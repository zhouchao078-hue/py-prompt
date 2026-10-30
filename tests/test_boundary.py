"""边界测试：长度、数量、路径、并发与类型的临界值。"""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.images import ImageGenerationResult
from prompt_search_agent.services.prompt_service import PromptServiceResult
from prompt_search_agent.storage import ConversationRepository, initialize_database
from prompt_search_agent.webapp import create_app

ACCESS_CODE = "boundary-code"


class FakeService:
    def generate(self, user_query, thread_id=None, on_stage=None, on_token=None):
        return PromptServiceResult(
            final_prompt=f"prompt for {user_query}",
            cached=False,
            thread_id=thread_id or "boundary-thread",
        )


class FakeImageSkill:
    def __init__(self, result: ImageGenerationResult) -> None:
        self.result = result

    def invoke(self, prompt, aspect_ratio=None, use_cache=True):
        return self.result


def settings_for(tmp_path: Path, **overrides) -> Settings:
    defaults: dict = {
        "deepseek_api_key": SecretStr("test-key"),
        "prompt_db_path": tmp_path / "boundary.sqlite3",
        "data_dir": tmp_path,
    }
    defaults.update(overrides)
    settings = Settings(**defaults)
    initialize_database(settings.prompt_db_path)
    return settings


def build_image(tmp_path: Path) -> ImageGenerationResult:
    path = tmp_path / "boundary.png"
    path.write_bytes(b"boundary-image")
    return ImageGenerationResult(
        image_id="boundary",
        file_name="boundary.png",
        file_path=path,
        prompt="boundary prompt",
        provider="openai-compatible",
        model="m",
        size="1024x1024",
    )


def build_client(settings: Settings, tmp_path: Path) -> TestClient:
    app = create_app(
        lambda: FakeService(),
        image_skill_factory=lambda: FakeImageSkill(build_image(tmp_path)),
        image_output_dir=tmp_path,
        app_settings=settings,
    )
    return TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {ACCESS_CODE}"}


# —— 长度边界 ——


def test_message_at_max_length_is_accepted(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))

    with build_client(settings, tmp_path) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "雪" * 4000},
            headers=auth(),
        )

    assert response.status_code == 200


def test_message_over_max_length_is_rejected(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))

    with build_client(settings, tmp_path) as client:
        too_long = client.post(
            "/api/prompt",
            json={"message": "雪" * 4001},
            headers=auth(),
        )
        empty = client.post(
            "/api/prompt",
            json={"message": ""},
            headers=auth(),
        )

    assert too_long.status_code == 422
    assert empty.status_code == 422


def test_body_exactly_at_limit_is_allowed(tmp_path: Path) -> None:
    payload = json.dumps({"message": "x" * 20}).encode()
    settings = settings_for(
        tmp_path,
        demo_access_code=SecretStr(ACCESS_CODE),
        max_request_body_bytes=len(payload),
    )

    with build_client(settings, tmp_path) as client:
        at_limit = client.post(
            "/api/prompt",
            content=payload,
            headers={**auth(), "Content-Type": "application/json"},
        )

    assert at_limit.status_code == 200


def test_body_one_byte_over_limit_is_rejected(tmp_path: Path) -> None:
    payload = json.dumps({"message": "x" * 20}).encode()
    settings = settings_for(
        tmp_path,
        demo_access_code=SecretStr(ACCESS_CODE),
        max_request_body_bytes=len(payload) - 1,
    )

    with build_client(settings, tmp_path) as client:
        over = client.post(
            "/api/prompt",
            content=payload,
            headers={**auth(), "Content-Type": "application/json"},
        )

    assert over.status_code == 413


# —— 取值边界 ——


def test_invalid_aspect_ratio_and_media_type_are_rejected(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))

    with build_client(settings, tmp_path) as client:
        bad_ratio = client.post(
            "/api/media",
            json={"message": "猫", "media_type": "image", "aspect_ratio": "4:3"},
            headers=auth(),
        )
        bad_type = client.post(
            "/api/media",
            json={"message": "猫", "media_type": "gif"},
            headers=auth(),
        )

    assert bad_ratio.status_code == 422
    assert bad_type.status_code == 422


