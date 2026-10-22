"""Command-line entry point."""

import argparse
import json
import sqlite3
import sys

from prompt_search_agent.chains.compose_prompt import (
    SYSTEM_PROMPT as COMPOSE_SYSTEM_PROMPT,
)
from prompt_search_agent.chains.parse_request import (
    SYSTEM_PROMPT as PARSE_SYSTEM_PROMPT,
)
from prompt_search_agent.config import Settings
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.search.sqlite import (
    SqlitePromptSearchBackend,
)
from prompt_search_agent.search.tokenizer import normalize_text
from prompt_search_agent.skills.prompt_generation import (
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search and compose an AIGC prompt",
    )
    parser.add_argument("query", nargs="+")
    args = parser.parse_args()

    user_query = " ".join(args.query)

    settings = Settings()  # pyright: ignore[reportCallIssue]
    initialize_database(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )

    normalized_query = normalize_text(user_query).casefold()
    prompt_version = build_prompt_version(
        PARSE_SYSTEM_PROMPT,
        COMPOSE_SYSTEM_PROMPT,
    )
    index_version = get_prompt_index_version(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    cache_key = build_cache_key(
        normalized_query=normalized_query,
        model_name=settings.deepseek_model,
        prompt_version=prompt_version,
        index_version=index_version,
    )

    cached_prompt = get_cached_prompt(
        settings.prompt_db_path,
        cache_key,
        settings.sqlite_busy_timeout_ms,
    )

    if cached_prompt is not None:
        print(cached_prompt)
        return 0

    model = create_chat_model(settings)

    search_backend = SqlitePromptSearchBackend(
        db_path=settings.prompt_db_path,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )

    skill = build_prompt_generation_skill(
        model,
        search_backend,
    )

    result = skill.invoke(user_query)
    final_prompt = result.get("final_prompt")

    if not final_prompt:
        print(
            result.get("error", "Failed to compose prompt"),
            file=sys.stderr,
        )
        return 1

    request = result.get("request")
    candidates = result.get("candidates") or []
    request_json = (
        request.model_dump_json()
        if request is not None
        else None
    )
    candidate_ids_json = json.dumps(
        [candidate.prompt_id for candidate in candidates],
        ensure_ascii=False,
    )

    try:
        save_cached_prompt(
            db_path=settings.prompt_db_path,
            cache_key=cache_key,
            normalized_query=normalized_query,
            model_name=settings.deepseek_model,
            prompt_version=prompt_version,
            index_version=index_version,
            final_prompt=final_prompt,
            request_json=request_json,
            candidate_ids_json=candidate_ids_json,
            busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        )
    except sqlite3.DatabaseError as exc:
        print(f"Cache write failed: {exc}", file=sys.stderr)

    print(final_prompt)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
