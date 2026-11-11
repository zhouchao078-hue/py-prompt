import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APITimeoutError

from prompt_search_agent.images import (
    ImageEditRequest,
    ImageGenerationRequest,
    OpenAIImageProvider,
)
from prompt_search_agent.images.openai_compatible import (
    _call_with_connect_retry,
    _normalize_api_base,
)
from prompt_search_agent.skills.image_generation import (
    ImageGenerationSkill,
)
from prompt_search_agent.storage import (
    connect_database,
    initialize_database,
    purge_expired_generated_images,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\nimage-data"


class FakeImages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response

    def edit(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeOpenAIClient:
    def __init__(self, response: Any) -> None:
        self.images = FakeImages(response)


def test_connect_timeout_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr(
        "prompt_search_agent.images.openai_compatible.time.sleep",
        lambda _: None,
    )

    def operation() -> str:
        nonlocal calls
        calls += 1

        if calls < 3:
            try:
                raise httpx2.ConnectTimeout("handshake timed out")
            except httpx2.ConnectTimeout as cause:
                raise APITimeoutError(
                    request=httpx2.Request(
                        "POST",
                        "https://relay.example.com/v1/images/generations",
                    )
                ) from cause

        return "ok"

    assert _call_with_connect_retry(operation) == "ok"
    assert calls == 3


def test_read_timeout_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr(
        "prompt_search_agent.images.openai_compatible.time.sleep",
        lambda _: None,
    )

    def operation() -> str:
        nonlocal calls
        calls += 1

        try:
            raise httpx2.ReadTimeout("response body timed out")
        except httpx2.ReadTimeout as cause:
            raise APITimeoutError(
                request=httpx2.Request(
                    "POST",
                    "https://relay.example.com/v1/images/generations",
                )
            ) from cause

    with pytest.raises(APITimeoutError):
        _call_with_connect_retry(operation)

    assert calls == 1


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (
            "https://relay.example.com/v1",
            "https://relay.example.com/v1",
        ),
        (
            "https://relay.example.com/v1/images/generations",
            "https://relay.example.com/v1",
        ),
        (
            "https://relay.example.com/v1/images/edits/",
            "https://relay.example.com/v1",
        ),
    ],
)
def test_image_api_base_accepts_root_or_full_endpoint(
    configured: str,
    expected: str,
) -> None:
    assert _normalize_api_base(configured) == expected


def test_provider_saves_base64_image(tmp_path: Path) -> None:
    client = FakeOpenAIClient(
        SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(PNG_BYTES).decode(),
                    url=None,
                    revised_prompt="A revised image prompt",
                )
            ]
        )
    )
    provider = OpenAIImageProvider(
        api_key="test-key",
        api_base="https://relay.example.com/v1",
        model="image-model",
        output_dir=tmp_path,
        client=client,
    )

    result = provider.generate(
        ImageGenerationRequest(
            prompt="a cat in the snow",
            size="1024x1536",
        )
    )

    assert result.file_path.read_bytes() == PNG_BYTES
    assert result.file_name.endswith(".png")
    assert result.revised_prompt == "A revised image prompt"
    assert client.images.calls == [
        {
            "model": "image-model",
            "prompt": "a cat in the snow",
            "n": 1,
            "size": "1024x1536",
        }
    ]


def test_provider_downloads_url_image(tmp_path: Path) -> None:
    client = FakeOpenAIClient(
        SimpleNamespace(
            data=[
                {
                    "b64_json": None,
                    "url": "https://cdn.example.com/image.webp",
                }
            ]
        )
    )
    provider = OpenAIImageProvider(
        api_key="test-key",
        api_base="https://relay.example.com/v1",
        model="image-model",
        output_dir=tmp_path,
        client=client,
        downloader=lambda _: (b"RIFF0000WEBPdata", "image/webp"),
    )

    result = provider.generate(
        ImageGenerationRequest(
            prompt="a city at night",
            size="1024x1024",
        )
    )

    assert result.file_name.endswith(".webp")
    assert result.file_path.read_bytes().startswith(b"RIFF")


