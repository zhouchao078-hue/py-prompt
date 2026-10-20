"""LangChain tool adapter for prompt retrieval."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from prompt_search_agent.models import SearchRequest
from prompt_search_agent.search.base import PromptSearchBackend


class SearchPromptsInput(BaseModel):
    """Input contract for the prompt retrieval tool."""

    request: SearchRequest
    top_k: int = Field(default=5, ge=1, le=20)


def build_search_prompts_tool(
    search_backend: PromptSearchBackend,
) -> StructuredTool:
    """Build a model-callable tool around a search backend."""

    def search_prompts(
        request: SearchRequest,
        top_k: int = 5,
    ) -> list[dict[str, object]]:
        candidates = search_backend.search(request, top_k=top_k)
        return [
            candidate.model_dump(mode="json")
            for candidate in candidates
        ]

    return StructuredTool.from_function(
        func=search_prompts,
        name="search_prompts",
        description=(
            "Search the local AIGC prompt library using structured visual "
            "requirements and return ranked prompt candidates."
        ),
        args_schema=SearchPromptsInput,
    )
