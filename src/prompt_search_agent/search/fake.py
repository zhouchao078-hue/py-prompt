"""In-memory search backend for the initial vertical slice.

TODO: Implement a fake backend backed by tests/fixtures/prompts.jsonl.
"""
from pathlib import Path

from pydantic import ValidationError

from prompt_search_agent.models import PromptCandidate, PromptRecord, SearchRequest


class FakePromptSearchBackend:
    def __init__(self, prompts_path: Path) -> None:
        self.prompts_path = prompts_path
        self.records = load_prompt_records(prompts_path)


    @staticmethod
    def _extract_terms(request:SearchRequest) -> list[str]:
        """Extract terms from request."""
        raw_terms = [
            request.subject,
            request.scene,
            request.style,
            request.camera,
            request.mood,
            *request.keywords,
        ]

        terms: list[str] = []
        seen: set[str] = set()
        for value in raw_terms:
            if value is None:
                continue
            normalized = value.strip().casefold()
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            terms.append(normalized)
        return terms



    def search(self, request: SearchRequest, top_k: int = 5) -> list[PromptCandidate]:
        terms = self._extract_terms(request)
        if not terms:
            return []
        candidates :list[PromptCandidate] = []

        for record in self.records:
            prompt_text = record.prompt_text.casefold()
            matched_terms = [
                term for term in terms
                if term in prompt_text
            ]
            if not matched_terms:
                continue
            score = len(matched_terms) / len(terms)

            candidate = PromptCandidate(
                **record.model_dump(),
                relevance_score= score,
                matched_terms = matched_terms

            )
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: item.relevance_score,
            reverse=True
        )
        if top_k <= 0:
            return []
        return candidates[:top_k]



def load_prompt_records(path: Path) -> list[PromptRecord]:
    records: list[PromptRecord] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = PromptRecord.model_validate_json(line)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid Prompt Record at {path}:{line_number}"
                ) from exc
            records.append(record)
    return records
