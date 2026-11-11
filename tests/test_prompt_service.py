import sqlite3
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.services.prompt_service import PromptService
from prompt_search_agent.storage import ConversationRepository, initialize_database


class FailingSkill:
    def invoke(
        self,
        user_query: str,
        conversation_context: str = "",
        on_token=None,
    ) -> dict[str, Any]:
        return {"error": "parse failed"}


class FakeFallbackChain:
    def invoke(self, input_: dict[str, str]) -> str:
        return f"fallback for {input_['user_query']}"


def test_prompt_service_falls_back_to_direct_generation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    service = PromptService(
        settings,
        FailingSkill(),  # type: ignore[arg-type]
        fallback_generate_chain=FakeFallbackChain(),
    )

    result = service.generate("火星上的紫色机械鲸鱼")

    assert result.final_prompt == "fallback for 火星上的紫色机械鲸鱼"
    assert result.generated_from_brief is True
    assert result.cached is False
    assert result.thread_id


class SuccessfulSkill:
    def invoke(
        self,
        user_query: str,
        conversation_context: str = "",
        on_token=None,
    ) -> dict[str, Any]:
        return {"final_prompt": "a snowy cat"}


class BrokenWriteRepo(ConversationRepository):
    """模拟写锁：append_message 抛错，读路径正常。"""

    def append_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        raise sqlite3.OperationalError("database is locked")


def test_result_survives_conversation_write_failure(
    tmp_path: Path,
) -> None:
    """已经算完（且已付费）的提示词不能因为一次写锁就丢掉。"""
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )
    initialize_database(settings.prompt_db_path)
    service = PromptService(
        settings,
        SuccessfulSkill(),  # type: ignore[arg-type]
        conversation_repo=BrokenWriteRepo(settings.prompt_db_path),
    )

    result = service.generate("雪夜白猫")

    assert result.final_prompt == "a snowy cat"
    assert result.thread_id
