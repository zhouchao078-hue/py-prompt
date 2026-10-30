from pathlib import Path
from typing import Any

from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.graph.state import NO_MATCHING_PROMPT
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
        on_token=None,
    ) -> dict[str, Any]:
        self.contexts.append(conversation_context)
        return {
            "request": SearchRequest(subject=user_query),
            "candidates": [],
            "final_prompt": f"prompt for {user_query}",
        }


class NoMatchSkill:
    def invoke(
        self,
        user_query: str,
        conversation_context: str = "",
        on_token=None,
    ) -> dict[str, Any]:
        return {
            "candidates": [],
            "reranked_candidates": [],
            "needs_generation": False,
            "error": NO_MATCHING_PROMPT,
        }


class FakeSummaryChain:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def invoke(self, input_: dict[str, str]) -> str:
        self.calls.append(input_)
        return "较早对话摘要"


class FakeIntentChain:
    def __init__(self, result: IntentResult) -> None:
        self.result = result

    def invoke(self, input_: dict[str, str]) -> dict[str, Any]:
        return {
            "parsed": self.result,
        }


class FakeRegenerateChain:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def invoke(self, input_: dict[str, str]) -> str:
        self.calls.append(input_)
        return "重新生成后的提示词"


class FakeModifyChain:
    def __init__(self, output: str = "无违规的改写提示词") -> None:
        self.output = output
        self.calls: list[dict[str, str]] = []

    def invoke(self, input_: dict[str, str]) -> str:
        self.calls.append(input_)
        return self.output


class FakeChatSkill:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, str]] = []

    def invoke(
        self,
        user_query: str,
        intent: str,
        conversation_context: str,
        current_prompt: str = "",
    ) -> str:
        self.calls.append(
            {
                "user_query": user_query,
                "intent": intent,
                "conversation_context": conversation_context,
                "current_prompt": current_prompt,
            }
        )
        return self.reply


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


def test_repository_lists_full_history_in_order(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)
    repo = ConversationRepository(db_path)

    for index in range(6):
        repo.append_message("thread-full", "user", f"user-{index}")
        repo.append_message("thread-full", "assistant", f"assistant-{index}")

    messages = repo.list_messages("thread-full", limit=20)

    assert len(messages) == 12
    assert messages[0].content == "user-0"
    assert messages[-1].content == "assistant-5"


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
        intent_chain=FakeIntentChain(
            IntentResult(
                intent="vague_feedback",
                confidence=0.98,
                clarification_question=(
                    "你想调整主体、颜色、场景、风格、镜头还是画幅？"
                ),
                reason="用户表达不满意，但没有给出明确修改",
            )
        ),
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


def test_chat_intent_returns_message_without_generation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    skill = ContextAwareSkill()
    chat_skill = FakeChatSkill("reply from chat skill")
    service = PromptService(
        settings,
        skill,  # type: ignore[arg-type]
        intent_chain=FakeIntentChain(
            IntentResult(
                intent="chat",
                confidence=0.95,
                reason="casual greeting",
            )
        ),
        chat_skill=chat_skill,  # type: ignore[arg-type]
    )

    result = service.generate("hello", thread_id="thread-chat")

    assert result.response_type == "message"
    assert result.reply == "reply from chat skill"
    assert result.final_prompt is None
    assert skill.contexts == []
    assert chat_skill.calls == [
        {
            "user_query": "hello",
            "intent": "chat",
            "conversation_context": "",
            "current_prompt": "",
        }
    ]


def test_no_retrieval_result_returns_not_found(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    service = PromptService(
        settings,
        NoMatchSkill(),  # type: ignore[arg-type]
    )

    result = service.generate(
        "本地库里不存在的画面",
        thread_id="thread-not-found",
    )

    assert result.response_type == "not_found"
    assert result.final_prompt is None
    assert result.intent == "create"
    assert "未检索到匹配提示词" in (result.reply or "")


def test_regenerate_skips_search_and_uses_variation_hint(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    skill = ContextAwareSkill()
    regenerate_chain = FakeRegenerateChain()
    service = PromptService(
        settings,
        skill,  # type: ignore[arg-type]
        fallback_generate_chain=regenerate_chain,
        intent_chain=FakeIntentChain(
            IntentResult(
                intent="regenerate",
                confidence=0.97,
                reason="用户要求重新生成",
            )
        ),
    )

    result = service.generate("再来一版", thread_id="thread-regenerate")

    assert result.response_type == "prompt"
    assert result.final_prompt == "重新生成后的提示词"
    assert result.intent == "regenerate"
    assert skill.contexts == []
    assert "重新生成" in regenerate_chain.calls[0]["variation_hint"]


def test_modify_request_rewrites_without_search(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    skill = ContextAwareSkill()
    modify_chain = FakeModifyChain()
    service = PromptService(
        settings,
        skill,  # type: ignore[arg-type]
        modify_chain=modify_chain,
        intent_chain=FakeIntentChain(
            IntentResult(
                intent="question",
                confidence=0.8,
                assistant_reply="这是版权问题。",
                reason="模型误判成问题",
            )
        ),
    )
    query = "这个提示词提示违规你能修改吗？改成没有版权风险的版本"

    result = service.generate(
        query,
        thread_id="thread-modify",
    )

    assert result.response_type == "prompt"
    assert result.intent == "modify"
    assert result.final_prompt == "无违规的改写提示词"
    assert skill.contexts == []
    assert modify_chain.calls[0]["user_query"] == query
