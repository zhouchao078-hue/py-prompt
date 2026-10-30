"""Image provider for OpenAI-compatible APIs and relays."""

import base64
import binascii
import ipaddress
import socket
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

from openai import OpenAI, OpenAIError

from prompt_search_agent.images.base import (
    ImageGenerationError,
    ImageGenerationRequest,
    ImageGenerationResult,
)

DownloadedImage = tuple[bytes, str | None]
ImageDownloader = Callable[[str], DownloadedImage]

ALLOWED_SCHEMES = frozenset({"http", "https"})


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
        self.client = client or OpenAI(
            api_key=api_key,
            base_url=api_base.rstrip("/"),
            timeout=timeout_seconds,
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
