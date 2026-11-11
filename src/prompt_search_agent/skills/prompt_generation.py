"""Prompt generation skill built on the existing LangGraph workflow."""

import logging
from typing import Any

from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.chains.compose_prompt import create_compose_prompt
from prompt_search_agent.chains.generate_prompt import (
    create_generate_prompt_chain,
)
from prompt_search_agent.chains.parse_request import create_parse_request_chain
from prompt_search_agent.chains.rerank_prompts import (
    create_rerank_prompts_chain,
)
from prompt_search_agent.graph.workflow import build_workflow
from prompt_search_agent.log_utils import log_value
from prompt_search_agent.search.base import PromptSearchBackend

LOGGER = logging.getLogger(__name__)


class PromptGenerationSkill:
    """Invoke the prompt generation workflow with a user query."""

    def __init__(self, workflow: Any) -> None:
        self.workflow = workflow

    def invoke(
        self,
        user_query: str,
        conversation_context: str = "",
        on_token: Any | None = None,
    ) -> dict[str, Any]:
        LOGGER.info(
            "prompt.skill.start query=%s context_chars=%s streaming=%s",
            log_value(user_query),
            len(conversation_context),
            on_token is not None,
        )
        try:
            result = self.workflow.invoke(
                {
                    "user_query": user_query,
                    "conversation_context": conversation_context,
                },
                config={"configurable": {"on_token": on_token}},
            )
        except Exception:
            LOGGER.exception(
                "prompt.skill.failed query=%s",
                log_value(user_query),
            )
            raise

        LOGGER.info(
            "prompt.skill.output response_type=%s final_prompt=%s error=%s "
            "sources=%s",
            result.get("response_type"),
            log_value(result.get("final_prompt")),
            log_value(result.get("error")),
            len(result.get("web_sources") or []),
        )
        return result


def build_prompt_generation_skill(
    model: ChatDeepSeek,
    search_backend: PromptSearchBackend,
    web_search_tool: Any | None = None,
    web_fetch_tool: Any | None = None,
    web_mode: str = "on_demand",
) -> PromptGenerationSkill:
    """Build the prompt generation skill and its dependencies."""

    parse_chain = create_parse_request_chain(model)
    rerank_chain = create_rerank_prompts_chain(model)
    compose_chain = create_compose_prompt(model)
    generate_chain = create_generate_prompt_chain(model)
    workflow = build_workflow(
        parse_chain,
        search_backend,
        rerank_chain,
        compose_chain,
        generate_chain,
        web_search_tool=web_search_tool,
        web_fetch_tool=web_fetch_tool,
        web_mode=web_mode,
    )
    return PromptGenerationSkill(workflow)
