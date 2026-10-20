"""LangGraph node implementations.

TODO: Implement parse, search, and render nodes.
"""

from pydantic import ValidationError

from prompt_search_agent.graph.state import AgentState
from prompt_search_agent.models import SearchRequest
from prompt_search_agent.search.base import PromptSearchBackend

PARSE_ATTEMPTS = 3

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
        candidates = search_backend.search(request,top_k=5)
        return {"candidates": candidates}
    return search_node

def build_compose_prompts_node(compose_chain):
    def compose_node(state:AgentState) -> dict:
        request = state.get("request")
        candidates = state.get("candidates")
        if request is None:
            return {"error": "Missing request for prompt composition"}
        if not candidates :
            return {"error": "No matching prompt"}
        request_json = request.model_dump_json()
        candidates_text = "\n\n".join(
            candidate.prompt_text for candidate in candidates[:3]
        )
        final_prompt = compose_chain.invoke(
            {
                "request_json": request_json,
                "candidates_text": candidates_text,
            }
        )
        if not final_prompt:
            return {"error": "LLM returned an empty prompt"}
        return {"final_prompt": final_prompt.strip()}
    return compose_node




