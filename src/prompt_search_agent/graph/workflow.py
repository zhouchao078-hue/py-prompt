"""LangGraph workflow assembly."""

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from prompt_search_agent.chains.compose_prompt import create_compose_prompt
from prompt_search_agent.chains.parse_request import create_parse_request_chain
from prompt_search_agent.chains.rerank_prompts import (
    create_rerank_prompts_chain,
)
from prompt_search_agent.config import Settings
from prompt_search_agent.graph.nodes import (
    build_compose_prompts_node,
    build_parse_request_node,
    build_rerank_prompts_node,
    build_search_prompts_node,
)
from prompt_search_agent.graph.state import AgentState
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.search.sqlite import SqlitePromptSearchBackend


def build_workflow(
    parse_chain,
    search_backend,
    rerank_chain,
    compose_chain,
):
    graph = StateGraph(AgentState)
    graph.add_node(
        "parse_request",
        build_parse_request_node(parse_chain),
    )
    graph.add_node(
        "search_prompt",
        build_search_prompts_node(search_backend),
    )
    graph.add_node(
        "rerank_prompts",
        build_rerank_prompts_node(rerank_chain),
    )
    graph.add_node(
        "compose_prompt",
        build_compose_prompts_node(compose_chain),
    )

    graph.add_edge(START, "parse_request")
    graph.add_conditional_edges(
        "parse_request",
        route_after_parse,
    )
    graph.add_edge("search_prompt", "rerank_prompts")
    graph.add_edge("rerank_prompts", "compose_prompt")
    graph.add_edge("compose_prompt", END)
    return graph.compile()


def route_after_parse(state: AgentState) -> str:
    if state.get("request") is None:
        return END
    return "search_prompt"


if __name__ == "__main__":
    settings = Settings()  # pyright: ignore[reportCallIssue]
    model = create_chat_model(settings)
    search_backend = SqlitePromptSearchBackend(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    workflow = build_workflow(
        create_parse_request_chain(model),
        search_backend,
        create_rerank_prompts_chain(model),
        create_compose_prompt(model),
    )
    result = workflow.invoke(
        {"user_query": "雪山上戴红围巾的白色短腿小猫，电影感"}
    )
    print(result.get("final_prompt", result.get("error")))
