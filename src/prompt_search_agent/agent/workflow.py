"""Bounded structured ReAct graph."""

from typing import Any, Literal

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from prompt_search_agent.agent.planner import (
    format_observations,
    tool_descriptions,
)
from prompt_search_agent.agent.state import (
    AgentArtifacts,
    AgentDecision,
    AgentRunState,
    AgentToolObservation,
)
from prompt_search_agent.agent.tools import (
    AgentToolContext,
    AgentToolRegistry,
)
from prompt_search_agent.models import WebSource

PLANNER_ATTEMPTS = 2


def build_agent_workflow(
    planner_chain: Any,
    registry: AgentToolRegistry,
    *,
    max_steps: int = 8,
    checkpointer: Any | None = None,
):
    graph = StateGraph(AgentRunState)

    def planner_node(state: AgentRunState) -> dict[str, Any]:
        step_count = int(state.get("step_count", 0))
        step_limit = int(state.get("max_steps", max_steps))

        if step_count >= step_limit:
            return {
                "status": "failed",
                "error": "AGENT_STEP_LIMIT",
                "final_reply": "任务步骤过多，已停止执行。",
            }

        inputs = {
            "user_goal": state["user_goal"],
            "conversation_context": state.get(
                "conversation_context",
                "",
            ),
            "current_prompt": state.get("current_prompt", ""),
            "step_count": step_count,
            "max_steps": step_limit,
            "observations_json": format_observations(
                state.get("observations", [])
            ),
            "tool_descriptions": tool_descriptions(registry),
        }

        for _ in range(PLANNER_ATTEMPTS):
            raw = planner_chain.invoke(inputs)
            decision = (
                raw.get("parsed")
                if isinstance(raw, dict)
                else None
            )

            if decision is not None:
                summaries = list(
                    state.get("decision_summaries", [])
                )
                summaries.append(decision.reason_summary)
                return {
                    "decision": decision,
                    "decision_summaries": summaries,
                    "step_count": step_count + 1,
                    "status": (
                        "waiting_user"
                        if decision.action == "ask_user"
                        else "planning"
                    ),
                }

        return {
            "status": "failed",
            "error": "PLANNER_INVALID_OUTPUT",
            "final_reply": "Agent 无法生成有效的下一步决策。",
        }

    def executor_node(state: AgentRunState) -> dict[str, Any]:
        decision = state.get("decision")
        observations = list(state.get("observations", []))
        artifacts = state.get("artifacts") or AgentArtifacts()

        if decision is None or decision.action != "call_tool":
            return {"status": "planning"}

        tool_name = decision.tool_name or ""
        result = registry.invoke(
            tool_name,
            decision.tool_input,
            AgentToolContext(
                thread_id=state["thread_id"],
                conversation_context=state.get(
                    "conversation_context",
                    "",
                ),
                current_prompt=state.get("current_prompt", ""),
            ),
        )
        observation = AgentToolObservation(
            tool_name=tool_name,
            ok=result.ok,
            data=result.data,
            error_code=result.error_code,
            message=result.message,
            retryable=result.retryable,
            elapsed_ms=result.elapsed_ms,
        )
        observations.append(observation)

        if result.ok:
            if tool_name in {"generate_prompt", "rewrite_prompt"}:
                final_prompt = result.data.get("final_prompt")

                if final_prompt:
                    artifacts.final_prompt = str(final_prompt)

            if tool_name == "generate_prompt":
                artifacts.sources = [
                    WebSource.model_validate(source)
                    for source in result.data.get("sources", [])
                ]

            if tool_name == "generate_image":
                image_id = result.data.get("image_id")
                image_url = result.data.get("image_url")

                if image_id:
                    artifacts.image_id = str(image_id)
                if image_url:
                    artifacts.image_url = str(image_url)
                if result.data.get("prompt"):
                    artifacts.final_prompt = str(result.data["prompt"])

            if tool_name == "get_conversation_history":
                artifacts.messages = list(
                    result.data.get("messages", [])
                )

            if tool_name == "add_prompt":
                artifacts.reply = (
                    "提示词已加入本地库。"
                    if result.data.get("inserted")
                    else "提示词已经存在。"
                )

        return {
            "observations": observations,
            "artifacts": artifacts,
            "status": "acting",
        }

    def evaluator_node(state: AgentRunState) -> dict[str, Any]:
        step_count = int(state.get("step_count", 0))
        step_limit = int(state.get("max_steps", max_steps))

        if step_count >= step_limit:
            return {
                "status": "failed",
                "error": "AGENT_STEP_LIMIT",
                "final_reply": "任务达到最大步骤数，已停止。",
            }

        return {"status": "planning"}

    def finalizer_node(state: AgentRunState) -> dict[str, Any]:
        artifacts = state.get("artifacts") or AgentArtifacts()
        decision = state.get("decision")

        if state.get("status") == "failed":
            return {
                "status": "failed",
                "response_type": "failed",
                "final_reply": state.get(
                    "final_reply",
                    "Agent 执行失败。",
                ),
            }

        if decision is not None and decision.action == "ask_user":
            return {
                "status": "waiting_user",
                "response_type": "message",
                "final_reply": (
                    decision.question
                    or "请补充更具体的要求。"
                ),
            }

        if artifacts.image_url:
            return {
                "status": "completed",
                "response_type": "image",
                "final_reply": artifacts.reply or "图片已生成。",
            }

        if artifacts.final_prompt:
            return {
                "status": "completed",
                "response_type": "prompt",
                "final_reply": artifacts.reply or "提示词已生成。",
            }

        if decision is not None and decision.final_response:
            return {
                "status": "completed",
                "response_type": "message",
                "final_reply": decision.final_response,
            }

        if artifacts.reply:
            return {
                "status": "completed",
                "response_type": "message",
                "final_reply": artifacts.reply,
            }

        return {
            "status": "failed",
            "response_type": "failed",
            "final_reply": "Agent 没有生成可用结果。",
        }

    def route_after_planner(
        state: AgentRunState,
    ) -> Literal["executor", "finalizer"]:
        if state.get("status") == "failed":
            return "finalizer"

        decision = state.get("decision")
        if decision is not None and decision.action == "call_tool":
            return "executor"

        return "finalizer"

    def route_after_evaluator(
        state: AgentRunState,
    ) -> Literal["planner", "finalizer"]:
        if state.get("status") == "failed":
            return "finalizer"

        return "planner"

    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("finalizer", finalizer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "executor": "executor",
            "finalizer": "finalizer",
        },
    )
    graph.add_edge("executor", "evaluator")
    graph.add_conditional_edges(
        "evaluator",
        route_after_evaluator,
        {
            "planner": "planner",
            "finalizer": "finalizer",
        },
    )
    graph.add_edge("finalizer", END)
    return graph.compile(checkpointer=checkpointer)


def decision_prompt(state: AgentRunState) -> str:
    """Debug helper for tests and local diagnostics."""
    decision: AgentDecision | None = state.get("decision")
    return decision.reason_summary if decision is not None else ""
