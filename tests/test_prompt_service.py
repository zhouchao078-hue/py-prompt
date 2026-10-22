from pathlib import Path
from typing import Any

from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.services.prompt_service import PromptService
from prompt_search_agent.storage import initialize_database


class FailingSkill:
    def invoke(self, user_query: str) -> dict[str, Any]:
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
