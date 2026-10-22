"""LangGraph state definitions.

TODO: Define AgentState.
"""
from typing import NotRequired, TypedDict

from prompt_search_agent.models import PromptCandidate, SearchRequest, WebSource


class AgentState(TypedDict):
    user_query: str
    conversation_context: NotRequired[str]
    request: NotRequired[SearchRequest]
    candidates: NotRequired[list[PromptCandidate]]
    web_context: NotRequired[str]
    web_sources: NotRequired[list[WebSource]]
    reranked_candidates: NotRequired[list[PromptCandidate]]
    needs_generation: NotRequired[bool]
    generated_from_brief: NotRequired[bool]
    error: NotRequired[str]
    final_prompt: NotRequired[str]
