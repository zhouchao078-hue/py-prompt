from pathlib import Path

from prompt_search_agent.ingest.records import PreparedPromptRecord
from prompt_search_agent.storage import (
    build_cache_key,
    build_prompt_version,
    connect_database,
    delete_cached_prompt,
    get_cached_prompt,
    get_cached_sources_json,
    get_prompt_index_version,
    initialize_database,
    insert_prompt_records,
    save_cached_prompt,
)


def make_record() -> PreparedPromptRecord:
    return PreparedPromptRecord(
        prompt_id="p001",
        prompt_text="雪夜里的白色小猫",
        search_tokens="雪夜 白色 小猫",
        content_hash="hash-001",
        category="动物",
        source_file="test.xlsx",
        source_sheet="Sheet1",
        source_row=2,
    )


def test_build_cache_key_is_deterministic() -> None:
    first = build_cache_key(
        normalized_query="雪夜里的白猫",
        model_name="deepseek-flash",
        prompt_version="prompt-v1",
        index_version="10:1",
    )
    second = build_cache_key(
        normalized_query="雪夜里的白猫",
        model_name="deepseek-flash",
        prompt_version="prompt-v1",
        index_version="10:1",
    )

    assert first == second
    assert first != build_cache_key(
        normalized_query="雪夜里的白猫",
        model_name="deepseek-flash",
        prompt_version="prompt-v2",
        index_version="10:1",
    )


def test_build_prompt_version_is_deterministic() -> None:
    first = build_prompt_version("parse", "compose")
    second = build_prompt_version("parse", "compose")

    assert first == second
    assert first != build_prompt_version("parse", "compose-v2")


def test_cached_prompt_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)
    cache_key = build_cache_key(
        normalized_query="雪夜里的白猫",
        model_name="deepseek-flash",
        prompt_version="prompt-v1",
        index_version="0:0",
    )

    save_cached_prompt(
        db_path=db_path,
        cache_key=cache_key,
        normalized_query="雪夜里的白猫",
        model_name="deepseek-flash",
        prompt_version="prompt-v1",
        index_version="0:0",
        final_prompt="最终提示词",
        sources_json=(
            '[{"title":"source","url":"https://example.com",'
            '"content":"reference"}]'
        ),
    )

    assert get_cached_prompt(
        db_path,
        cache_key,
    ) == "最终提示词"
    assert get_cached_sources_json(
        db_path,
        cache_key,
    ) == (
        '[{"title":"source","url":"https://example.com",'
        '"content":"reference"}]'
    )
    assert delete_cached_prompt(
        db_path,
        cache_key,
    ) is True
    assert get_cached_prompt(
        db_path,
        cache_key,
    ) is None
    assert delete_cached_prompt(
        db_path,
        cache_key,
    ) is False


def test_prompt_index_version_changes_after_insert(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)

    before = get_prompt_index_version(db_path)
    insert_prompt_records(db_path, [make_record()])
    after = get_prompt_index_version(db_path)

    assert before != after


def test_prompt_index_version_tracks_updates_and_deletes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)
    insert_prompt_records(db_path, [make_record()])
    after_insert = get_prompt_index_version(db_path)

    with connect_database(db_path) as connection:
        connection.execute(
            """
            UPDATE prompts
            SET prompt_text = ?,
                search_tokens = ?
            WHERE prompt_id = ?
            """,
            ("更新后的提示词", "更新 提示词", "p001"),
        )
        connection.commit()

    after_update = get_prompt_index_version(db_path)

    with connect_database(db_path) as connection:
        connection.execute(
            "DELETE FROM prompts WHERE prompt_id = ?",
            ("p001",),
        )
        connection.commit()

    after_delete = get_prompt_index_version(db_path)

    assert after_insert == "1:1:1"
    assert after_update == "1:1:2"
    assert after_delete == "0:0:3"
