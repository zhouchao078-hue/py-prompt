"""State and structured contracts for the bounded ReAct agent."""

from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field

from prompt_search_agent.models import WebSource


class AgentDecision(BaseModel):
    action: Literal["call_tool", "ask_user", "finish"]
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    question: str | None = None
    final_response: str | None = None
    reason_summary: str


class AgentToolObservation(BaseModel):
    tool_name: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None
    retryable: bool = False
    elapsed_ms: int = 0


class AgentArtifacts(BaseModel):
    final_prompt: str | None = None
    image_id: str | None = None
    image_url: str | None = None
    sources: list[WebSource] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    reply: str | None = None


class AgentRunState(TypedDict):
    run_id: str
    thread_id: str
    user_goal: str
    conversation_context: str
    current_prompt: str
    observations: list[AgentToolObservation]
    artifacts: AgentArtifacts
    step_count: int
    max_steps: int
    status: Literal[
        "planning",
        "acting",
        "waiting_user",
        "completed",
        "failed",
    ]
    response_type: Literal["prompt", "image", "message", "failed"]
    decision: NotRequired[AgentDecision]
    decision_summaries: list[str]
    final_reply: NotRequired[str]
    error: NotRequired[str]


class AgentRunResult(BaseModel):
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
