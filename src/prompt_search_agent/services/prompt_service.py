"""Prompt generation service with task-scoped conversation memory."""

import hashlib
import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable
from typing import Any, Literal
from uuid import uuid4

from openai import OpenAIError
from pydantic import BaseModel

from prompt_search_agent.chains.classify_intent import (
    INTENT_SYSTEM_PROMPT,
    create_intent_chain,
)
from prompt_search_agent.chains.compose_prompt import COMPOSE_SYSTEM_PROMPT
from prompt_search_agent.chains.generate_prompt import (
    GENERATE_SYSTEM_PROMPT,
    create_generate_prompt_chain,
)
from prompt_search_agent.chains.modify_prompt import (
    MODIFY_SYSTEM_PROMPT,
    create_modify_prompt_chain,
)
from prompt_search_agent.chains.parse_request import SYSTEM_PROMPT
from prompt_search_agent.chains.rerank_prompts import RERANK_SYSTEM_PROMPT
from prompt_search_agent.chains.summarize_conversation import (
    SUMMARY_SYSTEM_PROMPT,
    create_summary_chain,
)
from prompt_search_agent.config import Settings
from prompt_search_agent.graph.state import NO_MATCHING_PROMPT
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.models import IntentResult, SearchRequest, WebSource
from prompt_search_agent.search.sqlite import SqlitePromptSearchBackend
from prompt_search_agent.search.tokenizer import normalize_text
from prompt_search_agent.skills import (
    ChatSkill,
    ChatSkillError,
    build_chat_skill,
)
from prompt_search_agent.skills.prompt_generation import (
    PromptGenerationSkill,
    build_prompt_generation_skill,
)
from prompt_search_agent.storage import (
    ConversationRepository,
    ConversationSnapshot,
    build_cache_key,
    build_prompt_version,
    get_cached_prompt,
    get_cached_sources_json,
    get_prompt_index_version,
    initialize_database,
    save_cached_prompt,
)
from prompt_search_agent.streaming import invoke_with_tokens
from prompt_search_agent.tools import (
    WebToolNotConfigured,
    build_web_fetch_tool,
    build_web_search_tool,
)

LOGGER = logging.getLogger(__name__)

# 问"怎么改的/为什么这样改/用什么方法"属于提问，不是修改指令。
PROCESS_QUESTION_PATTERN = re.compile(
    r"(怎么|如何|怎样|为什么|为何|用什么|什么方法|哪些步骤|哪一步)"
)

MODIFY_REQUEST_PATTERN = re.compile(
    (
        r"(改写|修改|重写|润色|精简|缩短|翻译|"
        r"改成.{0,12}(?:不违规|无违规|合规)|"
        r"(?:去除|去掉|删除).{0,12}(?:版权|违规)|"
        r"替换.{0,12}(?:角色|人物|名称|地点))"
    ),
    flags=re.IGNORECASE,
)


class PromptServiceResult(BaseModel):
    final_prompt: str | None = None
    reply: str | None = None
    response_type: Literal[
        "prompt",
        "clarification",
        "message",
        "not_found",
    ] = "prompt"
    intent: str = "create"
    cached: bool
    generated_from_brief: bool = False
    thread_id: str = ""
    web_sources: list[WebSource] = []


class PromptServiceError(RuntimeError):
    """Raised when the prompt generation workflow cannot produce output."""


