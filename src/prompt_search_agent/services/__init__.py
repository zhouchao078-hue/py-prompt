"""Application services shared by CLI and web entry points."""

from prompt_search_agent.services.prompt_service import (
    PromptService,
    PromptServiceError,
    PromptServiceResult,
    build_prompt_service,
)

__all__ = [
    "PromptService",
    "PromptServiceError",
    "PromptServiceResult",
    "build_prompt_service",
]
