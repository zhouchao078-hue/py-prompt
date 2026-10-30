"""磁盘巡检：过期缓存与会话的回收。"""

import sqlite3
from pathlib import Path

from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.maintenance import run_janitor
from prompt_search_agent.storage import (
    ConversationRepository,
    initialize_database,
    save_cached_prompt,
)
from prompt_search_agent.storage.conversation import delete_stale_conversations
from prompt_search_agent.storage.query_cache import delete_stale_cache


def build_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
        data_dir=tmp_path,
    )
    initialize_database(settings.prompt_db_path)
    return settings


def age_rows(db_path: Path, table: str) -> None:
    connection = sqlite3.connect(db_path)

    try:
        connection.execute(
            f"UPDATE {table} SET created_at = datetime('now', '-90 days')"
        )
        connection.commit()
    finally:
        connection.close()


def age_conversations(db_path: Path) -> None:
    """往前挪到足够早：同一秒内比较会因为秒级精度取等而失败。"""
    connection = sqlite3.connect(db_path)

    try:
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = datetime('now', '-400 days')
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_stale_cache_is_deleted(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    save_cached_prompt(
        db_path=settings.prompt_db_path,
        cache_key="k1",
        normalized_query="q",
        model_name="m",
        prompt_version="v",
        index_version="i",
        final_prompt="p",
    )
    age_rows(settings.prompt_db_path, "query_cache")

    assert delete_stale_cache(settings.prompt_db_path, keep_days=30) == 1
    assert delete_stale_cache(settings.prompt_db_path, keep_days=30) == 0


def test_recent_cache_is_kept(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    save_cached_prompt(
        db_path=settings.prompt_db_path,
        cache_key="k1",
        normalized_query="q",
        model_name="m",
        prompt_version="v",
        index_version="i",
        final_prompt="p",
    )

    assert delete_stale_cache(settings.prompt_db_path, keep_days=30) == 0


def test_stale_conversations_are_deleted(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    repo = ConversationRepository(settings.prompt_db_path)
    repo.append_message("old-thread", "user", "hello")

    age_conversations(settings.prompt_db_path)

    assert delete_stale_conversations(settings.prompt_db_path, keep_days=90) == 1

    # 会话删掉后，消息由外键级联清理
    assert repo.list_messages("old-thread") == []


def test_janitor_reports_counts(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    save_cached_prompt(
        db_path=settings.prompt_db_path,
        cache_key="k1",
        normalized_query="q",
        model_name="m",
        prompt_version="v",
        index_version="i",
        final_prompt="p",
    )
    age_rows(settings.prompt_db_path, "query_cache")

    result = run_janitor(settings)

    assert result["cache"] == 1
    assert set(result) == {"images", "cache", "conversations"}
