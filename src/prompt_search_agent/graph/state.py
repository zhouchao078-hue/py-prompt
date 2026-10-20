"""LangGraph state definitions.

TODO: Define AgentState.
"""
from typing import NotRequired, TypedDict

from prompt_search_agent.models import PromptCandidate, SearchRequest


class AgentState(TypedDict):
    user_query: str
    request: NotRequired[SearchRequest]
    candidates: NotRequired[list[PromptCandidate]]
    error: NotRequired[str]
    final_prompt: NotRequired[str]
