"""FastAPI application for the prompt and media workbench."""

import asyncio
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol
from uuid import uuid4

import uvicorn
from anyio import CapacityLimiter, to_thread
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from openai import OpenAIError
from pydantic import BaseModel, Field, SecretStr

from prompt_search_agent.config import (
    PROJECT_ROOT,
    Settings,
)
from prompt_search_agent.cost import USAGE
from prompt_search_agent.guard import (
    DemoGuard,
    install_security,
    sign_token,
    verify_token,
)
from prompt_search_agent.image_quota import ImageQuota
from prompt_search_agent.images import (
    ImageGenerationError,
    ImageGenerationResult,
)
from prompt_search_agent.maintenance import disk_free_bytes, run_janitor
from prompt_search_agent.metrics import (
    METRICS,
    Labels,
    install_metrics,
    metrics_response,
)
from prompt_search_agent.models import WebSource
from prompt_search_agent.resilience import (
    CircuitBreaker,
    GenerationCancelled,
    UpstreamUnavailable,
)
from prompt_search_agent.services.prompt_service import (
    PromptServiceError,
    PromptServiceResult,
    build_prompt_service,
)
from prompt_search_agent.skills.image_generation import (
    build_image_generation_skill,
)
from prompt_search_agent.storage import (
    ConversationRepository,
    SessionRepository,
    add_prompt_text,
    generate_recovery_code,
    get_prompt_index_version,
    import_seed_if_empty,
    initialize_database,
    read_schema_version,
)
from prompt_search_agent.webassets import AssetManifest

LOGGER = logging.getLogger(__name__)

APP_VERSION = os.getenv("APP_VERSION", "0.2.0")

WEB_DIR = Path(__file__).parent / "web"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "generated" / "images"
THREAD_TOKEN_HEADER = "x-thread-token"

@dataclass
class ImageJob:
    """生图任务。内存态，进程退出即失效。"""

    status: str = "pending"
    created_at: float = 0.0
    prompt: str | None = None
    image_id: str | None = None
    image_url: str | None = None
    image_cached: bool = False
    message: str | None = None

    def to_response(self) -> dict[str, object]:
        return {
            "status": self.status,
            "prompt": self.prompt,
            "image_id": self.image_id,
            "image_url": self.image_url,
            "image_cached": self.image_cached,
            "message": self.message,
        }


# 生图任务表：进程内内存态，重启即丢，配合 --workers 1 使用。
IMAGE_JOBS: dict[str, ImageJob] = {}
IMAGE_JOBS_LOCK = threading.Lock()
IMAGE_JOB_TTL_SECONDS = 900.0

# 后台任务必须强引用，否则 asyncio 只持弱引用，任务可能跑到一半被 GC 掉。
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


