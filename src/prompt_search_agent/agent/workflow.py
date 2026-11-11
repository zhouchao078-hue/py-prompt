"""Bounded structured ReAct graph."""

import logging
from typing import Any, Literal

from langgraph.constants import END, START
from langgraph.graph import StateGraph
from pydantic import ValidationError

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
from prompt_search_agent.log_utils import log_value
from prompt_search_agent.models import WebSource

PLANNER_ATTEMPTS = 2
LOGGER = logging.getLogger(__name__)


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
        LOGGER.info(
            "agent.node.enter node=planner run=%s thread=%s step=%s/%s "
            "goal=%s context_chars=%s current_prompt=%s observations=%s",
            state.get("run_id"),
            state.get("thread_id"),
            step_count,
            step_limit,
            log_value(state.get("user_goal")),
            len(state.get("conversation_context", "")),
            log_value(state.get("current_prompt")),
            len(state.get("observations", [])),
        )

        if step_count >= step_limit:
            LOGGER.warning(
                "agent.node.limit node=planner run=%s step=%s max=%s",
                state.get("run_id"),
                step_count,
                step_limit,
            )
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

        for attempt in range(PLANNER_ATTEMPTS):
            LOGGER.info(
                "agent.planner.request run=%s attempt=%s/%s",
                state.get("run_id"),
                attempt + 1,
                PLANNER_ATTEMPTS,
            )
            raw = planner_chain.invoke(inputs)
            parsed_decision = (
                raw.get("parsed")
                if isinstance(raw, dict)
                else None
            )

            if parsed_decision is not None:
                try:
                    decision = AgentDecision.model_validate(parsed_decision)
                except ValidationError as exc:
                    LOGGER.warning(
                        "agent.planner.invalid_output run=%s attempt=%s "
                        "error=%s",
                        state.get("run_id"),
                        attempt + 1,
                        log_value(str(exc)),
                    )
                    continue

                LOGGER.info(
                    "agent.node.output node=planner run=%s step=%s action=%s "
                    "tool=%s tool_input=%s question=%s final_response=%s "
                    "reason=%s",
                    state.get("run_id"),
                    step_count + 1,
                    decision.action,
                    decision.tool_name,
                    log_value(decision.tool_input),
                    log_value(decision.question),
                    log_value(decision.final_response),
                    log_value(decision.reason_summary),
                )
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

        LOGGER.error(
            "agent.node.invalid_output node=planner run=%s attempts=%s",
            state.get("run_id"),
            PLANNER_ATTEMPTS,
        )
        return {
            "status": "failed",
            "error": "PLANNER_INVALID_OUTPUT",
            "final_reply": "Agent 无法生成有效的下一步决策。",
        }

    def executor_node(state: AgentRunState) -> dict[str, Any]:
        decision = state.get("decision")
        observations = list(state.get("observations", []))
        artifacts = state.get("artifacts") or AgentArtifacts()
        LOGGER.info(
            "agent.node.enter node=executor run=%s thread=%s decision=%s "
            "observations=%s",
            state.get("run_id"),
            state.get("thread_id"),
            log_value(decision),
            len(observations),
        )

        if decision is None or decision.action != "call_tool":
            LOGGER.info(
                "agent.node.output node=executor run=%s action=no_tool",
                state.get("run_id"),
            )
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
        LOGGER.info(
            "agent.executor.tool_output run=%s tool=%s ok=%s code=%s "
            "retryable=%s elapsed_ms=%s data=%s message=%s",
            state.get("run_id"),
            tool_name,
            result.ok,
            result.error_code,
            result.retryable,
            result.elapsed_ms,
            log_value(result.data),
            log_value(result.message),
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

        LOGGER.info(
            "agent.node.output node=executor run=%s status=acting "
            "prompt=%s image_id=%s image_url=%s sources=%s reply=%s",
            state.get("run_id"),
            log_value(artifacts.final_prompt),
            artifacts.image_id,
            artifacts.image_url,
            len(artifacts.sources),
            log_value(artifacts.reply),
        )
        return {
            "observations": observations,
            "artifacts": artifacts,
            "status": "acting",
        }

    def evaluator_node(state: AgentRunState) -> dict[str, Any]:
        step_count = int(state.get("step_count", 0))
        step_limit = int(state.get("max_steps", max_steps))
        latest = (
            state.get("observations", [])[-1]
            if state.get("observations")
            else None
        )
        LOGGER.info(
            "agent.node.enter node=evaluator run=%s step=%s/%s latest=%s",
            state.get("run_id"),
            step_count,
            step_limit,
            log_value(latest),
        )

        if step_count >= step_limit:
            LOGGER.warning(
                "agent.node.output node=evaluator run=%s status=failed "
                "reason=step_limit",
                state.get("run_id"),
            )
            return {
                "status": "failed",
                "error": "AGENT_STEP_LIMIT",
                "final_reply": "任务达到最大步骤数，已停止。",
            }

        LOGGER.info(
            "agent.node.output node=evaluator run=%s status=planning "
            "decision=continue",
            state.get("run_id"),
        )
        return {"status": "planning"}

    def finalizer_node(state: AgentRunState) -> dict[str, Any]:
        artifacts = state.get("artifacts") or AgentArtifacts()
        decision = state.get("decision")
        LOGGER.info(
            "agent.node.enter node=finalizer run=%s status=%s decision=%s "
            "prompt=%s image_id=%s image_url=%s sources=%s reply=%s",
            state.get("run_id"),
            state.get("status"),
            log_value(decision),
            log_value(artifacts.final_prompt),
            artifacts.image_id,
            artifacts.image_url,
            len(artifacts.sources),
            log_value(artifacts.reply),
        )

        if state.get("status") == "failed":
            LOGGER.warning(
                "agent.finalizer.output run=%s response_type=failed "
                "status=failed error=%s reply=%s",
                state.get("run_id"),
                state.get("error"),
                log_value(state.get("final_reply")),
            )
            return {
                "status": "failed",
                "response_type": "failed",
                "final_reply": state.get(
                    "final_reply",
                    "Agent 执行失败。",
                ),
            }

        if decision is not None and decision.action == "ask_user":
            LOGGER.info(
                "agent.finalizer.output run=%s response_type=message "
                "status=waiting_user question=%s",
                state.get("run_id"),
                log_value(decision.question),
            )
            return {
                "status": "waiting_user",
                "response_type": "message",
                "final_reply": (
                    decision.question
                    or "请补充更具体的要求。"
                ),
            }

        if artifacts.image_url:
            LOGGER.info(
                "agent.finalizer.output run=%s response_type=image "
                "status=completed image_id=%s image_url=%s",
                state.get("run_id"),
                artifacts.image_id,
                artifacts.image_url,
            )
            return {
                "status": "completed",
                "response_type": "image",
                "final_reply": artifacts.reply or "图片已生成。",
            }

        if artifacts.final_prompt:
            LOGGER.info(
                "agent.finalizer.output run=%s response_type=prompt "
                "status=completed prompt=%s",
                state.get("run_id"),
                log_value(artifacts.final_prompt),
            )
            return {
                "status": "completed",
                "response_type": "prompt",
                "final_reply": artifacts.reply or "提示词已生成。",
            }

        if decision is not None and decision.final_response:
            LOGGER.info(
                "agent.finalizer.output run=%s response_type=message "
                "status=completed reply=%s",
                state.get("run_id"),
                log_value(decision.final_response),
            )
            return {
                "status": "completed",
                "response_type": "message",
                "final_reply": decision.final_response,
            }

        if artifacts.reply:
            LOGGER.info(
                "agent.finalizer.output run=%s response_type=message "
                "status=completed reply=%s",
                state.get("run_id"),
                log_value(artifacts.reply),
            )
            return {
                "status": "completed",
                "response_type": "message",
                "final_reply": artifacts.reply,
            }

        LOGGER.error(
            "agent.finalizer.output run=%s response_type=failed "
            "status=failed reason=no_artifacts",
            state.get("run_id"),
        )
        return {
            "status": "failed",
            "response_type": "failed",
            "final_reply": "Agent 没有生成可用结果。",
        }

    def route_after_planner(
        state: AgentRunState,
    ) -> Literal["executor", "finalizer"]:
        if state.get("status") == "failed":
            LOGGER.info(
                "agent.route from=planner to=finalizer reason=failed run=%s",
                state.get("run_id"),
            )
            return "finalizer"

        decision = state.get("decision")
        if decision is not None and decision.action == "call_tool":
            LOGGER.info(
                "agent.route from=planner to=executor tool=%s run=%s",
                decision.tool_name,
                state.get("run_id"),
            )
            return "executor"

        LOGGER.info(
            "agent.route from=planner to=finalizer action=%s run=%s",
            decision.action if decision is not None else "none",
            state.get("run_id"),
        )
        return "finalizer"

    def route_after_evaluator(
        state: AgentRunState,
    ) -> Literal["planner", "finalizer"]:
        if state.get("status") == "failed":
            LOGGER.info(
                "agent.route from=evaluator to=finalizer reason=failed run=%s",
                state.get("run_id"),
            )
            return "finalizer"

        LOGGER.info(
            "agent.route from=evaluator to=planner run=%s",
            state.get("run_id"),
        )
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
