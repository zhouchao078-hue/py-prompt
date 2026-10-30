"""公网安全层测试：口令、限流、日配额、会话签名。"""

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.guard import sign_thread_id
from prompt_search_agent.services.prompt_service import PromptServiceResult
from prompt_search_agent.storage import (
    ConversationRepository,
    initialize_database,
)
from prompt_search_agent.webapp import create_app

ACCESS_CODE = "demo-code"
THREAD_SECRET = "thread-secret"


class FakeService:
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
        return PromptServiceResult(
            final_prompt=f"prompt for {user_query}",
            cached=False,
            thread_id=thread_id or "security-thread",
        )


def build_settings(
    tmp_path: Path,
    per_ip_limit: int = 100,
    daily_cap: int = 100,
) -> Settings:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
        demo_access_code=SecretStr(ACCESS_CODE),
        thread_secret=SecretStr(THREAD_SECRET),
        rate_limit_per_ip_per_hour=per_ip_limit,
        daily_request_cap=daily_cap,
    )
    initialize_database(settings.prompt_db_path)
    return settings


def build_client(settings: Settings) -> TestClient:
    app = create_app(lambda: FakeService(), app_settings=settings)
    return TestClient(app)


def post_prompt(
    client: TestClient,
    token: str | None = ACCESS_CODE,
    message: str = "雪夜白猫",
) -> int:
    headers = {}

    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    response = client.post(
        "/api/prompt",
        json={"message": message},
        headers=headers,
    )
    return response.status_code


def test_request_without_code_is_rejected(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        assert post_prompt(client, token=None) == 401


def test_wrong_code_is_rejected(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        assert post_prompt(client, token="wrong-code") == 401


def test_correct_code_passes(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        assert post_prompt(client) == 200


def test_health_is_exempt_from_auth(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["db"] == "ok"


def test_version_is_exempt_from_auth(tmp_path: Path) -> None:
    """发布/回滚脚本需要不带口令确认当前版本。"""
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        response = client.get("/api/version")

    assert response.status_code == 200
    assert response.json()["name"] == "prompt-atelier"


def test_rate_limit_triggers_429(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, per_ip_limit=2)

    with build_client(settings) as client:
        assert post_prompt(client) == 200
        assert post_prompt(client) == 200
        assert post_prompt(client) == 429


def test_daily_quota_triggers_503(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, per_ip_limit=100, daily_cap=2)

    with build_client(settings) as client:
        assert post_prompt(client) == 200
        assert post_prompt(client) == 200
        assert post_prompt(client) == 503


def test_history_requires_matching_thread_token(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    thread_id = "security-thread"

    with build_client(settings) as client:
        denied = client.get(
            f"/api/history/{thread_id}",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )
        allowed = client.get(
            f"/api/history/{thread_id}",
            headers={
                "Authorization": f"Bearer {ACCESS_CODE}",
                "x-thread-token": sign_thread_id(thread_id, THREAD_SECRET),
            },
        )

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_prompt_rejects_foreign_thread_id(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "雪夜白猫", "thread_id": "someone-else"},
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert response.status_code == 403


def test_prompt_accepts_own_thread_id(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    thread_id = "my-own-thread"

    with build_client(settings) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "雪夜白猫", "thread_id": thread_id},
            headers={
                "Authorization": f"Bearer {ACCESS_CODE}",
                "x-thread-token": sign_thread_id(thread_id, THREAD_SECRET),
            },
        )

    assert response.status_code == 200
    assert response.json()["thread_token"] == sign_thread_id(
        thread_id,
        THREAD_SECRET,
    )


def test_readonly_library_blocks_writes(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings = settings.model_copy(update={"demo_readonly_library": True})

    with build_client(settings) as client:
        response = client.post(
            "/api/prompts",
            json={"prompt_text": "manual prompt"},
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert response.status_code == 403


def test_response_carries_trace_id(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "雪夜白猫"},
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert response.headers.get("x-request-id")


def test_delete_history_requires_matching_token(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    thread_id = "delete-me"

    with build_client(settings) as client:
        denied = client.delete(
            f"/api/history/{thread_id}",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )
        allowed = client.delete(
            f"/api/history/{thread_id}",
            headers={
                "Authorization": f"Bearer {ACCESS_CODE}",
                "x-thread-token": sign_thread_id(thread_id, THREAD_SECRET),
            },
        )

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_deleted_history_is_gone(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    repo = ConversationRepository(settings.prompt_db_path)
    thread_id = "wipe-me"
    repo.append_message(thread_id, "user", "hello")
    repo.append_message(thread_id, "assistant", "hi")
    headers = {
        "Authorization": f"Bearer {ACCESS_CODE}",
        "x-thread-token": sign_thread_id(thread_id, THREAD_SECRET),
    }

    with build_client(settings) as client:
        deleted = client.delete(f"/api/history/{thread_id}", headers=headers)
        after = client.get(f"/api/history/{thread_id}", headers=headers)

    assert deleted.json()["deleted"] == 2
    assert after.status_code == 200
    assert after.json()["messages"] == []
