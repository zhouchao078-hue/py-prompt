from pathlib import Path

import pytest

from prompt_search_agent.models import SearchRequest
from prompt_search_agent.search.fake import FakePromptSearchBackend

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "prompts.jsonl"


def make_backend() -> FakePromptSearchBackend:
    return FakePromptSearchBackend(FIXTURE_PATH)
def test_search_finds_hanfu_snow_scene() -> None:
    backend = make_backend()
    request = SearchRequest(
        subject="少女",
        scene="雪夜",
        style="电影感",
        camera="低机位",
    )

    results = backend.search(request)

    assert len(results) == 2
    assert results[0].prompt_id == "p001"
    assert results[0].relevance_score == pytest.approx(1.0)
    assert results[0].matched_terms == [
        "少女",
        "雪夜",
        "电影感",
        "低机位",
    ]
    assert results[1].prompt_id == "p002"
    assert results[1].relevance_score == pytest.approx(0.5)
def test_search_respects_top_k() -> None:
    backend = make_backend()
    request = SearchRequest(
        subject="少女",
        scene="雪夜",
        style="电影感",
        camera="低机位",
    )

    results = backend.search(request, top_k=1)

    assert len(results) == 1
    assert results[0].prompt_id == "p001"
def test_search_returns_empty_when_nothing_matches() -> None:
    backend = make_backend()
    request = SearchRequest(subject="宇航员")

    results = backend.search(request)

    assert results == []
def test_search_returns_empty_for_empty_request() -> None:
    backend = make_backend()

    results = backend.search(SearchRequest())

    assert results == []
def test_search_returns_empty_for_zero_top_k() -> None:
    backend = make_backend()
    request = SearchRequest(subject="少女")

    results = backend.search(request, top_k=0)

    assert results == []