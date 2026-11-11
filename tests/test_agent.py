import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, ValidationError

from prompt_search_agent.agent.service import (
    AgentService,
    AgentServiceResult,
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
    AgentToolSpec,
    build_agent_tool_registry,
)
from prompt_search_agent.agent.workflow import build_agent_workflow
from prompt_search_agent.images import ImageGenerationError


class EchoInput(BaseModel):
    value: str


class EchoOutput(BaseModel):
    echo: str


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
                output_model=EchoOutput,
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


def test_agent_calls_tool_then_finishes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
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
    assert "agent.node.enter node=planner" in caplog.text
    assert "agent.node.output node=planner" in caplog.text
    assert "agent.tool.start tool=echo" in caplog.text
    assert "agent.tool.output tool=echo" in caplog.text
    assert "agent.node.enter node=executor" in caplog.text
    assert "agent.node.enter node=evaluator" in caplog.text
    assert "agent.node.enter node=finalizer" in caplog.text
    assert "agent.finalizer.output" in caplog.text
    assert "agent.route" in caplog.text


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


def test_agent_rejects_inconsistent_decision() -> None:
    with pytest.raises(ValidationError):
        AgentDecision(
            action="call_tool",
            reason_summary="Tool name is missing.",
        )

    with pytest.raises(ValidationError):
        AgentDecision(
            action="ask_user",
            reason_summary="Question is missing.",
        )

    with pytest.raises(ValidationError):
        AgentDecision(
            action="finish",
            tool_name="echo",
            reason_summary="Finish cannot call a tool.",
        )


def test_agent_retries_invalid_planner_contract() -> None:
    class InvalidThenValidPlanner:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, _input: dict[str, Any]) -> dict[str, Any]:
            self.calls += 1

            if self.calls == 1:
                return {
                    "parsed": {
                        "action": "call_tool",
                        "reason_summary": "Missing tool.",
                    }
                }

            return {
                "parsed": AgentDecision(
                    action="finish",
                    final_response="recovered",
                    reason_summary="Valid fallback decision.",
                )
            }

    planner = InvalidThenValidPlanner()
    workflow = build_agent_workflow(
        planner,
        build_echo_registry(),
        max_steps=2,
    )

    result = workflow.invoke(initial_state())

    assert result["final_reply"] == "recovered"
    assert planner.calls == 2


def test_agent_rejects_invalid_tool_output() -> None:
    def broken_tool(_: Any, __: EchoInput) -> dict[str, Any]:
        return {"wrong": "shape"}

    registry = AgentToolRegistry(
        [
            AgentToolSpec(
                name="broken",
                description="Return an invalid output contract.",
                input_model=EchoInput,
                output_model=EchoOutput,
                handler=broken_tool,
            )
        ]
    )

    result = registry.invoke(
        "broken",
        {"value": "hello"},
        AgentToolContext(
            thread_id="thread-1",
            conversation_context="",
            current_prompt="",
        ),
    )

    assert result.ok is False
    assert result.error_code == "INVALID_TOOL_OUTPUT"
    assert result.retryable is True
    assert "echo" in (result.message or "").lower()


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


def test_agent_persists_structured_image_result_metadata() -> None:
    class FakeConversationRepo:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str, str, dict[str, Any]]] = []

        def append_message(
            self,
            thread_id: str,
            role: str,
            content: str,
            metadata: dict[str, Any] | None = None,
        ) -> int:
            self.messages.append(
                (thread_id, role, content, metadata or {})
            )
            return len(self.messages)

        def update_after_turn(self, *_args: Any) -> None:
            return None

        def touch_conversation(self, *_args: Any) -> None:
            return None

    repo = FakeConversationRepo()
    service = AgentService(
        graph=None,
        conversation_repo=repo,  # type: ignore[arg-type]
        checkpoint_connection=None,  # type: ignore[arg-type]
    )
    result = AgentServiceResult(
        run_id="run-image",
        thread_id="thread-image",
        status="completed",
        response_type="image",
        prompt="a snowy cat",
        reply="图片已生成",
        image_id="image-1",
        image_url="/api/images/image-1.png",
    )

    service._persist_result(
        "draw a cat",
        "thread-image",
        SimpleNamespace(prompt_spec_json=None),
        result,
    )

    assistant = repo.messages[-1]
    assert assistant[1] == "assistant"
    assert assistant[3]["response_type"] == "image"
    assert assistant[3]["image_id"] == "image-1"
    assert assistant[3]["image_url"] == "/api/images/image-1.png"


def test_generate_image_timeout_returns_readable_tool_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    class FailingImageSkill:
        def invoke(self, *_args: Any, **_kwargs: Any) -> Any:
            raise ImageGenerationError(
                "Image API request failed: Request timed out."
            )

    registry = build_agent_tool_registry(
        prompt_skill=None,
        modify_chain=None,
        image_skill=FailingImageSkill(),
        conversation_repo=None,
        db_path=Path("unused.sqlite3"),
    )

    result = registry.invoke(
        "generate_image",
        {"prompt": "a snowy cat", "aspect_ratio": "2:3"},
        AgentToolContext(
            thread_id="thread-1",
            conversation_context="",
            current_prompt="",
        ),
    )

    assert result.ok is False
    assert result.error_code == "IMAGE_GENERATION_FAILED"
    assert result.retryable is True
    assert result.message == "图片服务连接或响应超时，请稍后重试。"
    assert "agent.tool.generate_image.error" in caplog.text
    assert "agent.tool.failed tool=generate_image" in caplog.text
