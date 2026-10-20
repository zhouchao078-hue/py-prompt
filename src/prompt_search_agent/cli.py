"""Command-line entry point."""

import argparse
import sys
from pathlib import Path

from prompt_search_agent.chains.compose_prompt import create_compose_prompt
from prompt_search_agent.chains.parse_request import create_parse_request_chain
from prompt_search_agent.config import Settings
from prompt_search_agent.graph.workflow import build_workflow
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.search.fake import FakePromptSearchBackend
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

    parse_chain = create_parse_request_chain(model)
    compose_chain = create_compose_prompt(model)

    fixture_path = (
            Path(__file__).parents[2]
            / "tests"
            / "fixtures"
            / "prompts.jsonl"
    )
    search_backend = FakePromptSearchBackend(fixture_path)

    workflow = build_workflow(
        parse_chain,
        search_backend,
        compose_chain,
    )

    result = workflow.invoke({"user_query": user_query})
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
