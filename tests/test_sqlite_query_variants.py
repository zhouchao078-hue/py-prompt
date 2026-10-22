from pathlib import Path

from prompt_search_agent.ingest.records import PreparedPromptRecord
from prompt_search_agent.models import SearchRequest
from prompt_search_agent.search.sqlite import SqlitePromptSearchBackend
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
        category="动物",
        source_file="test.xlsx",
        source_sheet="Sheet1",
        source_row=2,
    )


def test_query_variants_recall_composed_chinese_terms(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)
    insert_prompt_records(
        db_path,
        [
            make_record(
                "p001",
                "一只白色短毛胖小猫在雪山上滑雪",
                "一只 白色 短毛 短毛胖 胖 小猫 雪山 雪地 滑雪",
                "hash-001",
            )
        ],
    )
    backend = SqlitePromptSearchBackend(db_path)

    results = backend.search(
        SearchRequest(
            subject="白猫",
            query_variants=["白色 小猫"],
        ),
        top_k=5,
    )

    assert len(results) == 1
    assert results[0].prompt_id == "p001"
    assert results[0].matched_terms == ["白色", "小猫"]


def test_aspect_ratio_does_not_participate_in_search(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)
    insert_prompt_records(
        db_path,
        [
            make_record(
                "p002",
                "只包含画幅数字的提示词",
                "2 3",
                "hash-002",
            )
        ],
    )
    backend = SqlitePromptSearchBackend(db_path)

    results = backend.search(
        SearchRequest(
            subject="不存在的词",
            aspect_ratio="2:3",
        ),
        top_k=5,
    )

    assert results == []
