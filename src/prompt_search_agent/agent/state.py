"""State and structured contracts for the bounded ReAct agent."""

from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field, field_validator, model_validator

from prompt_search_agent.models import WebSource


class AgentDecision(BaseModel):
    action: Literal["call_tool", "ask_user", "finish"]
    tool_name: str | None = Field(default=None, max_length=100)
    tool_input: dict[str, Any] = Field(default_factory=dict)
    question: str | None = Field(default=None, max_length=2000)
    final_response: str | None = Field(default=None, max_length=12000)
    reason_summary: str = Field(min_length=1, max_length=500)

    @field_validator("tool_name", "question", "final_response")
    @classmethod
    def strip_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None

        stripped = value.strip()
        return stripped or None

    @field_validator("reason_summary")
    @classmethod
    def strip_reason_summary(cls, value: str) -> str:
        stripped = value.strip()

        if not stripped:
            raise ValueError("reason_summary must not be blank")

        return stripped

    @model_validator(mode="after")
    def validate_action_fields(self) -> "AgentDecision":
        if self.action == "call_tool" and self.tool_name is None:
            raise ValueError("call_tool requires tool_name")

        if self.action == "ask_user" and self.question is None:
            raise ValueError("ask_user requires question")

        if self.action == "finish" and self.tool_name is not None:
            raise ValueError("finish must not include tool_name")

        return self


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
