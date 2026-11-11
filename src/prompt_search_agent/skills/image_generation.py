"""Image generation skill."""

import hashlib
import logging
import re
from collections.abc import Mapping
from pathlib import Path

from prompt_search_agent.config import Settings
from prompt_search_agent.images import (
    ImageEditRequest,
    ImageGenerationError,
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageProvider,
    OpenAIImageProvider,
)
from prompt_search_agent.log_utils import log_value
from prompt_search_agent.storage import (
    build_generated_image_cache_key,
    delete_generated_image_record,
    get_cached_generated_image,
    initialize_database,
    purge_expired_generated_images,
    save_generated_image,
)

ASPECT_PARAMETER_PATTERN = re.compile(
    r"\s*--ar\s+\d+\s*:\s*\d+",
    flags=re.IGNORECASE,
)
LOGGER = logging.getLogger(__name__)


def normalize_image_prompt(prompt: str) -> str:
    normalized = ASPECT_PARAMETER_PATTERN.sub("", prompt).strip()

    if not normalized:
        raise ImageGenerationError("Image prompt is empty")

    return normalized


class ImageGenerationSkill:
    def __init__(
        self,
        provider: ImageProvider,
        size_by_aspect_ratio: Mapping[str, str],
        db_path: Path | None = None,
        cache_scope: str = "",
        retention_days: int = 7,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.provider = provider
        self.size_by_aspect_ratio = dict(size_by_aspect_ratio)
        self.db_path = db_path
        self.cache_scope = cache_scope
        self.retention_days = retention_days
        self.busy_timeout_ms = busy_timeout_ms

    def invoke(
        self,
        prompt: str,
        aspect_ratio: str | None = None,
        use_cache: bool = True,
    ) -> ImageGenerationResult:
        LOGGER.info(
            "image.skill.generate.start aspect_ratio=%s use_cache=%s "
            "prompt=%s",
            aspect_ratio,
            use_cache,
            log_value(prompt),
        )
        normalized_prompt = normalize_image_prompt(prompt)
        normalized_ratio = aspect_ratio or "1:1"
        size = self.size_by_aspect_ratio.get(
            normalized_ratio,
            self.size_by_aspect_ratio["1:1"],
        )
        cache_key = build_generated_image_cache_key(
            normalized_prompt,
            self.cache_scope,
            "default",
            size,
        )

        if self.db_path is not None and use_cache:
            cached = get_cached_generated_image(
                self.db_path,
                cache_key,
                self.busy_timeout_ms,
            )
            if cached is not None:
                if cached.file_path.is_file():
                    LOGGER.info(
                        "image.skill.generate.cache_hit image_id=%s file=%s",
                        cached.image_id,
                        cached.file_path,
                    )
                    return cached

                LOGGER.warning(
                    "image.skill.generate.stale_cache image_id=%s file=%s",
                    cached.image_id,
                    cached.file_path,
                )
                delete_generated_image_record(
                    self.db_path,
                    cache_key,
                    self.busy_timeout_ms,
                )

        LOGGER.info(
            "image.skill.generate.provider_call size=%s cache_key=%s",
            size,
            cache_key,
        )
        result = self.provider.generate(
            ImageGenerationRequest(
                prompt=normalized_prompt,
                size=size,
            )
        )

        if self.db_path is not None:
            previous_path = save_generated_image(
                self.db_path,
                cache_key,
                result,
                self.retention_days,
                self.busy_timeout_ms,
            )
            if previous_path is not None:
                try:
                    previous_path.unlink(missing_ok=True)
                except OSError:
                    pass

        LOGGER.info(
            "image.skill.generate.complete image_id=%s file=%s cached=%s",
            result.image_id,
            result.file_path,
            result.cached,
        )
        return result

    def edit(
        self,
        prompt: str,
        image_path: Path,
        mask_bytes: bytes,
        aspect_ratio: str | None = None,
        use_cache: bool = True,
    ) -> ImageGenerationResult:
        LOGGER.info(
            "image.skill.edit.start source=%s mask_bytes=%s aspect_ratio=%s "
            "use_cache=%s prompt=%s",
            image_path,
            len(mask_bytes),
            aspect_ratio,
            use_cache,
            log_value(prompt),
        )
        normalized_prompt = normalize_image_prompt(prompt)
        normalized_ratio = aspect_ratio or "1:1"
        size = self.size_by_aspect_ratio.get(
            normalized_ratio,
            self.size_by_aspect_ratio["1:1"],
        )
        mask_hash = hashlib.sha256(mask_bytes).hexdigest()
        cache_key = build_generated_image_cache_key(
            normalized_prompt,
            self.cache_scope,
            f"edit:{image_path.name}:{mask_hash}",
            size,
        )

        if self.db_path is not None and use_cache:
            cached = get_cached_generated_image(
                self.db_path,
                cache_key,
                self.busy_timeout_ms,
            )
            if cached is not None and cached.file_path.is_file():
                LOGGER.info(
                    "image.skill.edit.cache_hit image_id=%s file=%s",
                    cached.image_id,
                    cached.file_path,
                )
                return cached

        LOGGER.info(
            "image.skill.edit.provider_call source=%s size=%s cache_key=%s",
            image_path,
            size,
            cache_key,
        )
        result = self.provider.edit(
            ImageEditRequest(
                prompt=normalized_prompt,
                image_path=image_path,
                mask_bytes=mask_bytes,
                size=size,
            )
        )

        if self.db_path is not None:
            previous_path = save_generated_image(
                self.db_path,
                cache_key,
                result,
                self.retention_days,
                self.busy_timeout_ms,
            )
            if previous_path is not None:
                try:
                    previous_path.unlink(missing_ok=True)
                except OSError:
                    pass

        LOGGER.info(
            "image.skill.edit.complete image_id=%s file=%s cached=%s",
            result.image_id,
            result.file_path,
            result.cached,
        )
        return result


def build_image_generation_skill(
    settings: Settings,
) -> ImageGenerationSkill | None:
    if (
        settings.image_api_key is None
        or not settings.image_model
    ):
        return None

    provider = OpenAIImageProvider(
        api_key=settings.image_api_key.get_secret_value(),
        api_base=settings.image_api_base,
        model=settings.image_model,
        output_dir=settings.image_output_dir,
        timeout_seconds=settings.image_timeout_seconds,
        connect_timeout_seconds=settings.image_connect_timeout_seconds,
        max_download_bytes=settings.image_max_download_bytes,
        response_format=settings.image_response_format,
        output_format=settings.image_output_format,
    )
    initialize_database(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    for expired_path in purge_expired_generated_images(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    ):
        try:
            expired_path.unlink(missing_ok=True)
        except OSError:
            continue

    return ImageGenerationSkill(
        provider,
        {
            "1:1": settings.image_size_square,
            "3:2": settings.image_size_landscape,
            "2:3": settings.image_size_portrait,
        },
        db_path=settings.prompt_db_path,
        cache_scope=f"openai-compatible:{settings.image_model}",
        retention_days=settings.image_retention_days,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
