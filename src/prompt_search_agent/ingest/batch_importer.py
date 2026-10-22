from pathlib import Path
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError
from xlrd.biffh import XLRDError

from prompt_search_agent.ingest.importer import import_prompt_workbook
from prompt_search_agent.ingest.records import BatchImportResult, ImportFailure


def import_excel_directory(
    directory_path: Path,
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> BatchImportResult:
    files = [
        file_path
        for file_path in sorted(
            [
                *directory_path.glob("*.xlsx"),
                *directory_path.glob("*.xls"),
            ]
        )
        if not file_path.name.startswith("~$")
    ]
    raw_count = 0
    prepared_count = 0
    inserted_count = 0
    duplicate_count = 0
    successful_files = 0
    failures: list[ImportFailure] = []
    for file_path in files:
        try:
            result = import_prompt_workbook(
                file_path,
                db_path,
                busy_timeout_ms,
            )
        except (
            OSError,
            BadZipFile,
            InvalidFileException,
            ValidationError,
            XLRDError,
            ) as exc:
            failures.append(
                ImportFailure(
                    source_file=file_path.name,
                    error=str(exc),
                )
            )
            continue
        successful_files += 1
        raw_count += result.raw_count
        prepared_count += result.prepared_count
        inserted_count += result.inserted_count
        duplicate_count += result.duplicate_count
    return BatchImportResult(
        file_count=len(files),
        successful_files=successful_files,
        failed_files=len(failures),
        raw_count=raw_count,
        prepared_count=prepared_count,
        inserted_count=inserted_count,
        duplicate_count=duplicate_count,
        failures=failures,
    )


def import_xlsx_directory(
    directory_path: Path,
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> BatchImportResult:
    """Backward-compatible alias for Excel directory imports."""

    return import_excel_directory(
        directory_path,
        db_path,
        busy_timeout_ms,
    )
