"""上游熔断、限流绕过、请求体上限的故障注入测试。"""

import time

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.requests import Request as StarletteRequest

from prompt_search_agent.config import Settings
from prompt_search_agent.guard import DemoGuard
from prompt_search_agent.resilience import CircuitBreaker, UpstreamUnavailable
from prompt_search_agent.services.prompt_service import (
    PromptServiceError,
    PromptServiceResult,
)
from prompt_search_agent.webapp import create_app


class BoomService:
    """每次都让上游失败，用来触发熔断。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        user_query: str,
        thread_id: str | None = None,
        on_stage=None,
        on_token=None,
    ) -> PromptServiceResult:
        self.calls += 1
        raise PromptServiceError("上游挂了")


def build_settings(tmp_path, **overrides) -> Settings:
    defaults = {
        "deepseek_api_key": SecretStr("test-key"),
        "prompt_db_path": tmp_path / "prompt_index.sqlite3",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_breaker_opens_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)

    for _ in range(2):
        breaker.record_failure()

    breaker.guard()  # 还没到阈值，放行

    breaker.record_failure()

    with pytest.raises(UpstreamUnavailable):
        breaker.guard()


def test_breaker_resets_on_success() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()

    breaker.guard()  # 成功一次后重新计数


def test_breaker_half_opens_after_cooldown() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    breaker.record_failure()

    with pytest.raises(UpstreamUnavailable):
        breaker.guard()

    time.sleep(0.06)
    breaker.guard()  # 冷却结束，放探针过去


def test_failing_upstream_returns_503_instead_of_hanging(tmp_path) -> None:
    settings = build_settings(
        tmp_path,
        upstream_failure_threshold=2,
        upstream_cooldown_seconds=60,
    )
    service = BoomService()
    app = create_app(lambda: service, app_settings=settings)

    with TestClient(app) as client:
        first = client.post("/api/prompt", json={"message": "雪夜白猫"})
        second = client.post("/api/prompt", json={"message": "雪夜白猫"})
        third = client.post("/api/prompt", json={"message": "雪夜白猫"})

    assert first.status_code == 422
    assert second.status_code == 422
    # 第三次直接快速失败，不再打上游、不占并发槽位
    assert third.status_code == 503
    assert service.calls == 2


def test_oversized_body_is_rejected(tmp_path) -> None:
    settings = build_settings(tmp_path, max_request_body_bytes=200)
    app = create_app(lambda: BoomService(), app_settings=settings)

    with TestClient(app) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "雪" * 500},
        )

    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


def test_forwarded_for_uses_rightmost_entry() -> None:
    """最左那格是客户端自己填的，取它等于让攻击者换 IP 绕过限流。"""

    def build(forwarded: str) -> StarletteRequest:
        return StarletteRequest(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/prompt",
                "headers": [(b"x-forwarded-for", forwarded.encode())],
                "client": ("9.9.9.9", 1234),
                "query_string": b"",
            }
        )

    assert DemoGuard.client_ip(build("1.1.1.1, 2.2.2.2")) == "2.2.2.2"
    assert DemoGuard.client_ip(build("2.2.2.2")) == "2.2.2.2"


def test_spoofed_forwarded_for_cannot_bypass_rate_limit() -> None:
    guard = DemoGuard("code", per_ip_limit=1, daily_cap=100)

    def hit(fake: str) -> str:
        request = StarletteRequest(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/prompt",
                "headers": [
                    (b"authorization", b"Bearer code"),
                    (b"x-forwarded-for", fake.encode()),
                ],
                "client": ("9.9.9.9", 1234),
                "query_string": b"",
            }
        )

        rejection = guard.check(request, "trace")
        return "" if rejection is None else str(rejection.status_code)

    assert hit("1.1.1.1, 8.8.8.8") == ""
    # 客户端换伪造的最左 IP，但真实来源仍是 8.8.8.8
    assert hit("5.5.5.5, 8.8.8.8") == "429"


def test_ip_table_does_not_grow_without_bound(tmp_path) -> None:
    guard = DemoGuard("code", per_ip_limit=10, daily_cap=1000)

    for octet in range(300):
        request = StarletteRequest(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/prompt",
                "headers": [
                    (b"authorization", b"Bearer code"),
                    (b"x-forwarded-for", f"8.8.{octet // 250}.{octet % 250}".encode()),
                ],
                "client": ("9.9.9.9", 1234),
                "query_string": b"",
            }
        )
        guard.check(request, "trace")

    assert len(guard._hits) <= 300
