"""Image provider for OpenAI-compatible APIs and relays."""

import base64
import binascii
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from openai import OpenAI, OpenAIError

from prompt_search_agent.images.base import (
    ImageGenerationError,
    ImageGenerationRequest,
    ImageGenerationResult,
)

DownloadedImage = tuple[bytes, str | None]
ImageDownloader = Callable[[str], DownloadedImage]


def _download_image(url: str, timeout_seconds: float) -> DownloadedImage:
    request = Request(
        url,
        headers={"User-Agent": "prompt-search-agent/0.1"},
    )

    with urlopen(request, timeout=timeout_seconds) as response:
        content = response.read()
        content_type = response.headers.get_content_type()
        return content, content_type


def _read_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _normalize_response_items(response: Any) -> list[Any]:
    data = _read_value(response, "data")

    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        return list(data)
    if data is None:
        return []
    return [data]


def _detect_extension(
    content: bytes,
    content_type: str | None,
) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    ):
        return ".webp"

    normalized_type = (content_type or "").split(";", maxsplit=1)[0].lower()
    return {
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(normalized_type, ".png")


def _decode_base64_image(
    encoded_image: str,
) -> DownloadedImage:
    content_type: str | None = None
    payload = encoded_image.strip()

    if payload.startswith("data:image/"):
        header, separator, payload = payload.partition(",")
        if not separator:
            raise ValueError("Invalid image data URI")

        content_type = (
            header.removeprefix("data:")
            .split(";", maxsplit=1)[0]
            or None
        )

    try:
        return base64.b64decode(payload), content_type
    except (ValueError, binascii.Error) as exc:
        raise ImageGenerationError(
            "Image API returned invalid base64 data"
        ) from exc


class OpenAIImageProvider:
    """Generate images through an OpenAI-compatible image endpoint."""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        output_dir: Path,
        timeout_seconds: float = 120.0,
        max_download_bytes: int = 25_000_000,
        response_format: str | None = None,
        client: Any | None = None,
        downloader: ImageDownloader | None = None,
    ) -> None:
        self.model = model
        self.output_dir = output_dir
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.response_format = response_format
        self.client = client or OpenAI(
            api_key=api_key,
            base_url=api_base.rstrip("/"),
            timeout=timeout_seconds,
        )
        self.downloader = downloader or (
            lambda url: _download_image(url, timeout_seconds)
        )

    def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        request_options: dict[str, Any] = {
            "model": self.model,
            "prompt": request.prompt,
            "n": 1,
            "size": request.size,
        }

        if self.response_format:
            request_options["response_format"] = self.response_format

        try:
            response = self.client.images.generate(**request_options)
        except OpenAIError as exc:
            raise ImageGenerationError(
                f"Image API request failed: {exc}"
            ) from exc

        items = _normalize_response_items(response)
        if not items:
            raise ImageGenerationError(
                "Image API returned no image data"
            )

        item = items[0]
        encoded_image = _read_value(item, "b64_json")
        image_url = _read_value(item, "url")
        revised_prompt = _read_value(item, "revised_prompt")

        content, content_type = self._load_image(
            encoded_image=encoded_image,
            image_url=image_url,
        )

        if not content:
            raise ImageGenerationError(
                "Image API returned empty image data"
            )

        if len(content) > self.max_download_bytes:
            raise ImageGenerationError(
                "Generated image exceeds the configured size limit"
            )

        extension = _detect_extension(content, content_type)
        image_id = uuid4().hex
        file_name = f"{image_id}{extension}"
        file_path = self.output_dir / file_name

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            temporary_path = file_path.with_suffix(
                f"{file_path.suffix}.tmp"
            )
            temporary_path.write_bytes(content)
            temporary_path.replace(file_path)
        except OSError as exc:
            raise ImageGenerationError(
                "Failed to save the generated image"
            ) from exc

        return ImageGenerationResult(
            image_id=image_id,
            file_name=file_name,
            file_path=file_path,
            prompt=request.prompt,
            revised_prompt=(
                revised_prompt
                if isinstance(revised_prompt, str)
                else None
            ),
            provider="openai-compatible",
            model=self.model,
            size=request.size,
        )

    def _load_image(
        self,
        encoded_image: Any,
        image_url: Any,
    ) -> DownloadedImage:
        if isinstance(encoded_image, str) and encoded_image:
            return _decode_base64_image(encoded_image)

        if isinstance(image_url, str) and image_url:
            if image_url.startswith("data:image/"):
                return _decode_base64_image(image_url)

            try:
                return self.downloader(image_url)
            except (OSError, URLError, ValueError) as exc:
                raise ImageGenerationError(
                    "Failed to download the generated image"
                ) from exc

        raise ImageGenerationError(
            "Image API response must include "
            "data[0].b64_json or data[0].url"
        )
