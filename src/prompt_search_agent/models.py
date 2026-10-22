"""Pydantic models shared by the search workflow.

TODO: Define SearchRequest, PromptCandidate, and SearchResult.
"""
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    subject: str | None = None
    scene: str | None = None
    style: str | None = None
    camera: str | None = None
    mood: str | None = None
    query_variants: list[str] = Field(default_factory=list)
    aspect_ratio: str | None = None
    keywords: list[str] = Field(default_factory=list)


class PromptRecord(BaseModel):
    prompt_id: str
    prompt_text: str
    category: str | None
    source_file: str | None
    source_sheet: str | None
    source_row: int | None


class PromptCandidate(PromptRecord):
    relevance_score: float = Field(ge=0, le=1)
    matched_terms: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    query: SearchRequest
    candidates: list[PromptCandidate]