def test_provider_edits_image_with_mask(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(PNG_BYTES)
    mask_bytes = b"\x89PNG\r\n\x1a\nmask-data"
    client = FakeOpenAIClient(
        SimpleNamespace(
            data=[
                {
                    "b64_json": base64.b64encode(PNG_BYTES).decode(),
                    "url": None,
                }
            ]
        )
    )
    provider = OpenAIImageProvider(
        api_key="test-key",
        api_base="https://relay.example.com/v1",
        model="image-model",
        output_dir=tmp_path / "output",
        client=client,
    )

    result = provider.edit(
        ImageEditRequest(
            prompt="replace the marked area with a red scarf",
            image_path=source_path,
            mask_bytes=mask_bytes,
            size="1024x1536",
        )
    )

    call = client.images.calls[0]
    assert call["prompt"] == "replace the marked area with a red scarf"
    assert call["size"] == "1024x1536"
    assert call["image"][0] == "source.png"
    assert call["image"][1] == PNG_BYTES
    assert call["mask"] == ("mask.png", mask_bytes, "image/png")
    assert result.file_path.read_bytes() == PNG_BYTES


def test_skill_maps_aspect_ratio_and_removes_ar_parameter(
    tmp_path: Path,
) -> None:
    client = FakeOpenAIClient(
        SimpleNamespace(
            data=[
                {
                    "b64_json": base64.b64encode(PNG_BYTES).decode(),
                    "url": None,
                }
            ]
        )
    )
    provider = OpenAIImageProvider(
        api_key="test-key",
        api_base="https://relay.example.com/v1",
        model="image-model",
        output_dir=tmp_path,
        client=client,
    )
    skill = ImageGenerationSkill(
        provider,
        {
            "1:1": "1024x1024",
            "3:2": "1536x1024",
            "2:3": "1024x1536",
        },
    )

    result = skill.invoke(
        "cinematic cat in snow --ar 2:3",
        "2:3",
    )

    assert result.size == "1024x1536"
    assert client.images.calls[0]["prompt"] == "cinematic cat in snow"
    assert client.images.calls[0]["size"] == "1024x1536"


def test_skill_edits_image_with_normalized_prompt(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(PNG_BYTES)
    client = FakeOpenAIClient(
        SimpleNamespace(
            data=[
                {
                    "b64_json": base64.b64encode(PNG_BYTES).decode(),
                    "url": None,
                }
            ]
        )
    )
    provider = OpenAIImageProvider(
        api_key="test-key",
        api_base="https://relay.example.com/v1",
        model="image-model",
        output_dir=tmp_path / "output",
        client=client,
    )
    skill = ImageGenerationSkill(
        provider,
        {
            "1:1": "1024x1024",
            "2:3": "1024x1536",
        },
    )

    result = skill.edit(
        "change the background to blue --ar 2:3",
        source_path,
        b"\x89PNG\r\n\x1a\nmask-data",
        "2:3",
    )

    assert result.size == "1024x1536"
    assert client.images.calls[0]["prompt"] == (
        "change the background to blue"
    )


def test_skill_reuses_cached_image_and_can_bypass_cache(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    output_dir = tmp_path / "images"
    initialize_database(db_path)
    client = FakeOpenAIClient(
        SimpleNamespace(
            data=[
                {
                    "b64_json": base64.b64encode(PNG_BYTES).decode(),
                    "url": None,
                }
            ]
        )
    )
    provider = OpenAIImageProvider(
        api_key="test-key",
        api_base="https://relay.example.com/v1",
        model="image-model",
        output_dir=output_dir,
        client=client,
    )
    skill = ImageGenerationSkill(
        provider,
        {"1:1": "1024x1024"},
        db_path=db_path,
        cache_scope="openai-compatible:image-model",
    )

    first = skill.invoke("a snowy cat", "1:1")
    second = skill.invoke("a snowy cat", "1:1")
    third = skill.invoke("a snowy cat", "1:1", use_cache=False)

    assert first.cached is False
    assert second.cached is True
    assert second.image_id == first.image_id
    assert third.cached is False
    assert third.image_id != first.image_id
    assert len(client.images.calls) == 2
    assert first.file_path.is_file() is False


def test_expired_generated_images_are_purged(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    output_dir = tmp_path / "images"
    initialize_database(db_path)
    client = FakeOpenAIClient(
        SimpleNamespace(
            data=[
                {
                    "b64_json": base64.b64encode(PNG_BYTES).decode(),
                    "url": None,
                }
            ]
        )
    )
    provider = OpenAIImageProvider(
        api_key="test-key",
        api_base="https://relay.example.com/v1",
        model="image-model",
        output_dir=output_dir,
        client=client,
    )
    skill = ImageGenerationSkill(
        provider,
        {"1:1": "1024x1024"},
        db_path=db_path,
        cache_scope="openai-compatible:image-model",
    )
    result = skill.invoke("an expiring image", "1:1")

    with connect_database(db_path) as connection:
        connection.execute(
            """
            UPDATE generated_images
            SET expires_at = datetime('now', '-1 minute')
            """
        )
        connection.commit()

    expired_paths = purge_expired_generated_images(db_path)
    for expired_path in expired_paths:
        expired_path.unlink(missing_ok=True)

    assert expired_paths == [result.file_path]
    assert result.file_path.is_file() is False
