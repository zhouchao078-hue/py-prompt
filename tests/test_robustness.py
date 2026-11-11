"""健壮性测试：故障隔离、降级、并发与错误契约。"""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.cost import USAGE
from prompt_search_agent.graph.nodes import build_web_research_node
from prompt_search_agent.images import ImageGenerationError, ImageGenerationResult
from prompt_search_agent.maintenance import run_janitor
from prompt_search_agent.resilience import CircuitBreaker, UpstreamUnavailable
from prompt_search_agent.services.prompt_service import PromptServiceResult
from prompt_search_agent.storage import initialize_database
from prompt_search_agent.webapp import create_app

ACCESS_CODE = "robust-code"


class BoomService:
    def generate(self, user_query, thread_id=None, on_stage=None, on_token=None):
        raise PromptServiceError("upstream exploded")


class PromptServiceError(RuntimeError):
    pass


class CrashService:
    def generate(self, user_query, thread_id=None, on_stage=None, on_token=None):
        raise ValueError("unexpected internal state")


class FakeService:
    def generate(self, user_query, thread_id=None, on_stage=None, on_token=None):
        return PromptServiceResult(
            final_prompt="ok",
            cached=False,
            thread_id=thread_id or "robust-thread",
        )


class FailingImageSkill:
    def invoke(self, prompt, aspect_ratio=None, use_cache=True):
        raise ImageGenerationError("provider down")

    def edit(
        self,
        prompt,
        image_path,
        mask_bytes,
        aspect_ratio=None,
        use_cache=True,
    ):
        raise ImageGenerationError("provider down")


class FakeImageSkill:
    def __init__(self, result: ImageGenerationResult) -> None:
        self.result = result

    def invoke(self, prompt, aspect_ratio=None, use_cache=True):
        return self.result

    def edit(
        self,
        prompt,
        image_path,
        mask_bytes,
        aspect_ratio=None,
        use_cache=True,
    ):
        return self.result


def settings_for(tmp_path: Path, **overrides) -> Settings:
    defaults: dict = {
        "deepseek_api_key": SecretStr("test-key"),
        "prompt_db_path": tmp_path / "robust.sqlite3",
        "data_dir": tmp_path,
        "demo_access_code": SecretStr(ACCESS_CODE),
        "thread_secret": SecretStr("robust-thread-secret"),
    }
    defaults.update(overrides)
    settings = Settings(**defaults)
    initialize_database(settings.prompt_db_path)
    return settings


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {ACCESS_CODE}"}


def test_unhandled_exception_returns_error_contract(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    app = create_app(lambda: CrashService(), app_settings=settings)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "猫"},
            headers=auth(),
        )

    body = response.json()
    assert response.status_code == 500
    assert body["code"] == "internal_error"
    assert body["trace_id"]
    # 不能把内部堆栈或异常原文回给浏览器
    assert "unexpected internal state" not in response.text
    assert "Traceback" not in response.text


def test_metrics_survive_a_failed_request(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    app = create_app(lambda: CrashService(), app_settings=settings)

    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/prompt", json={"message": "猫"}, headers=auth())
        response = client.get("/metrics")

    assert response.status_code == 200
    assert 'status="500"' in response.text


def test_body_limit_checked_before_auth(tmp_path: Path) -> None:
    """超大请求体应该在鉴权之前就被砍掉，不该先白跑一次口径检查。"""
    settings = settings_for(tmp_path, max_request_body_bytes=64)

    with TestClient(create_app(lambda: FakeService(), app_settings=settings)) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "雪" * 500},
        )

    assert response.status_code == 413


def test_web_research_degrades_when_search_raises() -> None:
    class BrokenTool:
        def invoke(self, payload):
            raise RuntimeError("tavily timeout")

    node = build_web_research_node(BrokenTool(), BrokenTool())
    result = node({"user_query": "雪夜白猫"})

    assert result == {"web_context": "", "web_sources": []}


