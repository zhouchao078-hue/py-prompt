import argparse
from typing import Any, cast

from prompt_search_agent.chains.parse_request import (
    create_parse_request_chain,
)
from prompt_search_agent.chains.rerank_prompts import (
    create_rerank_prompts_chain,
)
from prompt_search_agent.config import Settings
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.models import SearchRequest
from prompt_search_agent.search.sqlite import SqlitePromptSearchBackend


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a live DeepSeek rerank test",
    )
    parser.add_argument(
        "query",
        nargs="+",
        help="Natural-language prompt request",
    )
    args = parser.parse_args()
    user_query = " ".join(args.query)

    settings = Settings()  # pyright: ignore[reportCallIssue]
    model = create_chat_model(settings)

    parse_chain = create_parse_request_chain(model)
    raw_parse_result = cast(
        dict[str, Any],
        parse_chain.invoke({"query": user_query}),
    )
    parsed = raw_parse_result["parsed"]

    if parsed is None:
        print("Parsing failed:", raw_parse_result["parsing_error"])
        return 1

    request = SearchRequest.model_validate(parsed)
    search_backend = SqlitePromptSearchBackend(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    candidates = search_backend.search(request, top_k=20)

    if not candidates:
        print("No search candidates")
        return 1

    candidates_text = "\n\n".join(
        (
            f"prompt_id: {candidate.prompt_id}\n"
            f"matched_terms: {candidate.matched_terms}\n"
            f"bm25_relevance: {candidate.relevance_score}\n"
            f"prompt_text: {candidate.prompt_text}"
        )
        for candidate in candidates
    )

    rerank_chain = create_rerank_prompts_chain(model)
    raw_rerank_result = cast(
        dict[str, Any],
        rerank_chain.invoke(
            {
                "user_query": user_query,
                "conversation_context": "",
                "request_json": request.model_dump_json(),
                "candidates_text": candidates_text,
            }
        ),
    )
    rerank_result = raw_rerank_result["parsed"]

    if rerank_result is None:
        print("Rerank parsing failed:", raw_rerank_result["parsing_error"])
        return 1

    print(rerank_result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
