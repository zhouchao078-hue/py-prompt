"""Pydantic models shared by the search workflow.

TODO: Define SearchRequest, PromptCandidate, and SearchResult.
"""
from typing import Literal

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


class RerankedCandidate(BaseModel):
    prompt_id: str
    relevance_score: float = Field(ge=0, le=1)
    reason: str


class RerankResult(BaseModel):
    selected: list[RerankedCandidate] = Field(default_factory=list)
    needs_generation: bool = False


class PromptQualityResult(BaseModel):
    score: int = Field(ge=0, le=100)
    passed: bool
    missing_requirements: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    irrelevant_content: list[str] = Field(default_factory=list)
    verdict: str


class IntentResult(BaseModel):
    intent: Literal[
        "create",
        "modify",
        "vague_feedback",
        "other",
    ]
    confidence: float = Field(ge=0, le=1)
    clarification_question: str | None = None
    reason: str


class WebSource(BaseModel):
    title: str
    url: str
    content: str
