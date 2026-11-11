"""公网安全层测试：口令、限流、日配额、会话签名。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_search_agent.config import Settings
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


def test_failed_auth_attempts_are_rate_limited(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path, per_ip_limit=2)

    with build_client(settings) as client:
        statuses = [
            post_prompt(client, token="wrong-code")
            for _ in range(3)
        ]

    assert statuses == [401, 401, 429]


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


def test_polling_reads_do_not_consume_write_rate_limit(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path, per_ip_limit=2)
    headers = {"Authorization": f"Bearer {ACCESS_CODE}"}

    with build_client(settings) as client:
        reads = [
            client.get("/api/session", headers=headers).status_code
            for _ in range(5)
        ]
        writes = [
            post_prompt(client)
            for _ in range(3)
        ]

    assert reads == [200, 200, 200, 200, 200]
    assert writes == [200, 200, 429]


def test_session_cookie_is_secure_behind_https_proxy(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    settings = settings.model_copy(update={"public_mode": True})

    with build_client(settings) as client:
        response = client.get(
            "/api/session",
            headers={
                "Authorization": f"Bearer {ACCESS_CODE}",
                "x-forwarded-proto": "https",
            },
        )

    cookie = response.headers.get("set-cookie", "").lower()
    assert "secure" in cookie
    assert "httponly" in cookie


def test_public_mode_requires_access_code() -> None:
    settings = Settings(
        public_mode=True,
        thread_secret=SecretStr("custom-secret"),
    )

    with pytest.raises(RuntimeError, match="DEMO_ACCESS_CODE"):
        settings.assert_runtime_safe()


def test_public_mode_requires_custom_thread_secret() -> None:
    settings = Settings(
        public_mode=True,
        demo_access_code=SecretStr(ACCESS_CODE),
    )

    with pytest.raises(RuntimeError, match="THREAD_SECRET"):
        settings.assert_runtime_safe()


def create_conversation(client, tool: str = "prompt") -> str:
    response = client.post(
        "/api/conversations",
        json={"tool": tool},
        headers={"Authorization": f"Bearer {ACCESS_CODE}"},
    )
    assert response.status_code == 200
    return response.json()["thread_id"]


def test_history_is_scoped_to_the_session(tmp_path: Path) -> None:
    """用别人的 thread_id 读不到内容，也写不进去。"""
    settings = build_settings(tmp_path)

    with build_client(settings) as owner:
        thread_id = create_conversation(owner)
        ConversationRepository(settings.prompt_db_path).append_message(
            thread_id,
            "user",
            "别人的私密对话",
        )
        mine = owner.get(
            f"/api/history/{thread_id}",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert mine.status_code == 200
    assert [m["content"] for m in mine.json()["messages"]] == [
        "别人的私密对话"
    ]

    # 另一个浏览器：有自己的会话，但没有这条对话的归属
    with build_client(settings) as other:
        other.get(
            "/api/session",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )
        leak = other.get(
            f"/api/history/{thread_id}",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )
        missing = other.get(
            "/api/history/never-existed",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert leak.status_code == 403
    assert missing.status_code == 403


def test_prompt_with_unknown_thread_id_starts_new_conversation(
    tmp_path: Path,
) -> None:
    """传入不属于本会话的 thread_id 时，不报错也不串号，直接开新的。"""
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "雪夜白猫", "thread_id": "someone-else"},
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert response.status_code == 200
    assert response.json()["thread_id"] != "someone-else"


def test_unknown_thread_id_does_not_reach_that_conversation(
    tmp_path: Path,
) -> None:
    """丢弃是安全的：写不进别人的对话，也读不到。"""
    settings = build_settings(tmp_path)
    repo = ConversationRepository(settings.prompt_db_path)

    with build_client(settings) as owner:
        victim = create_conversation(owner)
        repo.append_message(victim, "user", "别人的私密对话")

    with build_client(settings) as intruder:
        intruder.post(
            "/api/prompt",
            json={"message": "雪夜白猫", "thread_id": victim},
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    messages = repo.list_messages(victim)
    assert [item.content for item in messages] == ["别人的私密对话"]


def test_prompt_continues_own_conversation(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with build_client(settings) as client:
        thread_id = create_conversation(client)
        response = client.post(
            "/api/prompt",
            json={"message": "雪夜白猫", "thread_id": thread_id},
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert response.status_code == 200
    assert response.json()["thread_id"] == thread_id


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


def test_delete_history_requires_ownership(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    repo = ConversationRepository(settings.prompt_db_path)

    with build_client(settings) as owner:
        thread_id = create_conversation(owner)
        repo.append_message(thread_id, "user", "hello")
        repo.append_message(thread_id, "assistant", "hi")
        headers = {"Authorization": f"Bearer {ACCESS_CODE}"}
        deleted = owner.delete(f"/api/history/{thread_id}", headers=headers)
        after = owner.get(f"/api/history/{thread_id}", headers=headers)

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 2
    # 删掉之后归属也断了，再读就是 403（不区分"不存在"和"不属于你"）
    assert after.status_code == 403

    # 会话删除后归属也断了：另一个浏览器仍然读不到
    with build_client(settings) as other:
        other.get(
            "/api/session",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )
        denied = other.delete(
            f"/api/history/{thread_id}",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert denied.status_code == 403


def test_foreign_conversation_cannot_be_deleted(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    repo = ConversationRepository(settings.prompt_db_path)

    with build_client(settings) as owner:
        thread_id = create_conversation(owner)
        repo.append_message(thread_id, "user", "别删我的")

    with build_client(settings) as intruder:
        intruder.get(
            "/api/session",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )
        denied = intruder.delete(
            f"/api/history/{thread_id}",
            headers={"Authorization": f"Bearer {ACCESS_CODE}"},
        )

    assert denied.status_code == 403
    assert [m.content for m in repo.list_messages(thread_id)] == ["别删我的"]
