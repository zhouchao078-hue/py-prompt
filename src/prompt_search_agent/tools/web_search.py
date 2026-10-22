"""Tavily-backed web search tool using the official SDK."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from tavily import TavilyClient

from prompt_search_agent.config import Settings


class WebToolNotConfigured(RuntimeError):
    """Raised when Tavily credentials are unavailable."""


class WebSearchInput(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=10)


def build_web_search_tool(settings: Settings) -> StructuredTool:
    if (
        settings.tavily_api_key is None
        or not settings.tavily_api_key.get_secret_value().strip()
    ):
        raise WebToolNotConfigured("TAVILY_API_KEY is not configured")

    client = TavilyClient(
        api_key=settings.tavily_api_key.get_secret_value(),
    )

    def search_web(
        query: str,
        max_results: int = settings.tavily_max_results,
    ) -> dict:
        return client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
            include_raw_content=False,
            include_images=False,
            exclude_domains=[
                "facebook.com",
                "instagram.com",
                "x.com",
                "twitter.com",
                "tiktok.com",
                "pinterest.com",
            ],
        )

    return StructuredTool.from_function(
        func=search_web,
        name="search_web",
        description=(
            "Search the public web for current visual references, prompt "
            "styles, scenes, or production details. Return titles, URLs, "
            "snippets, and relevance scores."
        ),
        args_schema=WebSearchInput,
    )
