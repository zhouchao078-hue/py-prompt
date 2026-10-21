from contextlib import closing
from pathlib import Path

from prompt_search_agent.ingest.records import PreparedPromptRecord
from prompt_search_agent.storage import connect_database


def insert_prompt_records(db_path: Path,records: list[PreparedPromptRecord],busy_timeout_ms: int = 5000,) -> int:
    if not records:
        return 0
    insert_count = 0
    with closing(connect_database(db_path,busy_timeout_ms)) as connection:
        with connection:
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