"""Prompt generation skill built on the existing LangGraph workflow."""

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
from prompt_search_agent.search.base import PromptSearchBackend


class PromptGenerationSkill:
    """Invoke the prompt generation workflow with a user query."""

    def __init__(self, workflow: Any) -> None:
        self.workflow = workflow

    def invoke(self, user_query: str) -> dict[str, Any]:
        return self.workflow.invoke({"user_query": user_query})


def build_prompt_generation_skill(
    model: ChatDeepSeek,
    search_backend: PromptSearchBackend,
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
    )
    return PromptGenerationSkill(workflow)
