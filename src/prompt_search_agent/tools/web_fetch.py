"""Tavily-backed webpage extraction tool using the official SDK."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from tavily import TavilyClient

from prompt_search_agent.config import Settings
from prompt_search_agent.tools.web_search import WebToolNotConfigured


class WebFetchInput(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=5)
    query: str | None = None


def build_web_fetch_tool(settings: Settings) -> StructuredTool:
    if (
        settings.tavily_api_key is None
        or not settings.tavily_api_key.get_secret_value().strip()
    ):
        raise WebToolNotConfigured("TAVILY_API_KEY is not configured")

    client = TavilyClient(
        api_key=settings.tavily_api_key.get_secret_value(),
    )

    def fetch_webpage(
        urls: list[str],
        query: str | None = None,
    ) -> dict:
        return client.extract(
            urls=urls,
            extract_depth="basic",
            include_images=False,
            format="text",
            query=query or "",
        )

    return StructuredTool.from_function(
        func=fetch_webpage,
        name="fetch_webpage",
        description=(
            "Extract readable text from one or more public webpages. "
            "Use this only after search_web has identified relevant URLs."
        ),
        args_schema=WebFetchInput,
    )
