import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prompt_search_agent.backup import (
    create_backup,
    list_backups,
    prune_backups,
)
from prompt_search_agent.storage import initialize_database


def seed(db_path: Path, rows: int = 3) -> None:
    initialize_database(db_path)
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS samples(value TEXT)"
    )
    connection.executemany(
        "INSERT INTO samples(value) VALUES (?)",
        [(f"row-{index}",) for index in range(rows)],
    )
    connection.commit()
    connection.close()


def count_rows(db_path: Path) -> int:
    connection = sqlite3.connect(db_path)
    try:
        return int(
            connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        )
    finally:
        connection.close()


def test_backup_contains_the_same_data(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite3"
    seed(db_path, rows=5)

    target = create_backup(db_path, keep=10)

    assert target is not None and target.is_file()
    assert count_rows(target) == 5


def test_backups_are_pruned_to_keep_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite3"
    seed(db_path)
    base = datetime(2026, 10, 31, 10, 0, 0, tzinfo=UTC)

    for hour in range(5):
        create_backup(db_path, keep=10, now=base + timedelta(hours=hour))

    assert len(list_backups(db_path)) == 5

    removed = prune_backups(db_path, keep=2)

    remaining = list_backups(db_path)
    assert removed == 3
    assert len(remaining) == 2
    # 留下的是最近的两份：10:00 起第 5 份是 14:00，第 4 份是 13:00
    assert remaining[-1].name.endswith("140000.sqlite3")
    assert remaining[0].name.endswith("130000.sqlite3")


def test_backup_is_skipped_when_database_missing(tmp_path: Path) -> None:
    assert create_backup(tmp_path / "missing.sqlite3") is None


def test_same_second_backup_is_not_duplicated(tmp_path: Path) -> None:
    db_path = tmp_path / "index.sqlite3"
    seed(db_path)
    moment = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)

    first = create_backup(db_path, now=moment)
    second = create_backup(db_path, now=moment)

    assert first == second
    assert len(list_backups(db_path)) == 1
