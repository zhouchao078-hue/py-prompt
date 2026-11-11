"""Image provider for OpenAI-compatible APIs and relays."""

import base64
import binascii
import ipaddress
import logging
import mimetypes
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)
from uuid import uuid4

import httpx2
from openai import APITimeoutError, OpenAI, OpenAIError

from prompt_search_agent.images.base import (
    ImageEditRequest,
    ImageGenerationError,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from prompt_search_agent.log_utils import log_value

DownloadedImage = tuple[bytes, str | None]
ImageDownloader = Callable[[str], DownloadedImage]

ALLOWED_SCHEMES = frozenset({"http", "https"})
LOGGER = logging.getLogger(__name__)
IMAGE_ENDPOINT_SUFFIXES = (
    "/images/generations",
    "/images/edits",
)
IMAGE_CONNECT_ATTEMPTS = 3


def _normalize_api_base(api_base: str) -> str:
    """Accept either an API root or a complete image endpoint URL."""
    normalized = api_base.rstrip("/")

    for suffix in IMAGE_ENDPOINT_SUFFIXES:
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]

    return normalized


def _call_with_connect_retry(operation: Callable[[], Any]) -> Any:
    """Retry only TLS/connect failures; read timeouts may already cost a generation."""
    for attempt in range(IMAGE_CONNECT_ATTEMPTS):
        try:
            return operation()
        except APITimeoutError as exc:
            cause = type(exc.__cause__).__name__
            connect_timeout = isinstance(
                exc.__cause__,
                httpx2.ConnectTimeout,
            )

            if (
                connect_timeout
                and attempt < IMAGE_CONNECT_ATTEMPTS - 1
            ):
                LOGGER.warning(
                    "image.api.retry reason=connect_timeout "
                    "request_sent=false attempt=%s/%s cause=%s message=%s",
                    attempt + 1,
                    IMAGE_CONNECT_ATTEMPTS,
                    cause,
                    log_value(str(exc)),
                )
                time.sleep(0.8 * (attempt + 1))
                continue

            LOGGER.warning(
                "image.api.timeout retry=false reason=%s "
                "request_sent=%s error_type=%s cause=%s message=%s",
                (
                    "connect_exhausted"
                    if connect_timeout
                    else "response_timeout"
                ),
                "false" if connect_timeout else "unknown",
                type(exc).__name__,
                cause,
                log_value(str(exc)),
            )
            raise

    raise RuntimeError("Unreachable image request retry state")


def _is_public_host(host: str) -> bool:
    """回环、内网、链路本地地址一律拒绝，避免图片地址把我们变成内网代理。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False

    if not infos:
        return False

    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False

        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return False

    return True


def _assert_safe_url(url: str) -> None:
    """只允许 http/https，且目标必须是公网地址。"""
    parsed = urlparse(url)

    # file:// 会把服务器本地文件当图片回吐给调用方。
    if parsed.scheme.casefold() not in ALLOWED_SCHEMES:
        raise ImageGenerationError(
            f"图片地址协议不被允许: {parsed.scheme or 'unknown'}"
        )

    if not parsed.hostname or not _is_public_host(parsed.hostname):
        raise ImageGenerationError("图片地址指向非公网主机，已拒绝下载")


class _GuardedRedirectHandler(HTTPRedirectHandler):
    """跟随重定向，但每一跳都重新校验，防止公网地址跳到内网。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(_GuardedRedirectHandler())


def _download_image(
    url: str,
    timeout_seconds: float,
    max_bytes: int,
) -> DownloadedImage:
    _assert_safe_url(url)

    request = Request(
        url,
        headers={"User-Agent": "prompt-search-agent/0.1"},
    )

    with _OPENER.open(request, timeout=timeout_seconds) as response:
        # 多读一个字节就能判断是否超限，不用先把整个文件读进内存。
        content = response.read(max_bytes + 1)

        if len(content) > max_bytes:
            raise ImageGenerationError("生成的图片超过大小上限")

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
    max_bytes: int,
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

    # 先按长度估算再解码，避免几百 MB 的串在内存里展开。
    if len(payload) * 3 // 4 > max_bytes:
        raise ImageGenerationError("生成的图片超过大小上限")

    try:
        content = base64.b64decode(payload)
    except (ValueError, binascii.Error) as exc:
        raise ImageGenerationError(
            "Image API returned invalid base64 data"
        ) from exc

    if len(content) > max_bytes:
        raise ImageGenerationError("生成的图片超过大小上限")

    return content, content_type


