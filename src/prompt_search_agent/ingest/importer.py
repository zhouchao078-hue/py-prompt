from pathlib import Path

from prompt_search_agent.ingest.extractors.xls import XlsPromptExtractor
from prompt_search_agent.ingest.extractors.xlsx import XlsxPromptExtractor
from prompt_search_agent.ingest.records import ImportResult
from prompt_search_agent.ingest.transformer import prepare_prompt_records
from prompt_search_agent.storage import (
    initialize_database,
    insert_prompt_records,
    optimize_database,
)


def import_prompt_workbook(
    workbook_path: Path,
    db_path: Path,
    busy_timeout_ms: int = 5000,
    optimize: bool = True,
) -> ImportResult:
    suffix = workbook_path.suffix.lower()

    if suffix == ".xlsx":
        raw_records = XlsxPromptExtractor().extract(workbook_path)
    elif suffix == ".xls":
        raw_records = XlsPromptExtractor().extract(workbook_path)
    else:
        raise ValueError(f"Unsupported workbook type: {suffix}")

    prepared_records = prepare_prompt_records(raw_records)
    initialize_database(db_path, busy_timeout_ms)
    insert_count = insert_prompt_records(
        db_path,
        prepared_records,
        busy_timeout_ms,
    )
    duplicate_count = len(raw_records) - len(prepared_records)
    if optimize:
        optimize_database(db_path, busy_timeout_ms)

    mp = ImportResult(
        raw_count=len(raw_records),
        prepared_count=len(prepared_records),
        inserted_count=insert_count,
        duplicate_count=duplicate_count,
    )
    return mp


def import_xlsx_workbook(
    workbook_path: Path,
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> ImportResult:
    """Backward-compatible alias for an XLSX workbook."""

    return import_prompt_workbook(
        workbook_path,
        db_path,
        busy_timeout_ms,
        optimize=True,
    )
