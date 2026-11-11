import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel

from prompt_search_agent.agent.state import (
    AgentArtifacts,
    AgentDecision,
    AgentRunState,
    AgentToolObservation,
)
from prompt_search_agent.agent.tools import (
    AgentToolRegistry,
    AgentToolSpec,
)
from prompt_search_agent.agent.workflow import build_agent_workflow


class EchoInput(BaseModel):
    value: str


class FakePlannerChain:
    def __init__(self, decisions: list[AgentDecision]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input_: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(input_)
        decision = self.decisions.pop(0)
        return {"parsed": decision}


def echo_tool(
    _: Any,
    tool_input: EchoInput,
) -> dict[str, Any]:
    return {"echo": tool_input.value}


def build_echo_registry() -> AgentToolRegistry:
    return AgentToolRegistry(
        [
            AgentToolSpec(
                name="echo",
                description="Return the input value.",
                input_model=EchoInput,
                handler=echo_tool,
            )
        ]
    )


def initial_state() -> AgentRunState:
    return {
        "run_id": "run-1",
        "thread_id": "thread-1",
        "user_goal": "test the agent",
        "conversation_context": "",
        "current_prompt": "",
        "observations": [],
        "decision_summaries": [],
        "artifacts": AgentArtifacts(),
        "step_count": 0,
        "max_steps": 4,
        "status": "planning",
        "response_type": "message",
    }


def test_agent_calls_tool_then_finishes() -> None:
    planner = FakePlannerChain(
        [
            AgentDecision(
                action="call_tool",
                tool_name="echo",
                tool_input={"value": "hello"},
                reason_summary="Need an observation first.",
            ),
            AgentDecision(
                action="finish",
                final_response="done",
                reason_summary="Observation is sufficient.",
            ),
        ]
    )
    workflow = build_agent_workflow(
        planner,
        build_echo_registry(),
        max_steps=4,
    )

    result = workflow.invoke(initial_state())

    assert result["status"] == "completed"
    assert result["response_type"] == "message"
    assert result["final_reply"] == "done"
    assert result["step_count"] == 2
    assert result["decision_summaries"] == [
        "Need an observation first.",
        "Observation is sufficient.",
    ]
    assert [
        observation.tool_name
        for observation in result["observations"]
    ] == ["echo"]
    assert result["observations"][0].data == {"echo": "hello"}


def test_agent_stops_at_step_limit() -> None:
    decisions = [
        AgentDecision(
            action="call_tool",
            tool_name="echo",
            tool_input={"value": str(index)},
            reason_summary="Keep observing.",
        )
        for index in range(3)
    ]
    workflow = build_agent_workflow(
        FakePlannerChain(decisions),
        build_echo_registry(),
        max_steps=2,
    )
    state = initial_state()
    state["max_steps"] = 2

    result = workflow.invoke(state)

    assert result["status"] == "failed"
    assert result["response_type"] == "failed"
    assert result["error"] == "AGENT_STEP_LIMIT"
    assert result["step_count"] == 2


def test_agent_returns_validated_tool_error() -> None:
    planner = FakePlannerChain(
        [
            AgentDecision(
                action="call_tool",
                tool_name="echo",
                tool_input={"wrong": "shape"},
                reason_summary="Try an invalid call.",
            ),
            AgentDecision(
                action="finish",
                final_response="stopped after validation error",
                reason_summary="Tool input was invalid.",
            ),
        ]
    )
    workflow = build_agent_workflow(
        planner,
        build_echo_registry(),
        max_steps=4,
    )

    result = workflow.invoke(initial_state())

    observation = result["observations"][0]
    assert observation.ok is False
    assert observation.error_code == "INVALID_TOOL_INPUT"
    assert result["status"] == "completed"


def test_agent_checkpoint_persists_in_sqlite(tmp_path: Path) -> None:
    connection = sqlite3.connect(
        tmp_path / "checkpoints.sqlite3",
        check_same_thread=False,
    )
    checkpointer = SqliteSaver(connection)
    planner = FakePlannerChain(
        [
            AgentDecision(
                action="finish",
                final_response="checkpointed",
                reason_summary="Nothing else is needed.",
            )
        ]
    )
    workflow = build_agent_workflow(
        planner,
        build_echo_registry(),
        max_steps=2,
        checkpointer=checkpointer,
    )

    result = workflow.invoke(
        initial_state(),
        config={"configurable": {"thread_id": "checkpoint-run"}},
    )
    connection.close()

    assert result["final_reply"] == "checkpointed"
    checkpoint_db = tmp_path / "checkpoints.sqlite3"
    assert checkpoint_db.exists()


def test_observation_model_round_trips() -> None:
    observation = AgentToolObservation(
        tool_name="echo",
        ok=True,
        data={"text": "ok"},
    )

    assert observation.model_dump()["data"] == {"text": "ok"}
