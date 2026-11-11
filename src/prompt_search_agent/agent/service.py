"""Service wrapper for the bounded ReAct agent."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field

from prompt_search_agent.agent.planner import create_agent_planner_chain
from prompt_search_agent.agent.state import (
    AgentArtifacts,
    AgentRunResult,
    AgentToolObservation,
)
from prompt_search_agent.agent.tools import (
    build_agent_tool_registry,
)
from prompt_search_agent.agent.workflow import build_agent_workflow
from prompt_search_agent.chains.modify_prompt import (
    create_modify_prompt_chain,
)
from prompt_search_agent.config import Settings
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.models import WebSource
from prompt_search_agent.search.sqlite import SqlitePromptSearchBackend
from prompt_search_agent.skills.image_generation import (
    build_image_generation_skill,
)
from prompt_search_agent.skills.prompt_generation import (
    build_prompt_generation_skill,
)
from prompt_search_agent.storage import (
    ConversationRepository,
    initialize_database,
)
from prompt_search_agent.tools import (
    WebToolNotConfigured,
    build_web_fetch_tool,
    build_web_search_tool,
)


class AgentServiceResult(BaseModel):
    run_id: str
    thread_id: str
    status: Literal[
        "planning",
        "acting",
        "waiting_user",
        "completed",
        "failed",
    ]
    response_type: Literal["prompt", "image", "message", "failed"]
    prompt: str | None = None
    reply: str | None = None
    image_id: str | None = None
    image_url: str | None = None
    sources: list[WebSource] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    decision_summaries: list[str] = Field(default_factory=list)
    steps: int = 0


class AgentService:
    def __init__(
        self,
        graph: Any,
        conversation_repo: ConversationRepository,
        checkpoint_connection: sqlite3.Connection,
        max_steps: int = 8,
    ) -> None:
        self.graph = graph
        self.conversation_repo = conversation_repo
        self.checkpoint_connection = checkpoint_connection
        self.max_steps = max_steps

    def run(
        self,
        user_goal: str,
        thread_id: str,
    ) -> AgentServiceResult:
        run_id, initial_state, config, snapshot = self._start_run(
            user_goal,
            thread_id,
        )
        final_state = self.graph.invoke(initial_state, config=config)
        result = self._build_result(
            run_id,
            thread_id,
            final_state,
        )
        self._persist_result(
            user_goal,
            thread_id,
            snapshot,
            result,
        )
        return result

    def stream(
        self,
        user_goal: str,
        thread_id: str,
    ) -> Iterator[dict[str, Any]]:
        run_id, initial_state, config, snapshot = self._start_run(
            user_goal,
            thread_id,
        )
        yield {
            "event": "stage",
            "phase": "planning",
            "label": "理解目标并规划下一步",
            "steps": 0,
        }

        try:
            for chunk in self.graph.stream(
                initial_state,
                config=config,
                stream_mode="updates",
            ):
                for node, update in self._iter_graph_updates(chunk):
                    if not isinstance(update, dict):
                        continue

                    if node == "planner":
                        decision = update.get("decision")
                        if decision is not None:
                            yield {
                                "event": "step",
                                "phase": (
                                    "waiting_user"
                                    if decision.action == "ask_user"
                                    else "plan"
                                ),
                                "action": decision.action,
                                "tool_name": decision.tool_name,
                                "reason": decision.reason_summary,
                                "steps": update.get(
                                    "step_count",
                                    0,
                                ),
                            }
                    elif node == "executor":
                        observations = update.get("observations") or []
                        if observations:
                            observation = observations[-1]
                            yield {
                                "event": "step",
                                "phase": "tool",
                                "tool_name": observation.tool_name,
                                "ok": observation.ok,
                                "error_code": observation.error_code,
                                "message": observation.message,
                                "elapsed_ms": observation.elapsed_ms,
                            }
                    elif node == "evaluator":
                        yield {
                            "event": "step",
                            "phase": "evaluate",
                            "status": update.get(
                                "status",
                                "planning",
                            ),
                        }
                    elif node == "finalizer":
                        yield {
                            "event": "stage",
                            "phase": "finalize",
                            "label": "整理最终结果",
                        }

            state_snapshot = self.graph.get_state(config)
            final_state = state_snapshot.values
            result = self._build_result(
                run_id,
                thread_id,
                final_state,
            )
            self._persist_result(
                user_goal,
                thread_id,
                snapshot,
                result,
            )
            yield {
                "event": "result",
                "data": result.model_dump(),
            }
        except Exception as exc:  # noqa: BLE001
            yield {
                "event": "error",
                "message": str(exc),
            }

    def _start_run(
        self,
        user_goal: str,
        thread_id: str,
    ):
        self.conversation_repo.ensure_conversation(thread_id)
        snapshot = self.conversation_repo.load_snapshot(
            thread_id,
            recent_message_limit=20,
        )
        run_id = uuid4().hex
        initial_state = {
            "run_id": run_id,
            "thread_id": thread_id,
            "user_goal": user_goal,
            "conversation_context": snapshot.render_context(),
            "current_prompt": snapshot.previous_prompt or "",
            "observations": [],
            "decision_summaries": [],
            "artifacts": AgentArtifacts(),
            "step_count": 0,
            "max_steps": self.max_steps,
            "status": "planning",
            "response_type": "message",
        }
        config = {
            "configurable": {
                "thread_id": run_id,
            }
        }
        return run_id, initial_state, config, snapshot

    @staticmethod
    def _build_result(
        run_id: str,
        thread_id: str,
        final_state: dict[str, Any],
    ) -> AgentServiceResult:
        artifacts = final_state.get("artifacts") or AgentArtifacts()
        result = AgentRunResult.model_validate(
            {
                "run_id": run_id,
                "thread_id": thread_id,
                "status": final_state.get("status", "failed"),
                "response_type": final_state.get(
                    "response_type",
                    "failed",
                ),
                "prompt": artifacts.final_prompt,
                "reply": final_state.get("final_reply"),
                "image_id": artifacts.image_id,
                "image_url": artifacts.image_url,
                "sources": artifacts.sources,
                "tool_names": [
                    item.tool_name
                    for item in final_state.get("observations", [])
                ],
                "decision_summaries": final_state.get(
                    "decision_summaries",
                    [],
                ),
                "steps": final_state.get("step_count", 0),
            }
        )
        return AgentServiceResult(**result.model_dump())

    def _persist_result(
        self,
        user_goal: str,
        thread_id: str,
        snapshot: Any,
        result: AgentServiceResult,
    ) -> None:
        assistant_content = (
            result.prompt
            or result.image_url
            or result.reply
            or "Agent 没有生成结果。"
        )
        self.conversation_repo.append_message(
            thread_id,
            "user",
            user_goal,
        )
        self.conversation_repo.append_message(
            thread_id,
            "assistant",
            assistant_content,
        )

        if result.prompt:
            self.conversation_repo.update_after_turn(
                thread_id,
                snapshot.prompt_spec_json,
                result.prompt,
            )
        else:
            self.conversation_repo.touch_conversation(thread_id)

    @staticmethod
    def _iter_graph_updates(chunk: Any):
        if isinstance(chunk, tuple) and len(chunk) == 2:
            yield chunk[0], chunk[1]
            return

        if isinstance(chunk, dict):
            yield from chunk.items()

    def close(self) -> None:
        self.checkpoint_connection.close()


def _build_agent_graph(
    settings: Settings,
    checkpoint_connection: sqlite3.Connection,
):
    model = create_chat_model(settings)
    search_backend = SqlitePromptSearchBackend(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )

    try:
        web_search_tool = build_web_search_tool(settings)
        web_fetch_tool = build_web_fetch_tool(settings)
    except WebToolNotConfigured:
        web_search_tool = None
        web_fetch_tool = None

    prompt_skill = build_prompt_generation_skill(
        model,
        search_backend,
        web_search_tool=web_search_tool,
        web_fetch_tool=web_fetch_tool,
    )
    modify_chain = create_modify_prompt_chain(model)
    image_skill = build_image_generation_skill(settings)
    conversation_repo = ConversationRepository(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    registry = build_agent_tool_registry(
        prompt_skill,
        modify_chain,
        image_skill,
        conversation_repo,
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    planner_chain = create_agent_planner_chain(model)
    checkpointer = SqliteSaver(checkpoint_connection)
    return build_agent_workflow(
        planner_chain,
        registry,
        max_steps=settings.agent_max_steps,
        checkpointer=checkpointer,
    )


def build_agent_service(settings: Settings) -> AgentService:
    initialize_database(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    settings.agent_checkpoint_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    checkpoint_connection = sqlite3.connect(
        settings.agent_checkpoint_path,
        check_same_thread=False,
    )
    checkpoint_connection.execute("PRAGMA journal_mode = WAL")
    checkpoint_connection.execute(
        f"PRAGMA busy_timeout = {settings.sqlite_busy_timeout_ms}"
    )
    graph = _build_agent_graph(settings, checkpoint_connection)
    return AgentService(
        graph,
        ConversationRepository(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        ),
        checkpoint_connection,
        settings.agent_max_steps,
    )


def summarize_observations(
    observations: list[AgentToolObservation],
) -> list[dict[str, Any]]:
    return [item.model_dump() for item in observations]


def checkpoint_path(settings: Settings) -> Path:
    return settings.agent_checkpoint_path
