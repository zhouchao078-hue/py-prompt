from contextlib import closing
from pathlib import Path

from pydantic import BaseModel

from prompt_search_agent.ingest.records import (
    PreparedPromptRecord,
    RawPromptRecord,
)
from prompt_search_agent.ingest.transformer import prepare_prompt_records
from prompt_search_agent.storage.database import connect_database


class AddedPromptRecord(BaseModel):
    prompt_id: str
    prompt_text: str
    inserted: bool


def insert_prompt_records(db_path: Path,records: list[PreparedPromptRecord],busy_timeout_ms: int = 5000,) -> int:
    if not records:
        return 0
    insert_count = 0
    with closing(connect_database(db_path,busy_timeout_ms)) as connection, connection:
        for record in records:
            cursor = connection.execute(
            """INSERT INTO prompts(
                    prompt_id,
                    prompt_text,
                    search_tokens,
                    content_hash,
                    category,
                    source_file,
                    source_sheet,
                    source_row
                )VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(content_hash) DO NOTHING;""",
                (
                    record.prompt_id,
                    record.prompt_text,
                    record.search_tokens,
                    record.content_hash,
                    record.category,
                    record.source_file,
                    record.source_sheet,
                    record.source_row
                ),
            )
            insert_count += cursor.rowcount

    return insert_count


def add_prompt_text(
    db_path: Path,
    prompt_text: str,
    category: str | None = None,
    busy_timeout_ms: int = 5000,
) -> AddedPromptRecord | None:
    prepared = prepare_prompt_records(
        [
            RawPromptRecord(
                prompt_text=prompt_text,
                category=(category or "").strip() or "用户添加",
                source_file="manual",
                source_sheet="manual",
                source_row=0,
            )
        ]
    )

    if not prepared:
        return None

    record = prepared[0]
    inserted = insert_prompt_records(
        db_path,
        [record],
        busy_timeout_ms,
    )
    return AddedPromptRecord(
        prompt_id=record.prompt_id,
        prompt_text=record.prompt_text,
        inserted=inserted > 0,
    )
