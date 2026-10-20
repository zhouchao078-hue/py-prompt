"""Search backend protocol.

TODO: Define the search interface shared by all backends.
"""
from typing import Protocol

from prompt_search_agent.models import PromptCandidate, SearchRequest


class PromptSearchBackend(Protocol):
    def search(
            self,
            request: SearchRequest,
            top_k: int = 5
    ) -> list[PromptCandidate]:
        ...
