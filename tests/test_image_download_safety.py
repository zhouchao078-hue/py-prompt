"""图片下载路径的安全测试：SSRF、协议白名单、大小上限。"""

import base64

import pytest

from prompt_search_agent.images.base import ImageGenerationError
from prompt_search_agent.images.openai_compatible import (
    _assert_safe_url,
    _decode_base64_image,
    _download_image,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/a.png",
        "http://127.0.0.1/x.png",
        "http://localhost/x.png",
        "http://10.0.0.5/x.png",
        "http://192.168.1.1/x.png",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x.png",
        "http://0.0.0.0/x.png",
    ],
)
def test_unsafe_urls_are_rejected(url: str) -> None:
    with pytest.raises(ImageGenerationError):
        _assert_safe_url(url)


def test_download_refuses_before_opening_connection() -> None:
    """file:// 必须在建立连接前就被拒掉，不能读到本地文件。"""
    with pytest.raises(ImageGenerationError):
        _download_image("file:///etc/passwd", 5.0, 1024)


def test_base64_oversize_rejected_without_decoding() -> None:
    payload = base64.b64encode(b"A" * 10_000).decode()

    with pytest.raises(ImageGenerationError):
        _decode_base64_image(payload, max_bytes=1024)


def test_base64_within_limit_is_decoded() -> None:
    content = b"PNGTEST" * 8
    payload = base64.b64encode(content).decode()

    decoded, _ = _decode_base64_image(payload, max_bytes=1024)

    assert decoded == content


def test_data_uri_is_size_checked() -> None:
    content = b"X" * 5000
    payload = f"data:image/png;base64,{base64.b64encode(content).decode()}"

    with pytest.raises(ImageGenerationError):
        _decode_base64_image(payload, max_bytes=1024)
