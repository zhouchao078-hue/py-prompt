from fastapi.testclient import TestClient

from prompt_search_agent.services.prompt_service import (
    PromptServiceError,
    PromptServiceResult,
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
                "aspect_ratio": "16:9",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["media_type"] == "video"
    assert data["aspect_ratio"] == "16:9"
    assert data["provider_status"] == "not_configured"
    assert data["prompt"] == "prompt for 火星上的机械鲸鱼"
    assert data["reply"] is None
    assert data["response_type"] == "prompt"
    assert data["intent"] == "create"
    assert data["thread_id"] == "test-thread"


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
