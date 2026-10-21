from pathlib import Path

import pytest

from prompt_search_agent.ingest.records import PreparedPromptRecord
from prompt_search_agent.models import PromptCandidate, SearchRequest
from prompt_search_agent.search.sqlite import (
    SqlitePromptSearchBackend,
)
from prompt_search_agent.storage import (
    initialize_database,
    insert_prompt_records,
)


def make_record(
    prompt_id: str,
    prompt_text: str,
    search_tokens: str,
    content_hash: str,
) -> PreparedPromptRecord:
    return PreparedPromptRecord(
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        search_tokens=search_tokens,
        content_hash=content_hash,
        category="风景",
        source_file="test.xlsx",
        source_sheet="Sheet1",
        source_row=2,
    )


@pytest.fixture
def backend(tmp_path: Path) -> SqlitePromptSearchBackend:
    db_path = tmp_path / "prompt_index.sqlite3"

    initialize_database(db_path)

    records = [
        make_record(
            prompt_id="p001",
            prompt_text="北京市朝阳区的雪夜街头",
            search_tokens="北京 京市 朝阳 朝阳区 雪夜 街头",
            content_hash="hash-001",
        ),
        make_record(
            prompt_id="p002",
            prompt_text="一条安静的雪夜山路",
            search_tokens="安静 雪夜 山路",
            content_hash="hash-002",
        ),
    ]

    inserted = insert_prompt_records(db_path, records)
    assert inserted == 2

    return SqlitePromptSearchBackend(
        db_path=db_path,
        busy_timeout_ms=5000,
    )


def test_search_returns_prompt_candidate(
    backend: SqlitePromptSearchBackend,
) -> None:
    results = backend.search(
        SearchRequest(subject="朝阳"),
        top_k=5,
    )

    assert len(results) == 1
    assert isinstance(results[0], PromptCandidate)
    assert results[0].prompt_id == "p001"
    assert results[0].prompt_text == "北京市朝阳区的雪夜街头"
    assert results[0].matched_terms == ["朝阳"]
    assert results[0].relevance_score == pytest.approx(1.0)
    assert results[0].source_file == "test.xlsx"


def test_search_can_match_multiple_records(
    backend: SqlitePromptSearchBackend,
) -> None:
    results = backend.search(
        SearchRequest(scene="雪夜"),
        top_k=5,
    )

    result_ids = {item.prompt_id for item in results}

    assert result_ids == {"p001", "p002"}
    assert all(
        0.0 <= item.relevance_score <= 1.0
        for item in results
    )


def test_search_respects_top_k(
    backend: SqlitePromptSearchBackend,
) -> None:
    results = backend.search(
        SearchRequest(scene="雪夜"),
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].prompt_id in {"p001", "p002"}


def test_search_returns_empty_for_zero_top_k(
    backend: SqlitePromptSearchBackend,
) -> None:
    results = backend.search(
        SearchRequest(subject="朝阳"),
        top_k=0,
    )

    assert results == []


def test_search_returns_empty_for_empty_request(
    backend: SqlitePromptSearchBackend,
) -> None:
    results = backend.search(SearchRequest())

    assert results == []


def test_search_returns_empty_when_nothing_matches(
    backend: SqlitePromptSearchBackend,
) -> None:
    results = backend.search(
        SearchRequest(subject="宇航员"),
    )

    assert results == []