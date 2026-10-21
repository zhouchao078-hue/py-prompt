import argparse
from pathlib import Path

from prompt_search_agent.config import PROJECT_ROOT
from prompt_search_agent.ingest.importer import import_xlsx_workbook
from prompt_search_agent.ingest.records import ImportResult

DEFAULT_DB_PATH = (
    PROJECT_ROOT / "data" / "indexes" / "prompt_index.sqlite3"
)

def xlsximport(workbook_path: Path,db_path: Path = DEFAULT_DB_PATH,) -> ImportResult:
    return import_xlsx_workbook(
        workbook_path,
        db_path,
    )
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import one XLSX prompt workbook into SQLite",
    )
    parser.add_argument(
        "workbook_path",
        type=Path,
        help="Path to a single .xlsx workbook",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path",
    )
    args = parser.parse_args()

    if not args.workbook_path.exists():
        print(f"Workbook not found: {args.workbook_path}")
        return 1

    if args.workbook_path.suffix.lower() != ".xlsx":
        print(f"Unsupported file type: {args.workbook_path.suffix}")
        return 1

    result = xlsximport(
        args.workbook_path,
        args.db_path,
    )

    print(f"Workbook: {args.workbook_path.name}")
    print(f"Raw records: {result.raw_count}")
    print(f"Prepared records: {result.prepared_count}")
    print(f"Inserted records: {result.inserted_count}")
    print(f"Duplicates/filtered: {result.duplicate_count}")
    print(f"Database: {args.db_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
