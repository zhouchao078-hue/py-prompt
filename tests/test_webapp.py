import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_search_agent.agent import AgentServiceResult
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
        on_stage=None,
        on_token=None,
    ) -> PromptServiceResult:
        self.queries.append(user_query)

        if on_stage is not None:
            on_stage("intent")
            on_stage("retrieval")

        if on_token is not None:
            on_token("雪夜")
            on_token("白猫")

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
        self.edit_calls: list[
            tuple[str, Path, bytes, str | None, bool]
        ] = []

    def invoke(
        self,
        prompt: str,
        aspect_ratio: str | None = None,
        use_cache: bool = True,
    ) -> ImageGenerationResult:
        self.calls.append((prompt, aspect_ratio, use_cache))
        return self.result

    def edit(
        self,
        prompt: str,
        image_path: Path,
        mask_bytes: bytes,
        aspect_ratio: str | None = None,
        use_cache: bool = True,
    ) -> ImageGenerationResult:
        self.edit_calls.append(
            (
                prompt,
                image_path,
                mask_bytes,
                aspect_ratio,
                use_cache,
            )
        )
        return self.result.model_copy(update={"prompt": prompt})


class FakeAgentService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run(
        self,
        user_goal: str,
        thread_id: str,
    ) -> AgentServiceResult:
        self.calls.append((user_goal, thread_id))
        return self._result(thread_id)

    def stream(
        self,
        user_goal: str,
        thread_id: str,
    ) -> Iterator[dict[str, Any]]:
        self.calls.append((user_goal, thread_id))
        yield {
            "event": "stage",
            "phase": "planning",
            "steps": 0,
        }
        yield {
            "event": "step",
            "phase": "plan",
            "action": "call_tool",
            "tool_name": "generate_prompt",
            "reason": "Need to generate a prompt.",
            "steps": 1,
        }
        yield {
            "event": "result",
            "data": self._result(thread_id).model_dump(),
        }

    @staticmethod
    def _result(thread_id: str) -> AgentServiceResult:
        return AgentServiceResult(
            run_id="agent-run",
            thread_id=thread_id,
            status="completed",
            response_type="prompt",
            prompt="agent generated prompt",
            tool_names=["generate_prompt"],
            steps=1,
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


def test_agent_endpoint_uses_agent_service() -> None:
    prompt_service = FakePromptService()
    agent_service = FakeAgentService()
    app = create_app(
        lambda: prompt_service,
        agent_service_factory=lambda: agent_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/agent",
            json={"message": "帮我生成提示词"},
        )

    assert response.status_code == 200
    assert response.json()["response_type"] == "prompt"
    assert response.json()["prompt"] == "agent generated prompt"
    assert response.json()["tool_names"] == ["generate_prompt"]
    assert agent_service.calls[0][0] == "帮我生成提示词"
    assert prompt_service.queries == []


def test_agent_stream_exposes_run_trace_events() -> None:
    agent_service = FakeAgentService()
    app = create_app(
        lambda: FakePromptService(),
        agent_service_factory=lambda: agent_service,
    )

    with TestClient(app) as client, client.stream(
        "POST",
        "/api/agent/stream",
        json={"message": "帮我生成提示词"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: open" in body
    assert "event: agent" in body
    assert '"event": "stage"' in body
    assert '"event": "step"' in body
    assert '"phase": "plan"' in body
    assert '"event": "result"' in body
    assert '"response_type": "prompt"' in body
    assert "event: end" in body
    assert len(agent_service.calls) == 1
    assert agent_service.calls[0][0] == "帮我生成提示词"


def test_agent_page_contains_live_progress_mounts() -> None:
    app = create_app(
        lambda: FakePromptService(),
        agent_service_factory=lambda: FakeAgentService(),
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'id="agentLiveStatus"' in response.text
    assert 'id="agentTraceStatus"' in response.text
    assert 'id="agentTraceDetail"' in response.text
    assert 'id="agentProgressBar"' in response.text
    assert 'id="previewImageActions"' in response.text
    assert 'id="agentImageActions"' in response.text
    assert 'id="imageEditorDialog"' in response.text
    assert 'id="imageEditorCanvas"' in response.text


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
    # 对外只给友好文案，内部异常原文留在服务端日志里。
    assert response.json()["detail"] == "这次没能生成，换个说法再试一次。"


def test_index_and_health_are_available() -> None:
    app = create_app(lambda: FakePromptService())

    with TestClient(app) as client:
        index_response = client.get("/")
        health_response = client.get("/api/health")

    assert index_response.status_code == 200
    assert "Prompt Atelier" in index_response.text

    health = health_response.json()
    assert health["status"] == "degraded"
    assert health["db"] == "unknown"
    assert health["prompt_count"] == 0
    assert health["readonly_library"] is True


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
    app = create_app(
        lambda: FakePromptService(),
        app_settings=settings,
    )

    with TestClient(app) as client:
        # 先建一条归属于本会话的对话，再往里写消息
        created = client.post(
            "/api/conversations",
            json={"tool": "prompt"},
        )
        thread_id = created.json()["thread_id"]
        repo.append_message(thread_id, "user", "first question")
        repo.append_message(thread_id, "assistant", "first answer")
        repo.append_message(thread_id, "user", "second question")
        repo.update_summary(thread_id, "compressed summary", 2)
        response = client.get(
            f"/api/history/{thread_id}",
            params={"limit": 20},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["summary"] == "compressed summary"
    assert [message["content"] for message in data["messages"]] == [
        "first question",
        "first answer",
        "second question",
    ]


def test_image_job_renders_in_background(tmp_path: Path) -> None:
    image_path = tmp_path / "job.png"
    image_path.write_bytes(b"job-image")
    image_result = ImageGenerationResult(
        image_id="job",
        file_name="job.png",
        file_path=image_path,
        prompt="job prompt",
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
        created = client.post(
            "/api/images/jobs",
            json={"prompt": "job prompt", "aspect_ratio": "1:1"},
        )
        job_id = created.json()["job_id"]
        job: dict = {"status": "pending"}

        for _ in range(60):
            job = client.get(f"/api/images/jobs/{job_id}").json()

            if job["status"] != "pending":
                break

            time.sleep(0.05)

        missing = client.get("/api/images/jobs/does-not-exist")

    assert created.status_code == 200
    assert created.json()["status"] == "pending"
    assert job["status"] == "done"
    assert job["image_url"] == "/api/images/job.png"
    assert missing.status_code == 404


def test_image_edit_job_uses_source_and_mask(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"source-image")
    edited_path = tmp_path / "edited.png"
    edited_path.write_bytes(b"edited-image")
    image_result = ImageGenerationResult(
        image_id="edited",
        file_name="edited.png",
        file_path=edited_path,
        prompt="replace the marked area",
        provider="openai-compatible",
        model="image-model",
        size="1024x1536",
    )
    image_skill = FakeImageSkill(image_result)
    app = create_app(
        lambda: FakePromptService(),
        image_skill_factory=lambda: image_skill,
        image_output_dir=tmp_path,
    )
    mask_data_url = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/images/edits/jobs",
            json={
                "prompt": "replace the marked area",
                "image_url": "/api/images/source.png",
                "mask_data_url": mask_data_url,
                "aspect_ratio": "2:3",
            },
        )
        job_id = created.json()["job_id"]
        job: dict = {"status": "pending"}

        for _ in range(60):
            job = client.get(f"/api/images/jobs/{job_id}").json()

            if job["status"] != "pending":
                break

            time.sleep(0.05)

    assert created.status_code == 200
    assert job["status"] == "done"
    assert job["image_url"] == "/api/images/edited.png"
    assert len(image_skill.edit_calls) == 1
    prompt, image_path, mask_bytes, ratio, use_cache = (
        image_skill.edit_calls[0]
    )
    assert prompt == "replace the marked area"
    assert image_path == source_path.resolve()
    assert mask_bytes.startswith(b"\x89PNG")
    assert ratio == "2:3"
    assert use_cache is True


def test_image_edit_rejects_source_outside_output_dir(
    tmp_path: Path,
) -> None:
    app = create_app(
        lambda: FakePromptService(),
        image_skill_factory=lambda: FakeImageSkill(
            build_image_result(tmp_path, "unused.png")
        ),
        image_output_dir=tmp_path,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/images/edits/jobs",
            json={
                "prompt": "change the marked area",
                "image_url": "/api/images/../secret.png",
                "mask_data_url": (
                    "data:image/png;base64,"
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
                ),
                "aspect_ratio": "1:1",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "原图文件名无效。"


def test_prompt_stream_emits_stage_and_result() -> None:
    app = create_app(lambda: FakePromptService())

    with TestClient(app) as client, client.stream(
        "POST",
        "/api/prompt/stream",
        json={"message": "雪夜里的白猫"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: stage" in body
    assert '"stage": "intent"' in body
    assert '"stage": "retrieval"' in body
    assert "event: result" in body
    assert "雪夜里的白猫" in body


def test_prompt_stream_emits_tokens() -> None:
    """提示词是长文本，应该逐段推给前端，而不是最后一次性蹦出来。"""
    app = create_app(lambda: FakePromptService())

    with TestClient(app) as client, client.stream(
        "POST",
        "/api/prompt/stream",
        json={"message": "雪夜里的白猫"},
    ) as response:
        body = "".join(response.iter_text())

    assert "event: token" in body
    assert '"text": "雪夜"' in body
    assert body.index("event: token") < body.index("event: result")


def test_version_endpoint_reports_commit() -> None:
    app = create_app(lambda: FakePromptService())

    with TestClient(app) as client:
        response = client.get("/api/version")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "prompt-atelier"
    assert "version" in data and "commit" in data


def test_index_assets_are_fingerprinted() -> None:
    app = create_app(lambda: FakePromptService())

    with TestClient(app) as client:
        html = client.get("/").text
        match = re.search(r"/static/app\.[0-9a-f]{8}\.js", html)

        assert match is not None, "index.html 里的 app.js 未加哈希指纹"

        hashed = client.get(match.group(0))
        plain = client.get("/static/app.js")
        missing = client.get("/static/nope.js")

    assert hashed.status_code == 200
    assert "immutable" in hashed.headers["cache-control"]
    assert plain.status_code == 200
    assert missing.status_code == 404


def test_index_is_not_cached() -> None:
    app = create_app(lambda: FakePromptService())

    with TestClient(app) as client:
        response = client.get("/")

    assert response.headers["cache-control"] == "no-cache"


def build_image_result(
    tmp_path: Path,
    name: str = "quota.png",
) -> ImageGenerationResult:
    image_path = tmp_path / name
    image_path.write_bytes(b"quota-image")

    return ImageGenerationResult(
        image_id=name,
        file_name=name,
        file_path=image_path,
        prompt="quota prompt",
        provider="openai-compatible",
        model="image-model",
        size="1024x1024",
    )


def test_image_job_is_rejected_when_disk_is_low(tmp_path: Path) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "quota.sqlite3",
        data_dir=tmp_path,
        min_free_disk_gb=1e9,
    )
    app = create_app(
        lambda: FakePromptService(),
        image_skill_factory=lambda: FakeImageSkill(
            build_image_result(tmp_path)
        ),
        image_output_dir=tmp_path,
        app_settings=settings,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/images/jobs",
            json={"prompt": "quota prompt"},
        )

    assert response.status_code == 503
    assert "存储空间" in response.json()["detail"]


def test_image_job_hourly_quota_returns_429(tmp_path: Path) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "quota.sqlite3",
        data_dir=tmp_path,
        image_per_hour=1,
        image_max_in_flight=4,
    )
    app = create_app(
        lambda: FakePromptService(),
        image_skill_factory=lambda: FakeImageSkill(
            build_image_result(tmp_path)
        ),
        image_output_dir=tmp_path,
        app_settings=settings,
    )

    with TestClient(app) as client:
        first = client.post(
            "/api/images/jobs",
            json={"prompt": "quota prompt"},
        )
        job_id = first.json()["job_id"]

        for _ in range(60):
            job = client.get(f"/api/images/jobs/{job_id}").json()

            if job["status"] != "pending":
                break

            time.sleep(0.05)

        second = client.post(
            "/api/images/jobs",
            json={"prompt": "quota prompt"},
        )

    assert first.status_code == 200
    assert second.status_code == 429
