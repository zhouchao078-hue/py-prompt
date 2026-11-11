"""Validated tool registry used by the bounded ReAct agent."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from prompt_search_agent.graph.state import NO_MATCHING_PROMPT
from prompt_search_agent.images import ImageGenerationError
from prompt_search_agent.log_utils import log_value
from prompt_search_agent.models import WebSource
from prompt_search_agent.storage import add_prompt_text

LOGGER = logging.getLogger(__name__)


class AgentToolError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class AgentToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None
    retryable: bool = False
    elapsed_ms: int = 0


@dataclass(frozen=True)
class AgentToolContext:
    thread_id: str
    conversation_context: str
    current_prompt: str


class GeneratePromptInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class RewritePromptInput(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    current_prompt: str | None = Field(default=None, max_length=8000)


class GenerateImageInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    aspect_ratio: Literal["1:1", "3:2", "2:3"] = "2:3"


class HistoryInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


class AddPromptInput(BaseModel):
    prompt_text: str = Field(min_length=1, max_length=4000)
    category: str | None = Field(default=None, max_length=100)


class GeneratePromptOutput(BaseModel):
    final_prompt: str = Field(min_length=1, max_length=12000)
    sources: list[WebSource] = Field(default_factory=list)


class RewritePromptOutput(BaseModel):
    final_prompt: str = Field(min_length=1, max_length=12000)


class GenerateImageOutput(BaseModel):
    image_id: str = Field(min_length=1, max_length=100)
    image_url: str = Field(
        pattern=r"^/api/images/[A-Za-z0-9._-]+$",
    )
    prompt: str = Field(min_length=1, max_length=12000)
    cached: bool


class HistoryMessageOutput(BaseModel):
    id: int = Field(ge=1)
    role: str = Field(min_length=1, max_length=32)
    content: str


class ConversationHistoryOutput(BaseModel):
    messages: list[HistoryMessageOutput] = Field(default_factory=list)


class AddPromptOutput(BaseModel):
    prompt_id: str = Field(min_length=1, max_length=100)
    inserted: bool


@dataclass(frozen=True)
class AgentToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[AgentToolContext, Any], dict[str, Any]]


class AgentToolRegistry:
    def __init__(self, specs: list[AgentToolSpec]) -> None:
        self._specs = {spec.name: spec for spec in specs}

    def descriptions(self) -> str:
        return "\n".join(
            f"- {spec.name}: {spec.description}"
            for spec in self._specs.values()
        )

    def invoke(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        started = time.perf_counter()
        spec = self._specs.get(tool_name)

        if spec is None:
            LOGGER.warning(
                "agent.tool.not_found tool=%s thread=%s input=%s",
                tool_name,
                context.thread_id,
                log_value(tool_input),
            )
            return AgentToolResult(
                ok=False,
                error_code="TOOL_NOT_FOUND",
                message=f"未注册工具: {tool_name}",
            )

        LOGGER.info(
            "agent.tool.start tool=%s thread=%s input=%s",
            tool_name,
            context.thread_id,
            log_value(tool_input),
        )

        try:
            parsed_input = spec.input_model.model_validate(tool_input)
        except ValidationError as exc:
            LOGGER.warning(
                "agent.tool.invalid_input tool=%s thread=%s error=%s",
                tool_name,
                context.thread_id,
                log_value(str(exc)),
            )
            return AgentToolResult(
                ok=False,
                error_code="INVALID_TOOL_INPUT",
                message=str(exc),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            data = spec.handler(context, parsed_input)
        except AgentToolError as exc:
            LOGGER.warning(
                "agent.tool.failed tool=%s thread=%s code=%s retryable=%s "
                "elapsed_ms=%s message=%s",
                tool_name,
                context.thread_id,
                exc.error_code,
                exc.retryable,
                int((time.perf_counter() - started) * 1000),
                log_value(str(exc)),
            )
            return AgentToolResult(
                ok=False,
                error_code=exc.error_code,
                message=str(exc),
                retryable=exc.retryable,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            LOGGER.exception(
                "agent.tool.crashed tool=%s thread=%s error_type=%s",
                tool_name,
                context.thread_id,
                type(exc).__name__,
            )
            return AgentToolResult(
                ok=False,
                error_code="TOOL_EXECUTION_FAILED",
                message=str(exc),
                retryable=True,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            validated_output = spec.output_model.model_validate(data)
        except ValidationError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            LOGGER.error(
                "agent.tool.invalid_output tool=%s thread=%s "
                "elapsed_ms=%s error=%s",
                tool_name,
                context.thread_id,
                elapsed_ms,
                log_value(str(exc)),
            )
            return AgentToolResult(
                ok=False,
                error_code="INVALID_TOOL_OUTPUT",
                message=str(exc),
                retryable=True,
                elapsed_ms=elapsed_ms,
            )

        data = validated_output.model_dump(mode="json")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        LOGGER.info(
            "agent.tool.output tool=%s thread=%s ok=true elapsed_ms=%s data=%s",
            tool_name,
            context.thread_id,
            elapsed_ms,
            log_value(data),
        )
        return AgentToolResult(
            ok=True,
            data=data,
            elapsed_ms=elapsed_ms,
        )


def build_agent_tool_registry(
    prompt_skill: Any,
    modify_chain: Any,
    image_skill: Any | None,
    conversation_repo: Any,
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> AgentToolRegistry:
    def generate_prompt(
        context: AgentToolContext,
        tool_input: GeneratePromptInput,
    ) -> dict[str, Any]:
        result = prompt_skill.invoke(
            tool_input.query,
            context.conversation_context,
        )
        final_prompt = result.get("final_prompt")

        if not final_prompt:
            error = str(result.get("error") or "PROMPT_GENERATION_FAILED")
            raise AgentToolError(
                (
                    NO_MATCHING_PROMPT
                    if error == NO_MATCHING_PROMPT
                    else error
                ),
                "本地和联网检索均未生成可用提示词",
            )

        raw_sources = result.get("web_sources") or []
        sources = [
            (
                source.model_dump()
                if isinstance(source, WebSource)
                else dict(source)
            )
            for source in raw_sources
        ]
        return {
            "final_prompt": str(final_prompt).strip(),
            "sources": sources,
        }

    def rewrite_prompt(
        context: AgentToolContext,
        tool_input: RewritePromptInput,
    ) -> dict[str, Any]:
        prompt = tool_input.current_prompt or context.current_prompt
        final_prompt = modify_chain.invoke(
            {
                "user_query": tool_input.instruction,
                "conversation_context": context.conversation_context,
                "current_prompt": prompt,
            }
        )

        if not final_prompt:
            raise AgentToolError(
                "EMPTY_MODEL_OUTPUT",
                "提示词改写返回为空",
                retryable=True,
            )

        return {"final_prompt": str(final_prompt).strip()}

    def generate_image(
        context: AgentToolContext,
        tool_input: GenerateImageInput,
    ) -> dict[str, Any]:
        if image_skill is None:
            raise AgentToolError(
                "IMAGE_NOT_CONFIGURED",
                "图片生成服务尚未配置",
            )

        try:
            result = image_skill.invoke(
                tool_input.prompt,
                tool_input.aspect_ratio,
                use_cache=True,
            )
        except ImageGenerationError as exc:
            detail = str(exc).casefold()
            LOGGER.warning(
                "agent.tool.generate_image.error thread=%s prompt=%s "
                "aspect_ratio=%s error_type=%s message=%s",
                context.thread_id,
                log_value(tool_input.prompt),
                tool_input.aspect_ratio,
                type(exc).__name__,
                log_value(str(exc)),
            )
            message = (
                "图片服务连接或响应超时，请稍后重试。"
                if "timed out" in detail or "timeout" in detail
                else "图片生成失败，请稍后重试。"
            )
            raise AgentToolError(
                "IMAGE_GENERATION_FAILED",
                message,
                retryable=True,
            ) from exc

        return {
            "image_id": result.image_id,
            "image_url": f"/api/images/{result.file_name}",
            "prompt": result.prompt,
            "cached": result.cached,
        }

    def get_history(
        context: AgentToolContext,
        tool_input: HistoryInput,
    ) -> dict[str, Any]:
        messages = conversation_repo.list_messages(
            context.thread_id,
            tool_input.limit,
        )
        return {
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ]
        }

    def add_prompt(
        context: AgentToolContext,
        tool_input: AddPromptInput,
    ) -> dict[str, Any]:
        added = add_prompt_text(
            db_path,
            tool_input.prompt_text,
            tool_input.category,
            busy_timeout_ms,
        )

        if added is None:
            raise AgentToolError(
                "INVALID_PROMPT",
                "提示词为空或无法分词",
            )

        return {
            "prompt_id": added.prompt_id,
            "inserted": added.inserted,
        }

    return AgentToolRegistry(
        [
            AgentToolSpec(
                name="generate_prompt",
                description=(
                    "根据用户目标检索、联网并组装最终 AIGC 提示词。"
                    "输入 query。"
                ),
                input_model=GeneratePromptInput,
                output_model=GeneratePromptOutput,
                handler=generate_prompt,
            ),
            AgentToolSpec(
                name="rewrite_prompt",
                description=(
                    "根据明确指令修改当前提示词，包括润色、缩短、翻译"
                    "和去版权风险。输入 instruction，可选 current_prompt。"
                ),
                input_model=RewritePromptInput,
                output_model=RewritePromptOutput,
                handler=rewrite_prompt,
            ),
            AgentToolSpec(
                name="generate_image",
                description=(
                    "把最终提示词提交为图片生成任务。"
                    "输入 prompt 和 aspect_ratio。"
                ),
                input_model=GenerateImageInput,
                output_model=GenerateImageOutput,
                handler=generate_image,
            ),
            AgentToolSpec(
                name="get_conversation_history",
                description=(
                    "读取当前对话的历史消息。输入 limit，默认 20。"
                ),
                input_model=HistoryInput,
                output_model=ConversationHistoryOutput,
                handler=get_history,
            ),
            AgentToolSpec(
                name="add_prompt",
                description=(
                    "把用户明确提供的提示词写入本地提示词库。"
                    "输入 prompt_text，可选 category。"
                ),
                input_model=AddPromptInput,
                output_model=AddPromptOutput,
                handler=add_prompt,
            ),
        ]
    )