class OpenAIImageProvider:
    """Generate images through an OpenAI-compatible image endpoint."""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        output_dir: Path,
        timeout_seconds: float = 120.0,
        connect_timeout_seconds: float = 20.0,
        max_download_bytes: int = 25_000_000,
        response_format: str | None = None,
        output_format: str | None = None,
        client: Any | None = None,
        downloader: ImageDownloader | None = None,
    ) -> None:
        self.model = model
        self.output_dir = output_dir
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.response_format = response_format
        self.output_format = output_format
        normalized_api_base = _normalize_api_base(api_base)
        self.generation_url = (
            f"{normalized_api_base}/images/generations"
        )
        self.edit_url = f"{normalized_api_base}/images/edits"
        self.client = client or OpenAI(
            api_key=api_key,
            base_url=normalized_api_base,
            timeout=httpx2.Timeout(
                timeout_seconds,
                connect=min(connect_timeout_seconds, timeout_seconds),
                read=timeout_seconds,
                write=min(60.0, timeout_seconds),
                pool=min(30.0, timeout_seconds),
            ),
            max_retries=0,
        )
        self.downloader = downloader or (
            lambda url: _download_image(
                url,
                timeout_seconds,
                max_download_bytes,
            )
        )

    def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        started = time.perf_counter()
        LOGGER.info(
            "image.generate.request endpoint=%s model=%s "
            "size=%s response_format=%s output_format=%s prompt=%s",
            self.generation_url,
            self.model,
            request.size,
            self.response_format or "default",
            self.output_format or "default",
            log_value(request.prompt),
        )

        request_options: dict[str, Any] = {
            "model": self.model,
            "prompt": request.prompt,
            "n": 1,
            "size": request.size,
        }

        if self.response_format:
            request_options["response_format"] = self.response_format

        if self.output_format:
            request_options["output_format"] = self.output_format

        try:
            response = _call_with_connect_retry(
                lambda: self.client.images.generate(**request_options)
            )
        except OpenAIError as exc:
            LOGGER.error(
                "image.generate.error endpoint=%s model=%s "
                "size=%s elapsed_ms=%s error_type=%s message=%s",
                self.generation_url,
                self.model,
                request.size,
                int((time.perf_counter() - started) * 1000),
                type(exc).__name__,
                log_value(str(exc)),
            )
            raise ImageGenerationError(
                f"Image API request failed: {exc}"
            ) from exc

        result = self._store_response(
            response,
            request.prompt,
            request.size,
            operation="generate",
        )
        LOGGER.info(
            "image.generate.complete endpoint=%s model=%s "
            "size=%s elapsed_ms=%s image_id=%s file=%s cached=%s",
            self.generation_url,
            self.model,
            request.size,
            int((time.perf_counter() - started) * 1000),
            result.image_id,
            result.file_path,
            result.cached,
        )
        return result

    def edit(
        self,
        request: ImageEditRequest,
    ) -> ImageGenerationResult:
        started = time.perf_counter()
        LOGGER.info(
            "image.edit.request endpoint=%s model=%s size=%s "
            "response_format=%s output_format=%s source=%s mask_bytes=%s "
            "prompt=%s",
            self.edit_url,
            self.model,
            request.size,
            self.response_format or "default",
            self.output_format or "default",
            request.image_path,
            len(request.mask_bytes),
            log_value(request.prompt),
        )
        try:
            image_content = request.image_path.read_bytes()
        except OSError as exc:
            LOGGER.error(
                "image.edit.source_error source=%s error_type=%s message=%s",
                request.image_path,
                type(exc).__name__,
                log_value(str(exc)),
            )
            raise ImageGenerationError(
                "Failed to read the source image"
            ) from exc

        if not image_content:
            LOGGER.error("image.edit.invalid_source reason=empty")
            raise ImageGenerationError("Source image is empty")
        if len(image_content) > self.max_download_bytes:
            LOGGER.error(
                "image.edit.invalid_source reason=source_too_large bytes=%s "
                "max_bytes=%s",
                len(image_content),
                self.max_download_bytes,
            )
            raise ImageGenerationError("Source image exceeds the size limit")
        if not request.mask_bytes:
            LOGGER.error("image.edit.invalid_mask reason=empty")
            raise ImageGenerationError("Edit mask is empty")
        if len(request.mask_bytes) > self.max_download_bytes:
            LOGGER.error(
                "image.edit.invalid_mask reason=mask_too_large bytes=%s "
                "max_bytes=%s",
                len(request.mask_bytes),
                self.max_download_bytes,
            )
            raise ImageGenerationError("Edit mask exceeds the size limit")

        image_content_type = (
            mimetypes.guess_type(request.image_path.name)[0]
            or "application/octet-stream"
        )

        request_options: dict[str, Any] = {
            "model": self.model,
            "image": (
                request.image_path.name,
                image_content,
                image_content_type,
            ),
            "mask": (
                "mask.png",
                request.mask_bytes,
                "image/png",
            ),
            "prompt": request.prompt,
            "n": 1,
            "size": request.size,
        }

        if self.response_format:
            request_options["response_format"] = self.response_format

        if self.output_format:
            request_options["output_format"] = self.output_format

        try:
            response = _call_with_connect_retry(
                lambda: self.client.images.edit(**request_options)
            )
        except OpenAIError as exc:
            LOGGER.error(
                "image.edit.error endpoint=%s model=%s size=%s "
                "elapsed_ms=%s error_type=%s message=%s",
                self.edit_url,
                self.model,
                request.size,
                int((time.perf_counter() - started) * 1000),
                type(exc).__name__,
                log_value(str(exc)),
            )
            raise ImageGenerationError(
                f"Image edit API request failed: {exc}"
            ) from exc

        result = self._store_response(
            response,
            request.prompt,
            request.size,
            operation="edit",
        )
        LOGGER.info(
            "image.edit.complete endpoint=%s model=%s size=%s "
            "elapsed_ms=%s image_id=%s file=%s cached=%s",
            self.edit_url,
            self.model,
            request.size,
            int((time.perf_counter() - started) * 1000),
            result.image_id,
            result.file_path,
            result.cached,
        )
        return result

    def _store_response(
        self,
        response: Any,
        prompt: str,
        size: str,
        operation: str,
    ) -> ImageGenerationResult:
        items = _normalize_response_items(response)
        if not items:
            LOGGER.error(
                "image.response.invalid operation=%s reason=no_items "
                "response=%s",
                operation,
                log_value(response),
            )
            raise ImageGenerationError(
                "Image API returned no image data"
            )

        item = items[0]
        encoded_image = _read_value(item, "b64_json")
        image_url = _read_value(item, "url")
        revised_prompt = _read_value(item, "revised_prompt")
        item_keys = (
            sorted(str(key) for key in item)
            if isinstance(item, Mapping)
            else "-"
        )
        LOGGER.info(
            "image.response.received operation=%s items=%s item_keys=%s "
            "b64_chars=%s url_present=%s revised_prompt=%s",
            operation,
            len(items),
            log_value(item_keys),
            len(encoded_image) if isinstance(encoded_image, str) else 0,
            bool(image_url),
            log_value(revised_prompt),
        )

        content, content_type = self._load_image(
            encoded_image=encoded_image,
            image_url=image_url,
        )
        LOGGER.info(
            "image.response.loaded operation=%s bytes=%s content_type=%s "
            "revised_prompt=%s",
            operation,
            len(content),
            content_type or "-",
            log_value(revised_prompt),
        )

        if not content:
            LOGGER.error(
                "image.response.invalid operation=%s reason=empty_content",
                operation,
            )
            raise ImageGenerationError(
                "Image API returned empty image data"
            )

        if len(content) > self.max_download_bytes:
            LOGGER.error(
                "image.response.invalid operation=%s reason=too_large "
                "bytes=%s max_bytes=%s",
                operation,
                len(content),
                self.max_download_bytes,
            )
            raise ImageGenerationError(
                "Generated image exceeds the configured size limit"
            )

        extension = _detect_extension(content, content_type)
        image_id = uuid4().hex
        file_name = f"{image_id}{extension}"
        file_path = self.output_dir / file_name
        LOGGER.info(
            "image.file.save.start operation=%s path=%s bytes=%s",
            operation,
            file_path,
            len(content),
        )

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            temporary_path = file_path.with_suffix(
                f"{file_path.suffix}.tmp"
            )
            temporary_path.write_bytes(content)
            temporary_path.replace(file_path)
        except OSError as exc:
            LOGGER.exception(
                "image.file.save.error operation=%s path=%s",
                operation,
                file_path,
            )
            raise ImageGenerationError(
                "Failed to save the generated image"
            ) from exc
        LOGGER.info(
            "image.file.save.complete operation=%s path=%s bytes=%s",
            operation,
            file_path,
            len(content),
        )

        return ImageGenerationResult(
            image_id=image_id,
            file_name=file_name,
            file_path=file_path,
            prompt=prompt,
            revised_prompt=(
                revised_prompt
                if isinstance(revised_prompt, str)
                else None
            ),
            provider="openai-compatible",
            model=self.model,
            size=size,
        )

    def _load_image(
        self,
        encoded_image: Any,
        image_url: Any,
    ) -> DownloadedImage:
        if isinstance(encoded_image, str) and encoded_image:
            return _decode_base64_image(
                encoded_image,
                self.max_download_bytes,
            )

        if isinstance(image_url, str) and image_url:
            if image_url.startswith("data:image/"):
                return _decode_base64_image(
                    image_url,
                    self.max_download_bytes,
                )

            parsed_url = urlparse(image_url)
            LOGGER.info(
                "image.response.download.start scheme=%s host=%s",
                parsed_url.scheme,
                parsed_url.hostname or "-",
            )
            try:
                return self.downloader(image_url)
            except (OSError, URLError, ValueError) as exc:
                LOGGER.error(
                    "image.response.download.error error_type=%s message=%s",
                    type(exc).__name__,
                    log_value(str(exc)),
                )
                raise ImageGenerationError(
                    "Failed to download the generated image"
                ) from exc

        LOGGER.error(
            "image.response.invalid reason=missing_b64_or_url"
        )
        raise ImageGenerationError(
            "Image API response must include "
            "data[0].b64_json or data[0].url"
        )
