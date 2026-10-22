"""LangGraph node implementations.

TODO: Implement parse, search, and render nodes.
"""

from pydantic import ValidationError

from prompt_search_agent.graph.state import AgentState
from prompt_search_agent.models import SearchRequest
from prompt_search_agent.search.base import PromptSearchBackend

PARSE_ATTEMPTS = 3
RERANK_ATTEMPTS = 2

def build_parse_request_node(parse_chain):
    def analysis_user_input(state:AgentState) -> dict:
        query = state["user_query"]
        last_error = "No structured result"

        for _ in range(PARSE_ATTEMPTS):
            raw_result = parse_chain.invoke({"query": query})
            parsed = raw_result.get("parsed")
            if parsed is not None:
                try:
                    request = SearchRequest.model_validate(parsed)
                except ValidationError as exc:
                    last_error = str(exc)
                    continue

                return {"request": request}

            parsing_error = raw_result.get("parsing_error")
            raw = raw_result.get("raw")
            finish_reason = None
            if raw is not None:
                finish_reason = raw.response_metadata.get("finish_reason")

            last_error = (
                f"parsed is None; "
                f"parsing_error={parsing_error!r}; "
                f"finish_reason={finish_reason!r}"
            )

        return {"error": last_error}
    return analysis_user_input


def build_search_prompts_node(search_backend: PromptSearchBackend):
    def search_node(state:AgentState) -> dict:
        request = state.get("request")
        if request is None:
            return {"error": "Missing parsed search request"}
        candidates = search_backend.search(request, top_k=20)
        return {"candidates": candidates}
    return search_node


def build_rerank_prompts_node(rerank_chain):
    def rerank_prompts_node(state: AgentState) -> dict:
        user_query = state["user_query"]
        request = state.get("request")
        candidates = state.get("candidates") or []

        if request is None:
            return {"error": "Missing search request"}

        if not candidates:
            return {
                "reranked_candidates": [],
                "needs_generation": True,
            }

        candidates_text = "\n\n".join(
            (
                f"prompt_id: {candidate.prompt_id}\n"
                f"matched_terms: {candidate.matched_terms}\n"
                f"bm25_relevance: {candidate.relevance_score}\n"
                f"prompt_text: {candidate.prompt_text}"
            )
            for candidate in candidates[:20]
        )

        for _ in range(RERANK_ATTEMPTS):
            raw_result = rerank_chain.invoke(
                {
                    "user_query": user_query,
                    "request_json": request.model_dump_json(),
                    "candidates_text": candidates_text,
                }
            )
            parsed = (
                raw_result.get("parsed")
                if isinstance(raw_result, dict)
                else None
            )

            if parsed is None:
                continue

            candidates_by_id = {
                candidate.prompt_id: candidate
                for candidate in candidates
            }
            selected_ids = list(
                dict.fromkeys(
                    item.prompt_id
                    for item in parsed.selected
                )
            )
            selected = [
                candidates_by_id[prompt_id]
                for prompt_id in selected_ids
                if prompt_id in candidates_by_id
            ][:3]

            return {
                "reranked_candidates": selected,
                "needs_generation": parsed.needs_generation,
            }

        return {"error": "Rerank failed after retries"}

    return rerank_prompts_node


def build_compose_prompts_node(compose_chain):
    def compose_node(state:AgentState) -> dict:
        request = state.get("request")
        candidates = (
            state.get("reranked_candidates")
            or state.get("candidates")
            or []
        )
        if request is None:
            return {"error": "Missing request for prompt composition"}
        if not candidates:
            return {"error": "No matching prompt"}
        request_json = request.model_dump_json()
        candidates_text = "\n\n".join(
            candidate.prompt_text for candidate in candidates[:3]
        )
        final_prompt = compose_chain.invoke(
            {
                "user_query": state["user_query"],
                "request_json": request_json,
                "candidates_text": candidates_text,
            }
        )
        if not final_prompt:
            return {"error": "LLM returned an empty prompt"}
        return {
            "final_prompt": final_prompt.strip(),
            "generated_from_brief": False,
        }
    return compose_node


def build_generate_prompt_node(generate_chain):
    def generate_prompt_node(state: AgentState) -> dict:
        request = state.get("request")

        if request is None:
            return {"error": "Missing request for direct generation"}

        final_prompt = generate_chain.invoke(
            {
                "user_query": state["user_query"],
                "request_json": request.model_dump_json(),
            }
        )

        if not final_prompt:
            return {"error": "LLM returned an empty prompt"}

        return {
            "final_prompt": final_prompt.strip(),
            "generated_from_brief": True,
        }

    return generate_prompt_node




