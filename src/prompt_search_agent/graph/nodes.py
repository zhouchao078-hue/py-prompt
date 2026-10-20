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
        for _ in range(PARSE_ATTEMPTS):
            raw_result = parse_chain.invoke({"query": query})

            if raw_result is None:
                continue

            try:
                request = SearchRequest.model_validate(raw_result)
            except ValidationError:
                continue

            return {"request": request}
        return {"request": request}
    return analysis_user_input


def build_search_prompts_node(search_backend: PromptSearchBackend):
    def search_node(state:AgentState) -> dict:
        request = state.get("request")
        if request is None:
            return {"error": "Missing parsed search request"}
        candidates = search_backend.search(request,top_k=5)
        return {"candidates": candidates}
    return search_node






