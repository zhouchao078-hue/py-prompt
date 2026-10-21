"""Command-line entry point."""

import argparse
import sys

from prompt_search_agent.config import Settings
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.search.sqlite import (
    SqlitePromptSearchBackend,
)
from prompt_search_agent.skills.prompt_generation import (
    build_prompt_generation_skill,
)
from prompt_search_agent.storage import initialize_database


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

    print(final_prompt)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
