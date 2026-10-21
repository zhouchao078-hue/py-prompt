import pytest
import sqlite3
from contextlib import closing
from pathlib import Path

from prompt_search_agent.ingest.records import PreparedPromptRecord
from prompt_search_agent.storage.database import (
    connect_database,
    initialize_database,
)
from prompt_search_agent.storage.repository import insert_prompt_records


def insert_prompt(
    connection: sqlite3.Connection,
    *,
    prompt_id: str = "p001",
    prompt_text: str = "北京市朝阳区的雪夜街头",
    search_tokens: str = "北京 京市 朝阳 朝阳区 雪夜 街头",
    content_hash: str = "hash-001",
) -> None:
    connection.execute(
        """
        INSERT INTO prompts (
            prompt_id,
            prompt_text,
            search_tokens,
            content_hash,
            category,
            source_file,
            source_sheet,
            source_row
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prompt_id,
            prompt_text,
            search_tokens,
            content_hash,
            "风景",
            "test.xlsx",
            "Sheet1",
            2,
        ),
    )
    connection.commit()
def test_initialize_database_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"

    initialize_database(db_path)

    assert db_path.exists()

    with closing(connect_database(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

        table_names = {row["name"] for row in rows}

    assert "prompts" in table_names
    assert "prompts_fts" in table_names


def test_insert_and_fts_search_chinese_token(tmp_path: Path) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)

    with closing(connect_database(db_path)) as connection:
        insert_prompt(connection)

        row = connection.execute(
            """
            SELECT p.prompt_text
            FROM prompts_fts
            JOIN prompts AS p ON p.id = prompts_fts.rowid
            WHERE prompts_fts MATCH ?
            LIMIT 1
            """,
            ('"朝阳"',),
        ).fetchone()

    assert row is not None
    assert row["prompt_text"] == "北京市朝阳区的雪夜街头"


def test_duplicate_content_hash_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)

    with closing(connect_database(db_path)) as connection:
        insert_prompt(connection)

        with pytest.raises(sqlite3.IntegrityError):
            insert_prompt(
                connection,
                prompt_id="p002",
                prompt_text="完全相同内容的另一条提示词",
                content_hash="hash-001",
            )


def test_delete_removes_record_from_fts(tmp_path: Path) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)

    with closing(connect_database(db_path)) as connection:
        insert_prompt(connection)

        connection.execute(
            "DELETE FROM prompts WHERE prompt_id = ?",
            ("p001",),
        )
        connection.commit()

        row = connection.execute(
            """
            SELECT p.prompt_text
            FROM prompts_fts
            JOIN prompts AS p ON p.id = prompts_fts.rowid
            WHERE prompts_fts MATCH ?
            LIMIT 1
            """,
            ('"朝阳"',),
        ).fetchone()

    assert row is None

def make_record() -> PreparedPromptRecord:
    return PreparedPromptRecord(
        prompt_id="hash-001",
        prompt_text="北京市朝阳区的雪夜街头",
        search_tokens="北京 京市 朝阳 朝阳区 雪夜 街头",
        content_hash="hash-001",
        category="风景",
        source_file="test.xlsx",
        source_sheet="Sheet1",
        source_row=2,
    )


def test_insert_prompt_records(tmp_path: Path) -> None:
    db_path = tmp_path / "prompt_index.sqlite3"
    initialize_database(db_path)

    record = make_record()

    assert insert_prompt_records(db_path, [record]) == 1
    assert insert_prompt_records(db_path, [record]) == 0

    with closing(connect_database(db_path)) as connection:
        row = connection.execute(
            """
            SELECT p.prompt_text
            FROM prompts_fts
            JOIN prompts AS p ON p.id = prompts_fts.rowid
            WHERE prompts_fts MATCH ?
            """,
            ('"朝阳"',),
        ).fetchone()

    assert row is not None
    assert row["prompt_text"] == "北京市朝阳区的雪夜街头"