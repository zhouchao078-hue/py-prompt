"""LangGraph workflow assembly."""

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from prompt_search_agent.chains.compose_prompt import create_compose_prompt
from prompt_search_agent.chains.generate_prompt import (
    create_generate_prompt_chain,
)
from prompt_search_agent.chains.parse_request import create_parse_request_chain
from prompt_search_agent.chains.rerank_prompts import (
    create_rerank_prompts_chain,
)
from prompt_search_agent.config import Settings
from prompt_search_agent.graph.nodes import (
    build_compose_prompts_node,
    build_generate_prompt_node,
    build_parse_request_node,
    build_rerank_prompts_node,
    build_search_prompts_node,
    build_web_research_node,
)
from prompt_search_agent.graph.state import AgentState
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.search.sqlite import SqlitePromptSearchBackend


def build_workflow(
    parse_chain,
    search_backend,
    rerank_chain,
    compose_chain,
    generate_chain,
    web_search_tool=None,
    web_fetch_tool=None,
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
    graph.add_node(
        "generate_from_brief",
        build_generate_prompt_node(generate_chain),
    )

    web_enabled = (
        web_search_tool is not None
        and web_fetch_tool is not None
    )

    if web_enabled:
        graph.add_node(
            "web_research",
            build_web_research_node(
                web_search_tool,
                web_fetch_tool,
            ),
        )

    graph.add_edge(START, "parse_request")
    graph.add_conditional_edges(
        "parse_request",
        route_after_parse,
    )
    graph.add_edge("search_prompt", "rerank_prompts")
    graph.add_conditional_edges(
        "rerank_prompts",
        lambda state: route_after_rerank(state, web_enabled),
    )
    if web_enabled:
        graph.add_conditional_edges(
            "web_research",
            route_after_web_research,
        )
    graph.add_edge("compose_prompt", END)
    graph.add_edge("generate_from_brief", END)
    return graph.compile()


def route_after_parse(state: AgentState) -> str:
    if state.get("request") is None:
        return END
    return "search_prompt"


def route_after_rerank(
    state: AgentState,
    web_enabled: bool,
) -> str:
    if state.get("reranked_candidates"):
        return "compose_prompt"

    if state.get("needs_generation"):
        if web_enabled:
            return "web_research"
        return "generate_from_brief"

    return END


def route_after_web_research(state: AgentState) -> str:
    if state.get("web_context"):
        return "compose_prompt"

    if state.get("needs_generation"):
        return "generate_from_brief"

    return END


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
        create_generate_prompt_chain(model),
    )
    result = workflow.invoke(
        {"user_query": "雪山上戴红围巾的白色短腿小猫，电影感"}
    )
    print(result.get("final_prompt", result.get("error")))
