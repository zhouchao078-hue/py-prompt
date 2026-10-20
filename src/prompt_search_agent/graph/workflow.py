"""LangGraph workflow assembly.

TODO: Connect the nodes and compile the graph.
"""
from pathlib import Path

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from prompt_search_agent.chains.compose_prompt import create_compose_prompt
from prompt_search_agent.chains.parse_request import create_parse_request_chain
from prompt_search_agent.config import Settings
from prompt_search_agent.graph.nodes import (
    build_compose_prompts_node,
    build_parse_request_node,
    build_search_prompts_node,
)
from prompt_search_agent.graph.state import AgentState
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.search.fake import FakePromptSearchBackend


def build_workflow(parse_chain,search_backend,compose_chain):
    graph = StateGraph(AgentState)
    graph.add_node("parse_request",build_parse_request_node(parse_chain),)
    graph.add_node("search_prompt",build_search_prompts_node(search_backend),)
    graph.add_node("compose_prompt",build_compose_prompts_node(compose_chain),)
    graph.add_edge(START,"parse_request")
    graph.add_conditional_edges(
        "parse_request",
        route_after_parse,
    )
    graph.add_edge("search_prompt","compose_prompt",)
    graph.add_edge("compose_prompt",END)
    return graph.compile()

def route_after_parse(state: AgentState) -> str:
    if state.get("request") is None:
        return END
    return "search_prompt"


if __name__ == "__main__":
    settings = Settings()  # pyright: ignore[reportCallIssue]
    model = create_chat_model(settings)
    parse_chain = create_parse_request_chain(model)

    fixture_path = (
            Path(__file__).parents[3]
            / "tests"
            / "fixtures"
            / "prompts.jsonl"
    )
    search_backend = FakePromptSearchBackend(fixture_path)
    compose_chain = create_compose_prompt(model)
    workflow = build_workflow(parse_chain, search_backend,compose_chain,)
    result = workflow.invoke(
        {
            "user_query": "故宫雪夜里，一个穿汉服的少女，电影感，低机位，冷色调",
        }
    )
    if "final_prompt" not in result:
        print(result.get("error", "No final prompt"))
    else:
        print(result["final_prompt"])