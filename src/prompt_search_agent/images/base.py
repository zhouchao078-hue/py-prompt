"""Shared contracts for image generation providers."""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class ImageGenerationError(RuntimeError):
    """Raised when an image provider cannot produce an image."""


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    size: str


class ImageEditRequest(BaseModel):
    prompt: str = Field(min_length=1)
    image_path: Path
    mask_bytes: bytes
    size: str


class ImageGenerationResult(BaseModel):
    image_id: str
    file_name: str
    file_path: Path
    prompt: str
    revised_prompt: str | None = None
    provider: str
    model: str
    size: str
    cached: bool = False


class ImageProvider(Protocol):
    def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult: ...

    def edit(
        self,
        request: ImageEditRequest,
    ) -> ImageGenerationResult: ...