class PromptServiceLike(Protocol):
    def generate(
        self,
        user_query: str,
        thread_id: str | None = None,
        on_stage: Callable[[str], None] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> PromptServiceResult: ...


class ImageGenerationSkillLike(Protocol):
    def invoke(
        self,
        prompt: str,
        aspect_ratio: str | None = None,
        use_cache: bool = True,
    ) -> ImageGenerationResult: ...


class PromptRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class PromptResponse(BaseModel):
    prompt: str | None
    reply: str | None
    response_type: Literal[
        "prompt",
        "clarification",
        "message",
        "not_found",
    ]
    intent: str
    cached: bool
    generated_from_brief: bool
    thread_id: str
    sources: list[WebSource] = []


class MediaRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    media_type: Literal["image", "video"]
    aspect_ratio: Literal["1:1", "3:2", "2:3"] | None = None
    thread_id: str | None = None
    # 前端默认走异步渲染（/api/images/jobs），避免长请求被网关切断。
    render_image: bool = True


class MediaResponse(BaseModel):
    prompt: str | None
    reply: str | None
    response_type: Literal[
        "prompt",
        "clarification",
        "message",
        "not_found",
    ]
    intent: str
    media_type: Literal["image", "video"]
    aspect_ratio: str | None
    provider_status: Literal[
        "not_configured",
        "not_requested",
        "generated",
    ]
    note: str
    cached: bool
    thread_id: str
    image_id: str | None = None
    image_url: str | None = None
    image_cached: bool = False
    sources: list[WebSource] = []


class AddPromptRequest(BaseModel):
    prompt_text: str = Field(min_length=1, max_length=4000)
    category: str | None = Field(default=None, max_length=100)


class AddPromptResponse(BaseModel):
    prompt_id: str
    prompt_text: str
    inserted: bool


class DirectImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    aspect_ratio: Literal["1:1", "3:2", "2:3"] = "2:3"


class DirectImageResponse(BaseModel):
    prompt: str
    image_id: str
    image_url: str
    image_cached: bool
    provider: str
    model: str
    size: str


class HistoryMessage(BaseModel):
    id: int
    role: str
    content: str


class HistoryResponse(BaseModel):
    thread_id: str
    summary: str
    messages: list[HistoryMessage]


class DeleteHistoryResponse(BaseModel):
    thread_id: str
    deleted: int


class SessionInfo(BaseModel):
    has_recovery_code: bool


class RecoveryCodeResponse(BaseModel):
    code: str


class RestoreRequest(BaseModel):
    code: str = Field(min_length=4, max_length=64)


class ConversationItem(BaseModel):
    thread_id: str
    title: str
    updated_at: str
    message_count: int


class ConversationListResponse(BaseModel):
    tool: str
    items: list[ConversationItem]


class CreateConversationRequest(BaseModel):
    tool: Literal["prompt", "media"] = "prompt"


def _secret_ready(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())


def _session_repo(request: Request) -> SessionRepository | None:
    settings = request.app.state.settings

    if settings is None:
        return None

    return SessionRepository(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )


def _issue_session_cookie(
    request: Request,
    response: Response,
    session_id: str,
) -> None:
    settings = request.app.state.settings

    if settings is None:
        return

    signature = sign_token(session_id, settings.thread_secret_value)
    response.set_cookie(
        settings.session_cookie_name,
        f"{session_id}.{signature}",
        max_age=settings.session_cookie_days * 86400,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _current_session(request: Request) -> str | None:
    """从 cookie 解出当前会话；签名不对或会话记录不存在都返回 None。"""
    settings = request.app.state.settings

    if settings is None:
        return None

    raw = request.cookies.get(settings.session_cookie_name)

    if not raw or "." not in raw:
        return None

    session_id, _, signature = raw.rpartition(".")

    if not verify_token(
        session_id,
        signature,
        settings.thread_secret_value,
    ):
        return None

    repo = _session_repo(request)

    if repo is None or repo.get(session_id) is None:
        return None

    return session_id


def _ensure_session(request: Request, response: Response) -> str | None:
    """没有有效会话就新建一个，并把 cookie 一并下发。"""
    session_id = _current_session(request)

    if session_id is not None:
        return session_id

    repo = _session_repo(request)
    settings = request.app.state.settings

    if repo is None or settings is None:
        return None

    session_id = uuid4().hex

    try:
        repo.create(session_id)
    except sqlite3.OperationalError:
        # 数据库还没建表（首次启动 / 测试直接注入 settings），补一次再重试
        initialize_database(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        )
        repo.create(session_id)

    _issue_session_cookie(request, response, session_id)
    return session_id


def _require_owned_conversation(thread_id: str, request: Request) -> str:
    """读/删历史必须确认这条对话属于当前 cookie 对应的会话。"""
    session_id = _current_session(request)

    if session_id is None:
        raise HTTPException(
            status_code=403,
            detail="会话已失效，请刷新页面重试",
        )

    repo = _session_repo(request)

    if repo is None or not repo.owns_thread(session_id, thread_id):
        raise HTTPException(status_code=403, detail="无权访问该对话")

    return session_id


def _build_prompt_response(result: PromptServiceResult) -> PromptResponse:
    return PromptResponse(
        prompt=result.final_prompt,
        reply=result.reply,
        response_type=result.response_type,
        intent=result.intent,
        cached=result.cached,
        generated_from_brief=result.generated_from_brief,
        thread_id=result.thread_id,
        sources=result.web_sources,
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _run_image_job_with_quota(
    job_id: str,
    skill: ImageGenerationSkillLike,
    prompt: str,
    ratio: str,
    use_cache: bool,
    quota: ImageQuota,
    ip: str,
    stamp: float,
) -> None:
    """线程池里的入口：无论成功失败都要归还并发位。"""
    try:
        _run_image_job(job_id, skill, prompt, ratio, use_cache)
    finally:
        with IMAGE_JOBS_LOCK:
            job = IMAGE_JOBS.get(job_id)
            cached = bool(job.image_cached) if job is not None else False

        # 命中缓存没有成本，把小时配额也退回去。
        quota.release(ip, stamp, refund=cached)


async def _janitor_loop(settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await to_thread.run_sync(run_janitor, settings)
        except Exception:
            LOGGER.warning("巡检失败", exc_info=True)

        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=settings.janitor_interval_seconds,
            )
        except TimeoutError:
            continue


def _ensure_generation_capacity(
    limiter: CapacityLimiter,
    settings: Settings | None,
) -> None:
    """排队过长就快速失败，别让请求堆到网关超时。"""
    limit = settings.max_generation_queue if settings is not None else 16

    if limiter.statistics().tasks_waiting >= limit:
        raise HTTPException(
            status_code=503,
            detail="当前排队较多，请稍后再试。",
        )


async def _generate_with_breaker(
    service: PromptServiceLike,
    message: str,
    thread_id: str | None,
    on_stage: Callable[[str], None] | None,
    limiter: CapacityLimiter,
    breaker: CircuitBreaker,
    settings: Settings | None,
    on_token: Callable[[str], None] | None = None,
) -> PromptServiceResult:
    """所有生成入口共用：排队上限 + 熔断保护 + 并发限流。"""
    _ensure_generation_capacity(limiter, settings)
    breaker.guard()

    started = time.perf_counter()

    def run() -> PromptServiceResult:
        if on_token is None:
            return service.generate(message, thread_id, on_stage)

        return service.generate(message, thread_id, on_stage, on_token)

    try:
        result = await to_thread.run_sync(run, limiter=limiter)
    except GenerationCancelled:
        # 用户主动断开不算上游故障，不能计入熔断。
        raise
    except Exception:
        METRICS.inc("upstream_failures_total", (("stage", "generate"),))
        breaker.record_failure()
        raise
    else:
        breaker.record_success()
        return result
    finally:
        METRICS.observe(
            "generation_seconds",
            time.perf_counter() - started,
        )


def get_prompt_service(request: Request) -> PromptServiceLike:
    service = request.app.state.prompt_service

    if service is None:
        raise HTTPException(
            status_code=503,
            detail="生成服务未就绪，请检查服务端配置。",
        )

    return service


def _bootstrap_service(
    settings: Settings,
) -> PromptServiceLike | None:
    """初始化数据库、按需还原 seed 并构建服务。

    任何一步失败都降级为 ``None``：进程照常启动，接口返回 503，
    而不是让整个 demo 因为一个密钥缺失就直接挂掉。
    """
    try:
        initialize_database(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        )
        imported = import_seed_if_empty(
            settings.prompt_db_path,
            settings.seed_file,
            settings.sqlite_busy_timeout_ms,
        )

        if imported:
            LOGGER.info("已从 seed 还原提示词库: %s 条", imported)
    except Exception:
        LOGGER.exception("数据库初始化失败")

    try:
        return build_prompt_service(settings)
    except Exception:
        LOGGER.exception("提示词服务初始化失败，进入降级模式")
        return None


def _prune_image_jobs(now: float) -> None:
    """清掉超过 TTL 的任务，避免内存无限增长。"""
    stale = [
        job_id
        for job_id, job in IMAGE_JOBS.items()
        if now - job.created_at > IMAGE_JOB_TTL_SECONDS
    ]

    for job_id in stale:
        IMAGE_JOBS.pop(job_id, None)


def _run_image_job(
    job_id: str,
    skill: ImageGenerationSkillLike,
    prompt: str,
    ratio: str,
    use_cache: bool,
) -> None:
    """在线程里跑生图，失败也只更新任务状态，不抛到请求线程。"""
    try:
        result = skill.invoke(prompt, ratio, use_cache=use_cache)
    except Exception:
        # 后台线程不能被单次失败打死，否则任务会永久停在 pending。
        LOGGER.warning("生图任务 %s 失败", job_id, exc_info=True)
        METRICS.inc("image_jobs_total", (("status", "failed"),))

        with IMAGE_JOBS_LOCK:
            job = IMAGE_JOBS.get(job_id)

            if job is not None:
                job.status = "failed"
                job.message = "图片生成失败，请稍后重试。"

        return

    METRICS.inc("image_jobs_total", (("status", "done"),))
    USAGE.record_image()

    with IMAGE_JOBS_LOCK:
        job = IMAGE_JOBS.get(job_id)

        if job is None:
            return

        job.status = "done"
        job.prompt = result.prompt
        job.image_id = result.image_id
        job.image_url = f"/api/images/{result.file_name}"
        job.image_cached = result.cached


def _configure_logging() -> None:
    """uvicorn 只配置自己的 logger，业务日志需要显式接到 root 上。"""
    root = logging.getLogger()

    if root.handlers:
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app(
    service_factory: Callable[[], PromptServiceLike] | None = None,
    image_skill_factory: (
        Callable[[], ImageGenerationSkillLike | None] | None
    ) = None,
    image_output_dir: Path | None = None,
    app_settings: Settings | None = None,
) -> FastAPI:
    resolved_settings = app_settings

    if service_factory is None:
        _configure_logging()

        if resolved_settings is None:
            resolved_settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = resolved_settings
        app.state.settings = settings
        app.state.image_output_dir = image_output_dir or DEFAULT_OUTPUT_DIR
        app.state.generation_limiter = CapacityLimiter(
            settings.max_concurrent_generations if settings is not None else 8
        )
        app.state.generation_breaker = CircuitBreaker(
            settings.upstream_failure_threshold if settings is not None else 5,
            settings.upstream_cooldown_seconds if settings is not None else 30.0,
        )
        app.state.image_quota = ImageQuota(
            settings.image_per_hour if settings is not None else 6,
            settings.image_max_in_flight if settings is not None else 4,
        )
        app.state.image_executor = ThreadPoolExecutor(
            max_workers=settings.image_max_workers if settings is not None else 4,
            thread_name_prefix="image",
        )

        if settings is not None:
            for problem in settings.validate_runtime():
                LOGGER.warning("配置检查: %s", problem)

            app.state.image_output_dir = (
                image_output_dir or settings.image_output_dir
            )

            if settings.is_public_mode:
                LOGGER.info(
                    "公网防护已启用：%s 次/小时/IP，日上限 %s 次，只读库=%s",
                    settings.rate_limit_per_ip_per_hour,
                    settings.daily_request_cap,
                    settings.demo_readonly_library,
                )
            else:
                LOGGER.warning(
                    "未配置 DEMO_ACCESS_CODE，接口未鉴权，仅限本机使用"
                )

        if service_factory is not None:
            app.state.prompt_service = service_factory()
            app.state.image_skill = (
                image_skill_factory()
                if image_skill_factory is not None
                else None
            )
        elif settings is not None:
            app.state.image_skill = build_image_generation_skill(settings)
            app.state.prompt_service = _bootstrap_service(settings)
        else:
            app.state.prompt_service = None
            app.state.image_skill = None

        janitor_stop: asyncio.Event | None = None
        janitor_task: asyncio.Task[None] | None = None

        # 只在自己的生命周期里跑巡检；注入 fake service 的测试不跑。
        if settings is not None and service_factory is None:
            janitor_stop = asyncio.Event()
            janitor_task = asyncio.create_task(
                _janitor_loop(settings, janitor_stop)
            )

        yield

        if janitor_stop is not None and janitor_task is not None:
            janitor_stop.set()

            with suppress(TimeoutError):
                await asyncio.wait_for(janitor_task, timeout=5)

        app.state.image_executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        title="Prompt Atelier",
        version="0.1.0",
        lifespan=lifespan,
    )

    install_security(app, resolved_settings)
    install_metrics(app)

    @app.exception_handler(Exception)
    async def unhandled_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "-")
        LOGGER.exception(
            "未捕获异常 trace_id=%s path=%s",
            trace_id,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "服务暂时不可用，请稍后再试。",
                "trace_id": trace_id,
            },
        )

    assets = AssetManifest.build(WEB_DIR)
    app.state.assets = assets

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(
            assets.index_html(WEB_DIR / "index.html"),
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/session", response_model=SessionInfo)
    def read_session(
        request: Request,
        response: Response,
    ) -> SessionInfo:
        """确保当前浏览器有一个服务端会话，并告知是否已生成恢复码。"""
        session_id = _ensure_session(request, response)
        repo = _session_repo(request)
        has_code = bool(
            session_id and repo and repo.has_recovery_code(session_id)
        )
        return SessionInfo(has_recovery_code=has_code)

    @app.post("/api/session/code", response_model=RecoveryCodeResponse)
    def issue_recovery_code(
        request: Request,
        response: Response,
    ) -> RecoveryCodeResponse:
        """生成（或轮换）恢复码。明文只在这里返回一次。"""
        session_id = _ensure_session(request, response)
        repo = _session_repo(request)

        if session_id is None or repo is None:
            raise HTTPException(status_code=503, detail="会话暂不可用")

        code = generate_recovery_code()
        repo.set_recovery_code(session_id, code)
        return RecoveryCodeResponse(code=code)

    @app.post("/api/session/restore", response_model=SessionInfo)
    def restore_session(
        payload: RestoreRequest,
        request: Request,
        response: Response,
    ) -> SessionInfo:
        repo = _session_repo(request)

        if repo is None:
            raise HTTPException(status_code=503, detail="会话暂不可用")

        session_id = repo.find_by_code(payload.code)

        if session_id is None:
            raise HTTPException(
                status_code=400,
                detail="恢复码无效或已失效",
            )

        repo.touch(session_id)
        _issue_session_cookie(request, response, session_id)
        return SessionInfo(has_recovery_code=True)

    @app.post("/api/session/reset", response_model=SessionInfo)
    def reset_session(
        request: Request,
        response: Response,
    ) -> SessionInfo:
        """换一个全新会话（同一台机器上换人用）。旧会话仍可用恢复码找回。"""
        repo = _session_repo(request)
        settings = request.app.state.settings

        if repo is None or settings is None:
            raise HTTPException(status_code=503, detail="会话暂不可用")

        session_id = uuid4().hex
        repo.create(session_id)
        _issue_session_cookie(request, response, session_id)
        return SessionInfo(has_recovery_code=False)

    @app.get(
        "/api/conversations",
        response_model=ConversationListResponse,
    )
    def list_conversations(
        request: Request,
        response: Response,
        tool: Literal["prompt", "media"] = "prompt",
    ) -> ConversationListResponse:
        session_id = _ensure_session(request, response)
        repo = _session_repo(request)

        if session_id is None or repo is None:
            return ConversationListResponse(tool=tool, items=[])

        return ConversationListResponse(
            tool=tool,
            items=[
                ConversationItem(
                    thread_id=entry.thread_id,
                    title=entry.title or "未命名对话",
                    updated_at=entry.updated_at,
                    message_count=entry.message_count,
                )
                for entry in repo.list_conversations(session_id, tool)
            ],
        )

    @app.post("/api/conversations")
    def create_conversation(
        payload: CreateConversationRequest,
        request: Request,
        response: Response,
    ) -> dict[str, str]:
        session_id = _ensure_session(request, response)
        repo = _session_repo(request)

        if session_id is None or repo is None:
            raise HTTPException(status_code=503, detail="会话暂不可用")

        thread_id = repo.create_conversation(
            session_id,
            payload.tool,
            "新对话",
        )
        return {"thread_id": thread_id}

    @app.get("/api/version")
    def version(request: Request) -> dict[str, object]:
        settings = request.app.state.settings
        schema_version = 0

        if settings is not None:
            try:
                schema_version = read_schema_version(
                    settings.prompt_db_path,
                    settings.sqlite_busy_timeout_ms,
                )
            except Exception:
                LOGGER.warning("读取 schema 版本失败", exc_info=True)
                schema_version = -1

        return {
            "name": "prompt-atelier",
            "version": APP_VERSION,
            "commit": os.getenv("GIT_COMMIT", "unknown"),
            "built_at": os.getenv("BUILD_TIME", "unknown"),
            "schema_version": schema_version,
        }

    @app.get("/api/cost")
    def cost(request: Request) -> dict[str, object]:
        """进程启动以来的用量与估算成本。单价没配时 cost 恒为 0。"""
        return USAGE.snapshot(request.app.state.settings)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> PlainTextResponse:
        limiter: CapacityLimiter = request.app.state.generation_limiter
        stats = limiter.statistics()
        settings = request.app.state.settings
        usage = USAGE.snapshot(settings)

        gauges: dict[str, tuple[float, Labels]] = {
            # 唯一的雪崩前兆：持续大于 0 说明上游变慢或并发打满。
            "generation_waiting": (float(stats.tasks_waiting), ()),
            "generation_in_flight": (float(stats.borrowed_tokens), ()),
            "generation_capacity": (float(stats.total_tokens), ()),
            "image_jobs_tracked": (float(len(IMAGE_JOBS)), ()),
            "llm_input_tokens": (float(usage["input_tokens"]), ()),
            "llm_output_tokens": (float(usage["output_tokens"]), ()),
            "images_generated": (float(usage["images"]), ()),
            "estimated_cost": (float(usage["estimated_cost"]), ()),
        }

        if settings is not None:
            gauges["disk_free_bytes"] = (
                float(disk_free_bytes(settings.data_dir)),
                (),
            )

        return metrics_response(gauges)

    @app.get("/static/{asset_path:path}", include_in_schema=False)
    def static_asset(asset_path: str) -> FileResponse:
        resolved = assets.resolve(asset_path)

        if resolved is None:
            raise HTTPException(status_code=404)

        path, cache_control = resolved
        return FileResponse(path, headers={"Cache-Control": cache_control})

    @app.get("/api/health")
    def health(request: Request) -> dict[str, object]:
        settings = request.app.state.settings

        report: dict[str, object] = {
            "status": "ok",
            "db": "unknown",
            "prompt_count": 0,
            "llm": "unknown",
            "web": "unknown",
            "image": "unknown",
            "storage": "unknown",
            "disk_free_gb": 0.0,
            "readonly_library": True,
        }

        if settings is None:
            report["status"] = "degraded"
            return report

        try:
            index_version = get_prompt_index_version(
                settings.prompt_db_path,
                settings.sqlite_busy_timeout_ms,
            )
            report["db"] = "ok"
            report["prompt_count"] = int(
                index_version.split(":", maxsplit=1)[0]
            )
        except Exception:
            # 健康检查会被监控高频轮询，每次打一份堆栈会直接刷爆日志。
            # 同一类故障每 60 秒最多记一条。
            now = time.monotonic()
            last_logged = getattr(request.app.state, "db_error_logged_at", 0.0)

            if now - last_logged > 60.0:
                request.app.state.db_error_logged_at = now
                LOGGER.warning("健康检查：数据库不可用", exc_info=True)

            report["db"] = "down"

        report["llm"] = "ok" if _secret_ready(settings.deepseek_api_key) else "missing"
        report["web"] = "ok" if _secret_ready(settings.tavily_api_key) else "off"
        report["image"] = (
            "ok"
            if _secret_ready(settings.image_api_key) and settings.image_model
            else "off"
        )
        report["readonly_library"] = settings.demo_readonly_library

        try:
            free_gb = disk_free_bytes(settings.data_dir) / 1e9
            report["disk_free_gb"] = round(free_gb, 1)
            report["storage"] = (
                "low" if free_gb < settings.min_free_disk_gb else "ok"
            )
        except OSError:
            LOGGER.warning("健康检查：读取磁盘信息失败", exc_info=True)
            report["storage"] = "unknown"

        if (
            report["db"] != "ok"
            or report["llm"] != "ok"
            or report["storage"] == "low"
        ):
            report["status"] = "degraded"

        return report

    @app.post("/api/prompt", response_model=PromptResponse)
    async def generate_prompt(
        payload: PromptRequest,
        request: Request,
        response: Response,
        service: Annotated[
            PromptServiceLike,
            Depends(get_prompt_service),
        ],
    ) -> PromptResponse:
        session_id = _ensure_session(request, response)
        repo = _session_repo(request)
        thread_id = payload.thread_id

        if session_id is not None and repo is not None:
            thread_id = repo.resolve_thread(
                session_id,
                "prompt",
                payload.thread_id,
                payload.message[:40],
            )

        try:
            result = await _generate_with_breaker(
                service,
                payload.message,
                thread_id,
                None,
                request.app.state.generation_limiter,
                request.app.state.generation_breaker,
                request.app.state.settings,
            )
        except UpstreamUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="上游服务繁忙，请稍后再试。",
            ) from exc
        except OpenAIError as exc:
            LOGGER.warning(
                "模型调用失败 trace_id=%s err=%s",
                getattr(request.state, "trace_id", "-"),
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="模型服务暂时不可用，请稍后再试。",
            ) from exc
        except PromptServiceError as exc:
            LOGGER.warning(
                "提示词生成失败 trace_id=%s err=%s",
                getattr(request.state, "trace_id", "-"),
                exc,
            )
            raise HTTPException(
                status_code=422,
                detail="这次没能生成，换个说法再试一次。",
            ) from exc

        if session_id is not None and repo is not None:
            repo.touch_conversation(result.thread_id)

        return _build_prompt_response(result)

    @app.post("/api/prompt/stream")
    async def generate_prompt_stream(
        payload: PromptRequest,
        request: Request,
        response: Response,
        service: Annotated[
            PromptServiceLike,
            Depends(get_prompt_service),
        ],
    ) -> StreamingResponse:
        """SSE 版本：边跑边推阶段，避免前端干等 6~10 秒。"""
        session_id = _ensure_session(request, response)
        repo = _session_repo(request)
        thread_id = payload.thread_id

        if session_id is not None and repo is not None:
            thread_id = repo.resolve_thread(
                session_id,
                "prompt",
                payload.thread_id,
                payload.message[:40],
            )

        trace_id = getattr(request.state, "trace_id", "-")
        limiter: CapacityLimiter = request.app.state.generation_limiter
        breaker: CircuitBreaker = request.app.state.generation_breaker
        events: queue.Queue[tuple[str, object]] = queue.Queue()
        cancelled = threading.Event()

        def on_stage(stage: str) -> None:
            # 客户端断开后，在阶段边界中止，省掉后面最贵的上游调用。
            if cancelled.is_set():
                raise GenerationCancelled(stage)

            events.put(("stage", stage))

        def on_token(text: str) -> None:
            if cancelled.is_set():
                raise GenerationCancelled("token")

            events.put(("token", text))

        async def produce() -> None:
            try:
                result = await _generate_with_breaker(
                    service,
                    payload.message,
                    thread_id,
                    on_stage,
                    limiter,
                    breaker,
                    request.app.state.settings,
                    on_token,
                )
                events.put(("result", _build_prompt_response(result)))
            except GenerationCancelled:
                LOGGER.info("客户端断开，中止生成 trace_id=%s", trace_id)
            except UpstreamUnavailable:
                events.put(
                    ("error", {"message": "上游服务繁忙，请稍后再试。"})
                )
            except OpenAIError:
                LOGGER.warning("流式模型调用失败 trace_id=%s", trace_id)
                events.put(
                    ("error", {"message": "模型服务暂时不可用，请稍后再试。"})
                )
            except PromptServiceError as exc:
                LOGGER.warning(
                    "流式生成失败 trace_id=%s err=%s",
                    trace_id,
                    exc,
                )
                events.put(
                    (
                        "error",
                        {"message": "这次没能生成，换个说法再试一次。"},
                    )
                )
            except Exception:
                LOGGER.exception("流式生成异常 trace_id=%s", trace_id)
                events.put(
                    ("error", {"message": "服务暂时不可用，请稍后再试。"})
                )
            finally:
                events.put(("end", None))

        task = asyncio.create_task(produce())
        # 强引用：asyncio 只持弱引用，不引用住的话任务可能跑到一半被 GC。
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

        async def event_stream():
            try:
                yield _sse("open", {"trace_id": trace_id})
                idle = 0.0

                while True:
                    try:
                        kind, value = events.get_nowait()
                    except queue.Empty:
                        if await request.is_disconnected():
                            return
                        # token 流是低延迟场景，短轮询；心跳攒够 5s 才发一次。
                        await asyncio.sleep(0.05)
                        idle += 0.05

                        if idle >= 5.0:
                            idle = 0.0
                            yield ": ping\n\n"

                        continue

                    idle = 0.0

                    if kind == "stage":
                        yield _sse("stage", {"stage": value})
                    elif kind == "token":
                        yield _sse("token", {"text": value})
                    elif kind in {"result", "error"}:
                        payload_data = (
                            value.model_dump()
                            if isinstance(value, PromptResponse)
                            else value
                        )
                        yield _sse(kind, payload_data)

                        if kind == "result":
                            return
                    else:
                        return
            finally:
                cancelled.set()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/api/media", response_model=MediaResponse)
    async def generate_media(
        payload: MediaRequest,
        request: Request,
        response: Response,
        service: Annotated[
            PromptServiceLike,
            Depends(get_prompt_service),
        ],
    ) -> MediaResponse:
        session_id = _ensure_session(request, response)
        repo = _session_repo(request)
        thread_id = payload.thread_id

        if session_id is not None and repo is not None:
            thread_id = repo.resolve_thread(
                session_id,
                "media",
                payload.thread_id,
                payload.message[:40],
            )

        try:
            result = await _generate_with_breaker(
                service,
                payload.message,
                thread_id,
                None,
                request.app.state.generation_limiter,
                request.app.state.generation_breaker,
                request.app.state.settings,
            )
        except UpstreamUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="上游服务繁忙，请稍后再试。",
            ) from exc
        except OpenAIError as exc:
            LOGGER.warning(
                "模型调用失败 trace_id=%s err=%s",
                getattr(request.state, "trace_id", "-"),
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="模型服务暂时不可用，请稍后再试。",
            ) from exc
        except PromptServiceError as exc:
            LOGGER.warning(
                "媒体方案生成失败 trace_id=%s err=%s",
                getattr(request.state, "trace_id", "-"),
                exc,
            )
            raise HTTPException(
                status_code=422,
                detail="这次没能生成，换个说法再试一次。",
            ) from exc

        image_result: ImageGenerationResult | None = None
        image_skill: ImageGenerationSkillLike | None = (
            request.app.state.image_skill
        )

        if (
            result.response_type == "prompt"
            and payload.media_type == "image"
            and payload.render_image
            and result.final_prompt
            and image_skill is not None
        ):
            try:
                image_result = await to_thread.run_sync(
                    image_skill.invoke,
                    result.final_prompt,
                    payload.aspect_ratio,
                    result.intent != "regenerate",
                    limiter=request.app.state.generation_limiter,
                )
            except ImageGenerationError as exc:
                LOGGER.warning(
                    "图片生成失败 trace_id=%s err=%s",
                    getattr(request.state, "trace_id", "-"),
                    exc,
                )
                raise HTTPException(
                    status_code=502,
                    detail="图片生成失败，请稍后重试。",
                ) from exc

        if result.response_type != "prompt":
            provider_status = "not_requested"
            note = result.reply or ""
        elif image_result is not None:
            provider_status = "generated"
            note = (
                "已复用缓存图片。"
                if image_result.cached
                else "图片已生成并保存。"
            )
        elif image_skill is None:
            provider_status = "not_configured"
            note = (
                "提示词已生成。图片或视频生成服务尚未配置，"
                "当前页面展示的是可直接提交给生成器的最终提示词。"
            )
        else:
            provider_status = "not_requested"
            note = "提示词已生成，正在渲染图片。"

        return MediaResponse(
            prompt=(
                image_result.prompt
                if image_result is not None
                else result.final_prompt
            ),
            reply=result.reply,
            response_type=result.response_type,
            intent=result.intent,
            media_type=payload.media_type,
            aspect_ratio=payload.aspect_ratio,
            provider_status=provider_status,
            note=note,
            cached=result.cached,
            thread_id=result.thread_id,
            image_id=(
                image_result.image_id
                if image_result is not None
                else None
            ),
            image_url=(
                f"/api/images/{image_result.file_name}"
                if image_result is not None
                else None
            ),
            image_cached=(
                image_result.cached
                if image_result is not None
                else False
            ),
            sources=result.web_sources,
        )

    @app.post(
        "/api/prompts",
        response_model=AddPromptResponse,
    )
    def add_prompt(
        payload: AddPromptRequest,
        request: Request,
    ) -> AddPromptResponse:
        settings = request.app.state.settings

        if settings is None:
            raise HTTPException(
                status_code=503,
                detail="提示词数据库尚未初始化",
            )

        if settings.demo_readonly_library:
            raise HTTPException(
                status_code=403,
                detail="演示环境已关闭提示词写入。",
            )

        added = add_prompt_text(
            settings.prompt_db_path,
            payload.prompt_text,
            payload.category,
            settings.sqlite_busy_timeout_ms,
        )
        if added is None:
            raise HTTPException(
                status_code=422,
                detail="提示词内容为空或无法分词",
            )

        return AddPromptResponse(
            prompt_id=added.prompt_id,
            prompt_text=added.prompt_text,
            inserted=added.inserted,
        )

    @app.post("/api/images/jobs")
    def create_image_job(
        payload: DirectImageRequest,
        request: Request,
    ) -> dict[str, str]:
        """提交异步生图任务，立即返回 job_id，前端轮询结果。"""
        image_skill: ImageGenerationSkillLike | None = (
            request.app.state.image_skill
        )

        if image_skill is None:
            raise HTTPException(
                status_code=503,
                detail="图片生成服务尚未配置",
            )

        settings = request.app.state.settings

        # 磁盘写满前先停生图——它是最大的磁盘增长源。
        if settings is not None:
            free_gb = disk_free_bytes(settings.data_dir) / 1e9

            if free_gb < settings.min_free_disk_gb:
                LOGGER.warning("磁盘剩余 %.1fGB，暂停生图", free_gb)
                raise HTTPException(
                    status_code=503,
                    detail="存储空间不足，暂时无法生图。",
                )

        ip = DemoGuard.client_ip(request)
        quota: ImageQuota = request.app.state.image_quota
        stamp = quota.reserve(ip)

        if stamp is None:
            raise HTTPException(
                status_code=429,
                detail="图片生成排队已满或小时配额用完，请稍后再试。",
            )

        job_id = uuid4().hex
        now = time.monotonic()

        with IMAGE_JOBS_LOCK:
            _prune_image_jobs(now)
            IMAGE_JOBS[job_id] = ImageJob(created_at=now)

        request.app.state.image_executor.submit(
            _run_image_job_with_quota,
            job_id,
            image_skill,
            payload.prompt,
            payload.aspect_ratio,
            True,
            quota,
            ip,
            stamp,
        )

        return {"job_id": job_id, "status": "pending"}

    @app.get("/api/images/jobs/{job_id}")
    def read_image_job(job_id: str) -> dict[str, object]:
        with IMAGE_JOBS_LOCK:
            job = IMAGE_JOBS.get(job_id)

            if job is None:
                raise HTTPException(
                    status_code=404,
                    detail="任务不存在或已过期",
                )

            return job.to_response()

    @app.post(
        "/api/images/generate",
        response_model=DirectImageResponse,
    )
    def generate_image_directly(
        payload: DirectImageRequest,
        request: Request,
    ) -> DirectImageResponse:
        image_skill: ImageGenerationSkillLike | None = (
            request.app.state.image_skill
        )
        if image_skill is None:
            raise HTTPException(
                status_code=503,
                detail="图片生成服务尚未配置",
            )

        try:
            result = image_skill.invoke(
                payload.prompt,
                payload.aspect_ratio,
                use_cache=True,
            )
        except ImageGenerationError as exc:
            LOGGER.warning(
                "直接生图失败 trace_id=%s err=%s",
                getattr(request.state, "trace_id", "-"),
                exc,
            )
            raise HTTPException(
                status_code=502,
                detail="图片生成失败，请稍后重试。",
            ) from exc

        return DirectImageResponse(
            prompt=result.prompt,
            image_id=result.image_id,
            image_url=f"/api/images/{result.file_name}",
            image_cached=result.cached,
            provider=result.provider,
            model=result.model,
            size=result.size,
        )

    @app.get(
        "/api/history/{thread_id}",
        response_model=HistoryResponse,
    )
    def conversation_history(
        thread_id: str,
        request: Request,
        limit: int = 500,
    ) -> HistoryResponse:
        settings = request.app.state.settings

        if settings is None:
            raise HTTPException(
                status_code=503,
                detail="对话数据库尚未初始化",
            )

        _require_owned_conversation(thread_id, request)

        repository = ConversationRepository(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        )
        messages = repository.list_messages(thread_id, limit)
        return HistoryResponse(
            thread_id=thread_id,
            summary=repository.get_summary(thread_id),
            messages=[
                HistoryMessage(
                    id=message.id,
                    role=message.role,
                    content=message.content,
                )
                for message in messages
            ],
        )

    @app.delete(
        "/api/history/{thread_id}",
        response_model=DeleteHistoryResponse,
    )
    def delete_conversation_history(
        thread_id: str,
        request: Request,
    ) -> DeleteHistoryResponse:
        """删除当前会话下的某条对话（消息、摘要一起删）。

        合规要求：用户有权删除自己的对话数据。只能删自己 cookie 会话下的，
        别人拿不到你的 cookie 就删不掉。
        """
        settings = request.app.state.settings

        if settings is None:
            raise HTTPException(
                status_code=503,
                detail="对话数据库尚未初始化",
            )

        session_id = _require_owned_conversation(thread_id, request)
        repo = _session_repo(request)

        if repo is None:
            raise HTTPException(status_code=503, detail="会话库不可用")

        deleted = repo.delete_conversation(session_id, thread_id)
        METRICS.inc("history_deleted_total")
        LOGGER.info(
            "对话已删除 trace_id=%s deleted_messages=%s",
            getattr(request.state, "trace_id", "-"),
            deleted,
        )

        return DeleteHistoryResponse(thread_id=thread_id, deleted=deleted)

    @app.get(
        "/api/images/{file_name}",
        include_in_schema=False,
    )
    def generated_image(
        file_name: str,
        request: Request,
    ) -> FileResponse:
        if Path(file_name).name != file_name:
            raise HTTPException(status_code=404)

        if Path(file_name).suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
        }:
            raise HTTPException(status_code=404)

        image_path = request.app.state.image_output_dir / file_name
        if not image_path.is_file():
            raise HTTPException(status_code=404)

        return FileResponse(
            image_path,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    return app


app = create_app()


def run() -> None:
    _configure_logging()
    uvicorn.run(
        "prompt_search_agent.webapp:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
