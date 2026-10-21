from pathlib import Path

from prompt_search_agent.ingest.extractors.xlsx import XlsxPromptExtractor
from prompt_search_agent.ingest.records import ImportResult
from prompt_search_agent.ingest.transformer import prepare_prompt_records
from prompt_search_agent.storage import initialize_database, insert_prompt_records


def import_xlsx_workbook(workbook_path: Path,db_path: Path,busy_timeout_ms: int = 5000,) -> ImportResult:
    raw_records = XlsxPromptExtractor().extract(workbook_path)
    perpare_records = prepare_prompt_records(raw_records)
    initialize_database(db_path, busy_timeout_ms)
    insert_count = insert_prompt_records(
        db_path,
        perpare_records,
        busy_timeout_ms,
    )
    duplicate_count = len(raw_records) - len(perpare_records)
    mp = ImportResult(
        raw_count = len(raw_records),
        prepared_count = len(perpare_records),
        inserted_count = insert_count,
        duplicate_count = duplicate_count
    )
    return mp