def test_image_job_failure_is_marked_not_hung(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    app = create_app(
        lambda: FakeService(),
        image_skill_factory=FailingImageSkill,
        image_output_dir=tmp_path,
        app_settings=settings,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/images/jobs",
            json={"prompt": "猫"},
            headers=auth(),
        )
        job_id = created.json()["job_id"]
        job: dict = {"status": "pending"}

        for _ in range(60):
            job = client.get(f"/api/images/jobs/{job_id}", headers=auth()).json()

            if job["status"] != "pending":
                break

            time.sleep(0.05)

    assert job["status"] == "failed"
    assert job["message"]


def test_sse_reports_error_and_terminates(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    app = create_app(lambda: BoomService(), app_settings=settings)

    with TestClient(app) as client, client.stream(
        "POST",
        "/api/prompt/stream",
        json={"message": "猫"},
        headers=auth(),
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: error" in body
    assert "event: open" in body


def test_janitor_survives_internal_failure(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "prompt_search_agent.maintenance.purge_expired_generated_images",
        boom,
    )
    monkeypatch.setattr(
        "prompt_search_agent.maintenance.delete_stale_cache",
        boom,
    )
    monkeypatch.setattr(
        "prompt_search_agent.maintenance.delete_stale_conversations",
        boom,
    )
    monkeypatch.setattr(
        "prompt_search_agent.maintenance.reclaim_database",
        boom,
    )

    result = run_janitor(settings)

    # 回收全炸了也要正常返回；快照不受影响，照常生成
    assert result == {
        "images": 0,
        "cache": 0,
        "conversations": 0,
        "backups": 1,
    }


def test_breaker_is_thread_safe_under_contention() -> None:
    breaker = CircuitBreaker(failure_threshold=50, cooldown_seconds=60)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: breaker.record_failure(), range(50)))

    with pytest.raises(UpstreamUnavailable):
        breaker.guard()


def test_health_does_not_flood_logs_when_db_is_broken(
    tmp_path: Path,
    caplog,
) -> None:
    """健康检查被高频轮询，数据库故障时不能每次请求都打一份堆栈。"""
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "never-initialized.sqlite3",
        data_dir=tmp_path,
    )
    app = create_app(lambda: FakeService(), app_settings=settings)

    with (
        caplog.at_level("WARNING", logger="prompt_search_agent.webapp"),
        TestClient(app) as client,
    ):
        for _ in range(10):
            response = client.get("/api/health")
            assert response.status_code == 200
    warnings = [
        record
        for record in caplog.records
        if "数据库不可用" in record.getMessage()
    ]

    assert len(warnings) == 1


def test_cost_endpoint_reports_usage(tmp_path: Path) -> None:
    USAGE.reset()
    settings = settings_for(
        tmp_path,
        llm_input_price_per_million=1.0,
        llm_output_price_per_million=2.0,
        image_price_per_image=0.5,
    )
    USAGE.record_llm(1_000_000, 500_000)
    USAGE.record_image()

    app = create_app(lambda: FakeService(), app_settings=settings)

    with TestClient(app) as client:
        data = client.get("/api/cost", headers=auth()).json()

    assert data["input_tokens"] == 1_000_000
    assert data["output_tokens"] == 500_000
    assert data["images"] == 1
    assert data["pricing_configured"] is True
    assert data["estimated_cost"] == pytest.approx(2.5)


def test_cost_is_zero_when_pricing_not_configured(tmp_path: Path) -> None:
    USAGE.reset()
    settings = settings_for(tmp_path)
    USAGE.record_llm(1000, 1000)

    app = create_app(lambda: FakeService(), app_settings=settings)

    with TestClient(app) as client:
        data = client.get("/api/cost", headers=auth()).json()

    assert data["pricing_configured"] is False
    assert data["estimated_cost"] == 0
    assert data["input_tokens"] == 1000


def test_concurrent_generation_requests_all_answered(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, rate_limit_per_ip_per_hour=100)

    def hit(_: int) -> int:
        app = create_app(lambda: FakeService(), app_settings=settings)

        with TestClient(app) as client:
            return client.post(
                "/api/prompt",
                json={"message": "猫"},
                headers=auth(),
            ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(hit, range(8)))

    assert statuses == [200] * 8
