"""FastAPI application for the prompt and media workbench."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal, Protocol

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from prompt_search_agent.config import Settings
from prompt_search_agent.models import WebSource
from prompt_search_agent.services.prompt_service import (
    PromptServiceError,
    PromptServiceResult,
    build_prompt_service,
)
from prompt_search_agent.storage import get_prompt_index_version

WEB_DIR = Path(__file__).parent / "web"


class PromptServiceLike(Protocol):
    def generate(
        self,
        user_query: str,
        thread_id: str | None = None,
    ) -> PromptServiceResult: ...


class PromptRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class PromptResponse(BaseModel):
    prompt: str | None
    reply: str | None
    response_type: Literal["prompt", "clarification"]
    intent: str
    cached: bool
    generated_from_brief: bool
    thread_id: str
    sources: list[WebSource] = []


class MediaRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    media_type: Literal["image", "video"]
    aspect_ratio: str | None = None
    thread_id: str | None = None


class MediaResponse(BaseModel):
    prompt: str | None
    reply: str | None
    response_type: Literal["prompt", "clarification"]
    intent: str
    media_type: Literal["image", "video"]
    aspect_ratio: str | None
    provider_status: Literal["not_configured", "not_requested"]
    note: str
    cached: bool
    thread_id: str
    sources: list[WebSource] = []


def get_prompt_service(request: Request) -> PromptServiceLike:
    return request.app.state.prompt_service


def create_app(
    service_factory: Callable[[], PromptServiceLike] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service_factory is None:
            settings = Settings()  # pyright: ignore[reportCallIssue]
            app.state.settings = settings
            app.state.prompt_service = build_prompt_service(settings)
        else:
            app.state.settings = None
            app.state.prompt_service = service_factory()

        yield

    app = FastAPI(
        title="Prompt Atelier",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.mount(
        "/static",
        StaticFiles(directory=WEB_DIR),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/health")
    def health(request: Request) -> dict[str, str]:
        settings = request.app.state.settings

        if settings is None:
            return {
                "status": "ok",
                "prompt_count": "0",
            }

        index_version = get_prompt_index_version(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        )
        prompt_count = index_version.split(":", maxsplit=1)[0]
        return {
            "status": "ok",
            "prompt_count": prompt_count,
        }

    @app.post("/api/prompt", response_model=PromptResponse)
    def generate_prompt(
        payload: PromptRequest,
        service: Annotated[
            PromptServiceLike,
            Depends(get_prompt_service),
        ],
    ) -> PromptResponse:
        try:
            result = service.generate(
                payload.message,
                payload.thread_id,
            )
        except PromptServiceError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

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

    @app.post("/api/media", response_model=MediaResponse)
    def generate_media(
        payload: MediaRequest,
        service: Annotated[
            PromptServiceLike,
            Depends(get_prompt_service),
        ],
    ) -> MediaResponse:
        try:
            result = service.generate(
                payload.message,
                payload.thread_id,
            )
        except PromptServiceError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

        return MediaResponse(
            prompt=result.final_prompt,
            reply=result.reply,
            response_type=result.response_type,
            intent=result.intent,
            media_type=payload.media_type,
            aspect_ratio=payload.aspect_ratio,
            provider_status=(
                "not_configured"
                if result.response_type == "prompt"
                else "not_requested"
            ),
            note=(
                result.reply or ""
                if result.response_type == "clarification"
                else (
                    "提示词已生成。图片或视频生成服务尚未配置，"
                    "当前页面展示的是可直接提交给生成器的最终提示词。"
                )
            ),
            cached=result.cached,
            thread_id=result.thread_id,
            sources=result.web_sources,
        )

    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "prompt_search_agent.webapp:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