class PromptService:
    def __init__(
        self,
        settings: Settings,
        skill: PromptGenerationSkill,
        fallback_generate_chain: Any | None = None,
        modify_chain: Any | None = None,
        summary_chain: Any | None = None,
        intent_chain: Any | None = None,
        conversation_repo: ConversationRepository | None = None,
        chat_skill: ChatSkill | None = None,
    ) -> None:
        self.settings = settings
        self.skill = skill
        self.fallback_generate_chain = fallback_generate_chain
        self.modify_chain = modify_chain
        self.summary_chain = summary_chain
        self.intent_chain = intent_chain
        self.chat_skill = chat_skill
        self.conversation_repo = conversation_repo or ConversationRepository(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        )
        self.prompt_version = build_prompt_version(
            SYSTEM_PROMPT,
            RERANK_SYSTEM_PROMPT,
            COMPOSE_SYSTEM_PROMPT,
            GENERATE_SYSTEM_PROMPT,
            MODIFY_SYSTEM_PROMPT,
            SUMMARY_SYSTEM_PROMPT,
            INTENT_SYSTEM_PROMPT,
        )

    def generate(
        self,
        user_query: str,
        thread_id: str | None = None,
        on_stage: Callable[[str], None] | None = None,
        on_token: Callable[[str], None] | None = None,
        *,
        use_cache: bool = True,
    ) -> PromptServiceResult:
        notify = on_stage or (lambda _stage: None)
        thread_id = thread_id or str(uuid4())
        deadline = time.monotonic() + self.settings.generation_deadline_seconds

        def checkpoint() -> None:
            """阶段边界检查总预算；超时就不再发起新的上游调用。"""
            if time.monotonic() > deadline:
                raise PromptServiceError("生成超时，请稍后重试")

        snapshot = self._load_conversation(thread_id)
        conversation_context = snapshot.render_context()
        checkpoint()
        notify("intent")
        intent_result = self._classify_intent(
            user_query,
            conversation_context,
        )
        intent_result = self._apply_intent_guard(
            user_query,
            intent_result,
        )

        if (
            intent_result is not None
            and intent_result.intent == "vague_feedback"
        ):
            reply = self._build_clarification_reply(intent_result)
            self._save_clarification(thread_id, user_query, reply)
            return PromptServiceResult(
                reply=reply,
                response_type="clarification",
                intent=intent_result.intent,
                cached=False,
                thread_id=thread_id,
            )

        if intent_result is not None and intent_result.intent in {
            "chat",
            "question",
            "cancel",
            "other",
        }:
            if self.chat_skill is None:
                reply = self._build_conversation_reply(intent_result)
            else:
                try:
                    reply = self.chat_skill.invoke(
                        user_query=user_query,
                        intent=intent_result.intent,
                        conversation_context=conversation_context,
                        current_prompt=snapshot.previous_prompt or "",
                    )
                except (ChatSkillError, OpenAIError) as exc:
                    LOGGER.warning("Chat reply failed: %s", exc)
                    reply = self._build_conversation_reply(intent_result)

            self._save_clarification(thread_id, user_query, reply)
            return PromptServiceResult(
                reply=reply,
                response_type="message",
                intent=intent_result.intent,
                cached=False,
                thread_id=thread_id,
            )

        if (
            intent_result is not None
            and intent_result.intent == "regenerate"
        ):
            final_prompt = self._regenerate_from_context(
                user_query,
                conversation_context,
                on_token,
            )
            self._save_turn(
                thread_id,
                user_query,
                final_prompt,
                prompt_spec_json=snapshot.prompt_spec_json,
            )
            return PromptServiceResult(
                final_prompt=final_prompt,
                response_type="prompt",
                intent="regenerate",
                cached=False,
                generated_from_brief=True,
                thread_id=thread_id,
            )

        if (
            intent_result is not None
            and intent_result.intent == "modify"
        ):
            final_prompt = self._modify_from_context(
                user_query,
                conversation_context,
                snapshot.previous_prompt or "",
                on_token,
            )
            self._save_turn(
                thread_id,
                user_query,
                final_prompt,
                prompt_spec_json=snapshot.prompt_spec_json,
            )
            return PromptServiceResult(
                final_prompt=final_prompt,
                response_type="prompt",
                intent="modify",
                cached=False,
                generated_from_brief=False,
                thread_id=thread_id,
            )

        checkpoint()
        notify("retrieval")
        context_key = hashlib.sha256(
            (
                conversation_context
                + "\0"
                + (intent_result.intent if intent_result else "create")
            ).encode("utf-8")
        ).hexdigest()
        normalized_query = normalize_text(user_query).casefold()
        index_version = get_prompt_index_version(
            self.settings.prompt_db_path,
            self.settings.sqlite_busy_timeout_ms,
        )
        cache_key = build_cache_key(
            normalized_query=normalized_query,
            model_name=self.settings.deepseek_model,
            prompt_version=self.prompt_version,
            index_version=index_version,
            context_key=context_key,
        )
        cached_prompt = (
            get_cached_prompt(
                self.settings.prompt_db_path,
                cache_key,
                self.settings.sqlite_busy_timeout_ms,
            )
            if use_cache
            else None
        )

        if cached_prompt is not None:
            sources_json = get_cached_sources_json(
                self.settings.prompt_db_path,
                cache_key,
                self.settings.sqlite_busy_timeout_ms,
            )
            web_sources = (
                [
                    WebSource.model_validate(source)
                    for source in json.loads(sources_json)
                ]
                if sources_json
                else []
            )
            self._save_turn(
                thread_id,
                user_query,
                cached_prompt,
                prompt_spec_json=snapshot.prompt_spec_json,
            )
            return PromptServiceResult(
                final_prompt=cached_prompt,
                cached=True,
                generated_from_brief=False,
                thread_id=thread_id,
                intent=intent_result.intent if intent_result else "create",
                web_sources=web_sources,
            )

        result: dict[str, Any] = {}
        generated_from_brief = False

        try:
            result = self.skill.invoke(
                user_query,
                conversation_context,
                on_token,
            )
            final_prompt = result.get("final_prompt")

            if not final_prompt:
                if result.get("error") == NO_MATCHING_PROMPT:
                    reply = (
                        "未检索到匹配提示词。"
                        "你可以点击“添加提示词”将它加入本地提示词库。"
                    )
                    self._save_clarification(
                        thread_id,
                        user_query,
                        reply,
                    )
                    return PromptServiceResult(
                        reply=reply,
                        response_type="not_found",
                        intent=(
                            intent_result.intent
                            if intent_result is not None
                            else "create"
                        ),
                        cached=False,
                        thread_id=thread_id,
                    )

                raise PromptServiceError(
                    str(result.get("error", "Prompt generation failed"))
                )
        except PromptServiceError:
            if self.fallback_generate_chain is None:
                raise

            fallback_request = SearchRequest(keywords=[user_query])
            final_prompt = invoke_with_tokens(
                self.fallback_generate_chain,
                {
                    "user_query": user_query,
                    "conversation_context": conversation_context,
                    "request_json": fallback_request.model_dump_json(),
                    "variation_hint": "",
                },
                on_token,
            )

            if not final_prompt:
                raise PromptServiceError(
                    "Fallback prompt generation failed"
                )

            result = {
                "request": fallback_request,
                "candidates": [],
            }
            generated_from_brief = True

        request = result.get("request")
        candidates = (
            result.get("reranked_candidates")
            or result.get("candidates")
            or []
        )
        prompt_spec_json = (
            request.model_dump_json()
            if request is not None
            else snapshot.prompt_spec_json
        )
        candidate_ids_json = json.dumps(
            [candidate.prompt_id for candidate in candidates],
            ensure_ascii=False,
        )
        web_sources = result.get("web_sources") or []
        sources_json = (
            json.dumps(
                [
                    source.model_dump()
                    for source in web_sources
                ],
                ensure_ascii=False,
            )
            if web_sources
            else None
        )

        try:
            save_cached_prompt(
                db_path=self.settings.prompt_db_path,
                cache_key=cache_key,
                normalized_query=normalized_query,
                model_name=self.settings.deepseek_model,
                prompt_version=self.prompt_version,
                index_version=index_version,
                final_prompt=final_prompt,
                request_json=prompt_spec_json,
                candidate_ids_json=candidate_ids_json,
                sources_json=sources_json,
                busy_timeout_ms=self.settings.sqlite_busy_timeout_ms,
            )
        except sqlite3.DatabaseError:
            pass

        self._save_turn(
            thread_id,
            user_query,
            final_prompt,
            prompt_spec_json=prompt_spec_json,
        )

        return PromptServiceResult(
            final_prompt=final_prompt,
            cached=False,
            generated_from_brief=(
                generated_from_brief
                or bool(result.get("generated_from_brief", False))
            ),
            thread_id=thread_id,
            intent=intent_result.intent if intent_result else "create",
            web_sources=web_sources,
        )

    def _classify_intent(
        self,
        user_query: str,
        conversation_context: str,
    ) -> IntentResult | None:
        if self.intent_chain is None:
            return None

        for _ in range(2):
            try:
                raw_result = self.intent_chain.invoke(
                    {
                        "user_query": user_query,
                        "conversation_context": conversation_context,
                    }
                )
            except (
                OpenAIError,
                RuntimeError,
                ValueError,
            ) as exc:
                LOGGER.warning("Intent classification failed: %s", exc)
                return None

            parsed = (
                raw_result.get("parsed")
                if isinstance(raw_result, dict)
                else None
            )

            if parsed is not None:
                return parsed

        return None

    @staticmethod
    def _apply_intent_guard(
        user_query: str,
        intent_result: IntentResult | None,
    ) -> IntentResult | None:
        if intent_result is None:
            return None

        if intent_result.intent not in {
            "create",
            "question",
            "other",
        }:
            return intent_result

        if re.search(
            r"(不要|别|取消).{0,8}(修改|改写|润色)",
            user_query,
            flags=re.IGNORECASE,
        ):
            return intent_result

        # 在问"怎么改的、为什么改、用什么方法"时，句子里也会出现
        # "修改"，但那是在问流程，不能当成修改指令。
        if PROCESS_QUESTION_PATTERN.search(user_query):
            return intent_result

        if not MODIFY_REQUEST_PATTERN.search(user_query):
            return intent_result

        return intent_result.model_copy(
            update={
                "intent": "modify",
                "reason": "用户明确要求改写现有提示词",
            }
        )

    @staticmethod
    def _build_clarification_reply(
        intent_result: IntentResult,
    ) -> str:
        if intent_result.clarification_question:
            return intent_result.clarification_question

        if intent_result.intent == "vague_feedback":
            return (
                "你最想调整哪一部分：主体、颜色、场景、风格、"
                "镜头还是画幅？"
            )

        return "请直接描述你想生成或调整的画面。"

    @staticmethod
    def _build_conversation_reply(
        intent_result: IntentResult,
    ) -> str:
        if intent_result.assistant_reply:
            return intent_result.assistant_reply

        if intent_result.intent == "cancel":
            return "好，这一版先保留，不改动。"

        if intent_result.intent == "question":
            return "你可以直接问当前提示词的主体、风格、镜头或画幅。"

        return "我在。可以直接告诉我想生成或调整什么。"

    def _regenerate_from_context(
        self,
        user_query: str,
        conversation_context: str,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        if self.fallback_generate_chain is None:
            raise PromptServiceError("Regeneration chain is not configured")

        request_json = SearchRequest().model_dump_json()
        final_prompt = invoke_with_tokens(
            self.fallback_generate_chain,
            {
                "user_query": user_query,
                "conversation_context": conversation_context,
                "request_json": request_json,
                "variation_hint": (
                    "这是重新生成请求。保持核心主体和明确约束不变，"
                    "使用与上一版不同的构图、细节或视觉组织。"
                ),
            },
            on_token,
        )

        if not final_prompt:
            raise PromptServiceError("Regeneration produced an empty prompt")

        return final_prompt.strip()

    def _modify_from_context(
        self,
        user_query: str,
        conversation_context: str,
        current_prompt: str,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        if self.modify_chain is None:
            raise PromptServiceError("Modify chain is not configured")

        final_prompt = invoke_with_tokens(
            self.modify_chain,
            {
                "user_query": user_query,
                "conversation_context": conversation_context,
                "current_prompt": current_prompt,
            },
            on_token,
        )

        if not final_prompt:
            raise PromptServiceError("Modify chain produced an empty prompt")

        return final_prompt.strip()

    def _load_conversation(self, thread_id: str) -> ConversationSnapshot:
        """会话记忆是增益功能，数据库抖一下不该让整个请求失败。"""
        try:
            self.conversation_repo.ensure_conversation(thread_id)
            self._compress_if_needed(thread_id)
            return self.conversation_repo.load_snapshot(
                thread_id,
                self.settings.conversation_recent_messages,
            )
        except sqlite3.DatabaseError:
            LOGGER.warning("会话记忆不可用，按新会话处理", exc_info=True)
            return ConversationSnapshot(
                thread_id=thread_id,
                summary="",
                prompt_spec_json=None,
                previous_prompt=None,
                recent_messages=[],
            )

    def _save_clarification(
        self,
        thread_id: str,
        user_query: str,
        reply: str,
    ) -> None:
        try:
            self.conversation_repo.append_message(
                thread_id,
                "user",
                user_query,
            )
            self.conversation_repo.append_message(
                thread_id,
                "assistant",
                reply,
            )
            self.conversation_repo.touch_conversation(thread_id)
        except sqlite3.DatabaseError:
            LOGGER.warning("会话记录写入失败，回复照常返回", exc_info=True)
            return

        self._compress_if_needed(thread_id)

    def _save_turn(
        self,
        thread_id: str,
        user_query: str,
        final_prompt: str,
        prompt_spec_json: str | None,
    ) -> None:
        """写历史失败不能让已经算完（且已经付费）的提示词丢掉。"""
        try:
            self.conversation_repo.append_message(
                thread_id,
                "user",
                user_query,
            )
            self.conversation_repo.append_message(
                thread_id,
                "assistant",
                final_prompt,
            )
            self.conversation_repo.update_after_turn(
                thread_id,
                prompt_spec_json,
                final_prompt,
            )
        except sqlite3.DatabaseError:
            LOGGER.warning("会话记录写入失败，结果照常返回", exc_info=True)
            return

        self._compress_if_needed(thread_id)

    def _compress_if_needed(self, thread_id: str) -> None:
        if self.summary_chain is None:
            return

        try:
            batch = self.conversation_repo.get_compression_batch(
                thread_id,
                self.settings.conversation_recent_messages,
                self.settings.conversation_compress_after_messages,
            )
        except sqlite3.DatabaseError:
            LOGGER.warning("读取压缩批次失败，跳过压缩", exc_info=True)
            return

        if batch is None:
            return

        messages_text = "\n".join(
            f"{message.role}: {message.content[:700]}"
            for message in batch.messages
        )

        try:
            summary = self.summary_chain.invoke(
                {
                    "existing_summary": batch.existing_summary or "无",
                    "messages_text": messages_text,
                }
            ).strip()
        except (
            OpenAIError,
            RuntimeError,
            ValueError,
            sqlite3.DatabaseError,
        ) as exc:
            LOGGER.warning("Conversation summary failed: %s", exc)
            return

        if not summary:
            return

        self.conversation_repo.update_summary(
            thread_id,
            summary[: self.settings.conversation_summary_max_chars],
            batch.cutoff_message_id,
        )


def build_prompt_service(settings: Settings) -> PromptService:
    """Create the production prompt service."""
    initialize_database(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    model = create_chat_model(settings)
    chat_skill = build_chat_skill(model)
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

    skill = build_prompt_generation_skill(
        model,
        search_backend,
        web_search_tool=web_search_tool,
        web_fetch_tool=web_fetch_tool,
        web_mode=settings.web_research_mode,
    )
    return PromptService(
        settings,
        skill,
        fallback_generate_chain=create_generate_prompt_chain(model),
        modify_chain=create_modify_prompt_chain(model),
        summary_chain=create_summary_chain(model),
        intent_chain=create_intent_chain(model),
        chat_skill=chat_skill,
    )
