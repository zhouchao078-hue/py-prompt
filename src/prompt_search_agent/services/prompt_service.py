"""Prompt generation service with exact-query caching."""

import json
import sqlite3
from typing import Any

from pydantic import BaseModel

from prompt_search_agent.chains.compose_prompt import COMPOSE_SYSTEM_PROMPT
from prompt_search_agent.chains.generate_prompt import (
    GENERATE_SYSTEM_PROMPT,
    create_generate_prompt_chain,
)
from prompt_search_agent.chains.parse_request import SYSTEM_PROMPT
from prompt_search_agent.chains.rerank_prompts import RERANK_SYSTEM_PROMPT
from prompt_search_agent.config import Settings
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.models import SearchRequest
from prompt_search_agent.search.sqlite import SqlitePromptSearchBackend
from prompt_search_agent.search.tokenizer import normalize_text
from prompt_search_agent.skills.prompt_generation import (
    PromptGenerationSkill,
    build_prompt_generation_skill,
)
from prompt_search_agent.storage import (
    build_cache_key,
    build_prompt_version,
    get_cached_prompt,
    get_prompt_index_version,
    initialize_database,
    save_cached_prompt,
)


class PromptServiceResult(BaseModel):
    final_prompt: str
    cached: bool
    generated_from_brief: bool = False


class PromptServiceError(RuntimeError):
    """Raised when the prompt generation workflow cannot produce output."""


class PromptService:
    def __init__(
        self,
        settings: Settings,
        skill: PromptGenerationSkill,
        fallback_generate_chain: Any | None = None,
    ) -> None:
        self.settings = settings
        self.skill = skill
        self.fallback_generate_chain = fallback_generate_chain
        self.prompt_version = build_prompt_version(
            SYSTEM_PROMPT,
            RERANK_SYSTEM_PROMPT,
            COMPOSE_SYSTEM_PROMPT,
            GENERATE_SYSTEM_PROMPT,
        )

    def generate(self, user_query: str) -> PromptServiceResult:
        normalized_query = normalize_text(user_query).casefold()
        index_version = get_prompt_index_version(
            self.settings.prompt_db_path,
            self.settings.sqlite_busy_timeout_ms,
        )
        cache_key = build_cache_key(
            normalized_query=normalized_query,
            model_name=self.settings.deepseek_model,
            prompt_version=self.prompt_version,
            index_version=index_version,
        )
        cached_prompt = get_cached_prompt(
            self.settings.prompt_db_path,
            cache_key,
            self.settings.sqlite_busy_timeout_ms,
        )

        if cached_prompt is not None:
            return PromptServiceResult(
                final_prompt=cached_prompt,
                cached=True,
                generated_from_brief=False,
            )

        result: dict[str, Any] = {}
        generated_from_brief = False

        try:
            result = self.skill.invoke(user_query)
            final_prompt = result.get("final_prompt")

            if not final_prompt:
                raise PromptServiceError(
                    str(result.get("error", "Prompt generation failed"))
                )
        except PromptServiceError:
            if self.fallback_generate_chain is None:
                raise

            fallback_request = SearchRequest(keywords=[user_query])
            final_prompt = self.fallback_generate_chain.invoke(
                {
                    "user_query": user_query,
                    "request_json": fallback_request.model_dump_json(),
                }
            )

            if not final_prompt:
                raise PromptServiceError(
                    "Fallback prompt generation failed"
                )

            result = {
                "request": fallback_request,
                "candidates": [],
            }
            generated_from_brief = True

        request = result.get("request")
        candidates = result.get("candidates") or []
        candidate_ids_json = json.dumps(
            [candidate.prompt_id for candidate in candidates],
            ensure_ascii=False,
        )

        try:
            save_cached_prompt(
                db_path=self.settings.prompt_db_path,
                cache_key=cache_key,
                normalized_query=normalized_query,
                model_name=self.settings.deepseek_model,
                prompt_version=self.prompt_version,
                index_version=index_version,
                final_prompt=final_prompt,
                request_json=(
                    request.model_dump_json()
                    if request is not None
                    else None
                ),
                candidate_ids_json=candidate_ids_json,
                busy_timeout_ms=self.settings.sqlite_busy_timeout_ms,
            )
        except sqlite3.DatabaseError:
            pass

        return PromptServiceResult(
            final_prompt=final_prompt,
            cached=False,
            generated_from_brief=(
                generated_from_brief
                or bool(result.get("generated_from_brief", False))
            ),
        )


def build_prompt_service(settings: Settings) -> PromptService:
    """Create the production prompt service."""

    initialize_database(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    model = create_chat_model(settings)
    search_backend = SqlitePromptSearchBackend(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    skill = build_prompt_generation_skill(model, search_backend)
    return PromptService(
        settings,
        skill,
        fallback_generate_chain=create_generate_prompt_chain(model),
    )
