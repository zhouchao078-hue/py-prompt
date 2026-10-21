import argparse
from pathlib import Path

from prompt_search_agent.config import PROJECT_ROOT
from prompt_search_agent.ingest.batch_importer import (
    import_xlsx_directory,
)
DEFAULT_DB_PATH = (
    PROJECT_ROOT / "data" / "indexes" / "prompt_index.sqlite3"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import all XLSX prompt workbooks into SQLite",
    )
    parser.add_argument(
        "directory_path",
        type=Path,
        help="Directory containing .xlsx workbook files",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path",
    )
    args = parser.parse_args()

    if not args.directory_path.exists():
        print(f"Directory not found: {args.directory_path}")
        return 1

    if not args.directory_path.is_dir():
        print(f"Not a directory: {args.directory_path}")
        return 1

    result = import_xlsx_directory(
        args.directory_path,
        args.db_path,
    )

    print(f"Directory: {args.directory_path}")
    print(f"Files found: {result.file_count}")
    print(f"Successful: {result.successful_files}")
    print(f"Failed: {result.failed_files}")
    print(f"Raw records: {result.raw_count}")
    print(f"Prepared records: {result.prepared_count}")
    print(f"Inserted records: {result.inserted_count}")
    print(f"Duplicates/filtered: {result.duplicate_count}")
    print(f"Database: {args.db_path}")

    if result.failures:
        print()
        print("Failed files:")

        for failure in result.failures:
            print(f"- {failure.source_file}: {failure.error}")

        return 1

    if result.file_count == 0:
        print()
        print("No .xlsx files found.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
