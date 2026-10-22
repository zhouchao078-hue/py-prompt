from pathlib import Path
from typing import Any

from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.models import IntentResult, SearchRequest
from prompt_search_agent.services.prompt_service import PromptService
from prompt_search_agent.storage import (
    ConversationRepository,
    initialize_database,
)


class ContextAwareSkill:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def invoke(
        self,
        user_query: str,
        conversation_context: str = "",
    ) -> dict[str, Any]:
        self.contexts.append(conversation_context)
        return {
            "request": SearchRequest(subject=user_query),
            "candidates": [],
            "final_prompt": f"prompt for {user_query}",
        }


class FakeSummaryChain:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def invoke(self, input_: dict[str, str]) -> str:
        self.calls.append(input_)
        return "较早对话摘要"


class FakeIntentChain:
    def invoke(self, input_: dict[str, str]) -> dict[str, Any]:
        return {
            "parsed": IntentResult(
                intent="vague_feedback",
                confidence=0.98,
                clarification_question=(
                    "你想调整主体、颜色、场景、风格、镜头还是画幅？"
                ),
                reason="用户表达不满意，但没有给出明确修改",
            )
        }


def test_repository_loads_recent_messages_in_order(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)
    repo = ConversationRepository(db_path)

    repo.append_message("thread-1", "user", "第一轮用户")
    repo.append_message("thread-1", "assistant", "第一轮助手")
    repo.append_message("thread-1", "user", "第二轮用户")
    repo.append_message("thread-1", "assistant", "第二轮助手")

    snapshot = repo.load_snapshot("thread-1", recent_message_limit=3)

    assert [message.content for message in snapshot.recent_messages] == [
        "第一轮助手",
        "第二轮用户",
        "第二轮助手",
    ]


def test_prompt_service_injects_recent_context_and_summary(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
        conversation_recent_messages=2,
        conversation_compress_after_messages=3,
    )
    initialize_database(settings.prompt_db_path)
    skill = ContextAwareSkill()
    summary_chain = FakeSummaryChain()
    service = PromptService(
        settings,
        skill,  # type: ignore[arg-type]
        summary_chain=summary_chain,
    )

    service.generate("第一轮", thread_id="thread-1")
    service.generate("第二轮", thread_id="thread-1")
    service.generate("第三轮", thread_id="thread-1")

    assert skill.contexts[0] == ""
    assert "第一轮" in skill.contexts[1]
    assert "较早对话摘要" in skill.contexts[2]
    assert summary_chain.calls


def test_delete_conversation_cascades_messages(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)
    repo = ConversationRepository(db_path)
    repo.append_message("thread-1", "user", "待删除")
    repo.delete_conversation("thread-1")

    snapshot = repo.load_snapshot("thread-1")

    assert snapshot.recent_messages == []


def test_vague_feedback_returns_clarification_without_generation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    skill = ContextAwareSkill()
    service = PromptService(
        settings,
        skill,  # type: ignore[arg-type]
        intent_chain=FakeIntentChain(),
    )

    result = service.generate(
        "我觉得这个不是很好",
        thread_id="thread-feedback",
    )

    assert result.response_type == "clarification"
    assert result.intent == "vague_feedback"
    assert result.final_prompt is None
    assert result.reply == (
        "你想调整主体、颜色、场景、风格、镜头还是画幅？"
    )
    assert skill.contexts == []