def test_history_limit_is_clamped(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))
    repo = ConversationRepository(settings.prompt_db_path)

    for index in range(3):
        repo.append_message("clamp-thread", "user", f"m{index}")

    from prompt_search_agent.guard import sign_thread_id

    headers = {
        **auth(),
        "x-thread-token": sign_thread_id(
            "clamp-thread",
            settings.thread_secret_value,
        ),
    }

    with build_client(settings, tmp_path) as client:
        zero = client.get("/api/history/clamp-thread?limit=0", headers=headers)
        negative = client.get(
            "/api/history/clamp-thread?limit=-5",
            headers=headers,
        )
        huge = client.get(
            "/api/history/clamp-thread?limit=100000",
            headers=headers,
        )

    assert len(zero.json()["messages"]) == 1
    assert len(negative.json()["messages"]) == 1
    assert len(huge.json()["messages"]) == 3


# —— 路径边界 ——


def test_image_path_traversal_is_rejected(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))

    with build_client(settings, tmp_path) as client:
        response = client.get(
            "/api/images/%2E%2E%2Fconfig.py",
            headers=auth(),
        )

    assert response.status_code == 404


def test_static_path_traversal_is_rejected(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))

    with build_client(settings, tmp_path) as client:
        response = client.get("/static/%2E%2E%2Fconfig.py")

    assert response.status_code == 404


# —— 数量边界 ——


def test_rate_limit_allows_exactly_the_limit(tmp_path: Path) -> None:
    settings = settings_for(
        tmp_path,
        demo_access_code=SecretStr(ACCESS_CODE),
        rate_limit_per_ip_per_hour=2,
        daily_request_cap=100,
    )

    with build_client(settings, tmp_path) as client:
        statuses = [
            client.post(
                "/api/prompt",
                json={"message": "猫"},
                headers=auth(),
            ).status_code
            for _ in range(3)
        ]

    assert statuses == [200, 200, 429]


def test_image_quota_allows_exactly_the_limit(tmp_path: Path) -> None:
    settings = settings_for(
        tmp_path,
        demo_access_code=SecretStr(ACCESS_CODE),
        rate_limit_per_ip_per_hour=100,
        image_per_hour=2,
        image_max_in_flight=4,
    )

    with build_client(settings, tmp_path) as client:
        first = client.post(
            "/api/images/jobs",
            json={"prompt": "猫"},
            headers=auth(),
        )
        job_id = first.json()["job_id"]

        for _ in range(60):
            job = client.get(f"/api/images/jobs/{job_id}", headers=auth()).json()

            if job["status"] != "pending":
                break

            time.sleep(0.05)

        second = client.post(
            "/api/images/jobs",
            json={"prompt": "猫"},
            headers=auth(),
        )
        third = client.post(
            "/api/images/jobs",
            json={"prompt": "猫"},
            headers=auth(),
        )

    assert [first.status_code, second.status_code, third.status_code] == [
        200,
        200,
        429,
    ]


# —— 输入内容边界 ——


def test_unicode_and_zero_width_message_is_accepted(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))

    with build_client(settings, tmp_path) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "🐱\u200b雪夜\u3000白猫"},
            headers=auth(),
        )

    assert response.status_code == 200


def test_invalid_json_body_returns_422(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))

    with build_client(settings, tmp_path) as client:
        response = client.post(
            "/api/prompt",
            content=b"{not-json",
            headers={**auth(), "Content-Type": "application/json"},
        )

    assert response.status_code == 422


def test_unknown_image_job_returns_404(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, demo_access_code=SecretStr(ACCESS_CODE))

    with build_client(settings, tmp_path) as client:
        response = client.get(
            "/api/images/jobs/does-not-exist",
            headers=auth(),
        )

    assert response.status_code == 404
