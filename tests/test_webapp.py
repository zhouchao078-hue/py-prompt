from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.images import ImageGenerationResult
from prompt_search_agent.services.prompt_service import (
    PromptServiceError,
    PromptServiceResult,
)
from prompt_search_agent.storage import (
    ConversationRepository,
    initialize_database,
)
from prompt_search_agent.webapp import create_app


class FakePromptService:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.queries: list[str] = []

    def generate(
        self,
        user_query: str,
        thread_id: str | None = None,
    ) -> PromptServiceResult:
        self.queries.append(user_query)

        if self.should_fail:
            raise PromptServiceError("generation failed")

        return PromptServiceResult(
            final_prompt=f"prompt for {user_query}",
            cached=False,
            generated_from_brief=False,
            thread_id=thread_id or "test-thread",
        )


class FakeImageSkill:
    def __init__(self, result: ImageGenerationResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str | None, bool]] = []

    def invoke(
        self,
        prompt: str,
        aspect_ratio: str | None = None,
        use_cache: bool = True,
    ) -> ImageGenerationResult:
        self.calls.append((prompt, aspect_ratio, use_cache))
        return self.result


def test_prompt_endpoint_returns_prompt() -> None:
    service = FakePromptService()
    app = create_app(lambda: service)

    with TestClient(app) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "雪夜里的白猫"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "prompt": "prompt for 雪夜里的白猫",
        "reply": None,
        "response_type": "prompt",
        "intent": "create",
        "cached": False,
        "generated_from_brief": False,
        "thread_id": "test-thread",
        "sources": [],
    }
    assert service.queries == ["雪夜里的白猫"]


def test_media_endpoint_exposes_provider_status() -> None:
    app = create_app(lambda: FakePromptService())

    with TestClient(app) as client:
        response = client.post(
            "/api/media",
            json={
                "message": "火星上的机械鲸鱼",
                "media_type": "video",
                "aspect_ratio": "3:2",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["media_type"] == "video"
    assert data["aspect_ratio"] == "3:2"
    assert data["provider_status"] == "not_configured"
    assert data["prompt"] == "prompt for 火星上的机械鲸鱼"
    assert data["reply"] is None
    assert data["response_type"] == "prompt"
    assert data["intent"] == "create"
    assert data["thread_id"] == "test-thread"


def test_media_endpoint_generates_and_serves_image(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"image-bytes")
    image_result = ImageGenerationResult(
        image_id="generated",
        file_name="generated.png",
        file_path=image_path,
        prompt="prompt for a snowy cat",
        provider="openai-compatible",
        model="image-model",
        size="1024x1024",
    )
    image_skill = FakeImageSkill(image_result)
    app = create_app(
        lambda: FakePromptService(),
        image_skill_factory=lambda: image_skill,
        image_output_dir=tmp_path,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/media",
            json={
                "message": "a snowy cat",
                "media_type": "image",
                "aspect_ratio": "1:1",
            },
        )
        image_response = client.get(
            response.json()["image_url"],
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider_status"] == "generated"
    assert data["image_id"] == "generated"
    assert data["image_url"] == "/api/images/generated.png"
    assert data["prompt"] == "prompt for a snowy cat"
    assert image_skill.calls == [
        ("prompt for a snowy cat", "1:1", True)
    ]
    assert image_response.status_code == 200
    assert image_response.content == b"image-bytes"


def test_direct_image_endpoint_bypasses_prompt_service(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "direct.png"
    image_path.write_bytes(b"direct-image")
    image_result = ImageGenerationResult(
        image_id="direct",
        file_name="direct.png",
        file_path=image_path,
        prompt="safe rewritten prompt",
        provider="openai-compatible",
        model="image-model",
        size="1024x1536",
    )
    image_skill = FakeImageSkill(image_result)
    prompt_service = FakePromptService()
    app = create_app(
        lambda: prompt_service,
        image_skill_factory=lambda: image_skill,
        image_output_dir=tmp_path,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/images/generate",
            json={
                "prompt": "safe rewritten prompt",
                "aspect_ratio": "2:3",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "prompt": "safe rewritten prompt",
        "image_id": "direct",
        "image_url": "/api/images/direct.png",
        "image_cached": False,
        "provider": "openai-compatible",
        "model": "image-model",
        "size": "1024x1536",
    }
    assert prompt_service.queries == []
    assert image_skill.calls == [
        ("safe rewritten prompt", "2:3", True)
    ]


def test_prompt_endpoint_maps_service_error() -> None:
    app = create_app(lambda: FakePromptService(should_fail=True))

    with TestClient(app) as client:
        response = client.post(
            "/api/prompt",
            json={"message": "无法生成的请求"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "generation failed"


def test_index_and_health_are_available() -> None:
    app = create_app(lambda: FakePromptService())

    with TestClient(app) as client:
        index_response = client.get("/")
        health_response = client.get("/api/health")

    assert index_response.status_code == 200
    assert "Prompt Atelier" in index_response.text
    assert health_response.json() == {
        "status": "ok",
        "prompt_count": "0",
    }


def test_add_prompt_endpoint_inserts_manually(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    app = create_app(
        lambda: FakePromptService(),
        app_settings=settings,
    )

    with TestClient(app) as client:
        first = client.post(
            "/api/prompts",
            json={
                "prompt_text": "manual prompt with a snowy mountain",
                "category": "manual",
            },
        )
        second = client.post(
            "/api/prompts",
            json={
                "prompt_text": "manual prompt with a snowy mountain",
            },
        )

    assert first.status_code == 200
    assert first.json()["inserted"] is True
    assert second.status_code == 200
    assert second.json()["inserted"] is False


def test_history_endpoint_returns_full_conversation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    repo = ConversationRepository(settings.prompt_db_path)
    repo.append_message("history-thread", "user", "first question")
    repo.append_message("history-thread", "assistant", "first answer")
    repo.append_message("history-thread", "user", "second question")
    repo.update_summary("history-thread", "compressed summary", 2)
    app = create_app(
        lambda: FakePromptService(),
        app_settings=settings,
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/history/history-thread",
            params={"limit": 20},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == "history-thread"
    assert data["summary"] == "compressed summary"
    assert [message["content"] for message in data["messages"]] == [
        "first question",
        "first answer",
        "second question",
    ]
