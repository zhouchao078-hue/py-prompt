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

from prompt_search_agent.config import PROJECT_ROOT, Settings
from prompt_search_agent.images import (
    ImageGenerationError,
    ImageGenerationResult,
)
from prompt_search_agent.models import WebSource
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
    add_prompt_text,
    get_prompt_index_version,
)

WEB_DIR = Path(__file__).parent / "web"


class PromptServiceLike(Protocol):
    def generate(
        self,
        user_query: str,
        thread_id: str | None = None,
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


def get_prompt_service(request: Request) -> PromptServiceLike:
    return request.app.state.prompt_service


def create_app(
    service_factory: Callable[[], PromptServiceLike] | None = None,
    image_skill_factory: (
        Callable[[], ImageGenerationSkillLike | None] | None
    ) = None,
    image_output_dir: Path | None = None,
    app_settings: Settings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service_factory is None:
            settings = (
                app_settings
                or Settings()  # pyright: ignore[reportCallIssue]
            )
            app.state.settings = settings
            app.state.prompt_service = build_prompt_service(settings)
            app.state.image_skill = build_image_generation_skill(settings)
            app.state.image_output_dir = settings.image_output_dir
        else:
            app.state.settings = app_settings
            app.state.prompt_service = service_factory()
            app.state.image_skill = (
                image_skill_factory()
                if image_skill_factory is not None
                else None
            )
            app.state.image_output_dir = (
                image_output_dir
                or PROJECT_ROOT / "data" / "generated" / "images"
            )

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
        request: Request,
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

        image_result: ImageGenerationResult | None = None
        image_skill: ImageGenerationSkillLike | None = (
            request.app.state.image_skill
        )

        if (
            result.response_type == "prompt"
            and payload.media_type == "image"
            and result.final_prompt
            and image_skill is not None
        ):
            try:
                image_result = image_skill.invoke(
                    result.final_prompt,
                    payload.aspect_ratio,
                    use_cache=result.intent != "regenerate",
                )
            except ImageGenerationError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=str(exc),
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
        else:
            provider_status = "not_configured"
            note = (
                "提示词已生成。图片或视频生成服务尚未配置，"
                "当前页面展示的是可直接提交给生成器的最终提示词。"
            )

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
            raise HTTPException(
                status_code=502,
                detail=str(exc),
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

        return FileResponse(image_path)

    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "prompt_search_agent.webapp:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
