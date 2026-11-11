"""LangGraph workflow assembly."""

import logging

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

WEB_RESEARCH_MODES = ("on_demand", "always", "never")
LOGGER = logging.getLogger(__name__)

# 只有用户明确要"查资料"时才走联网。默认不查，因为联网是 20s 级别的慢路径。
WEB_TRIGGERS = (
    "联网",
    "搜索",
    "查一下",
    "查查",
    "最新",
    "资料",
    "参考",
    "网上",
    "search",
    "latest",
    "reference",
)


def wants_web_research(user_query: str) -> bool:
    lowered = user_query.casefold()
    return any(trigger in lowered for trigger in WEB_TRIGGERS)



def build_workflow(
    parse_chain,
    search_backend,
    rerank_chain,
    compose_chain,
    generate_chain,
    web_search_tool=None,
    web_fetch_tool=None,
    web_mode: str = "on_demand",
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
        lambda state: route_after_rerank(state, web_enabled, web_mode),
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
        LOGGER.info("prompt.route from=parse_request to=end reason=no_request")
        return END
    LOGGER.info("prompt.route from=parse_request to=search_prompt")
    return "search_prompt"


def route_after_rerank(
    state: AgentState,
    web_enabled: bool,
    web_mode: str = "on_demand",
) -> str:
    """决定本地命中后是组装、联网还是直接生成。

    两条原则：
    * 用户**明确要求联网**时优先满足，即使本地有命中 —— 否则用户说"查一下最新的"
      却被本地老数据糊弄过去，是更糟的体验。本地候选仍会一起送进组装。
    * 没命中且没要求联网时直接生成，不再阻塞在 20 秒级的抓取上。
    """
    if web_enabled and web_mode != "never":
        asked = web_mode == "always" or wants_web_research(
            str(state.get("user_query") or "")
        )

        if asked:
            LOGGER.info(
                "prompt.route from=rerank_prompts to=web_research mode=%s",
                web_mode,
            )
            return "web_research"

    if state.get("reranked_candidates"):
        LOGGER.info(
            "prompt.route from=rerank_prompts to=compose_prompt "
            "candidates=%s",
            len(state.get("reranked_candidates") or []),
        )
        return "compose_prompt"

    LOGGER.info(
        "prompt.route from=rerank_prompts to=generate_from_brief "
        "reason=no_reranked_candidates",
    )
    return "generate_from_brief"


def route_after_web_research(state: AgentState) -> str:
    # 联网拿到材料就组装；没拿到但本地有候选也照样组装，别浪费已有召回。
    if state.get("web_context"):
        LOGGER.info(
            "prompt.route from=web_research to=compose_prompt "
            "reason=web_context",
        )
        return "compose_prompt"

    if state.get("reranked_candidates") or state.get("candidates"):
        LOGGER.info(
            "prompt.route from=web_research to=compose_prompt "
            "reason=local_candidates",
        )
        return "compose_prompt"

    LOGGER.info(
        "prompt.route from=web_research to=generate_from_brief "
        "reason=no_sources",
    )
    return "generate_from_brief"


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
