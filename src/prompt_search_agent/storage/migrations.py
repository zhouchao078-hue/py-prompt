"""Schema 版本化迁移。

用 ``PRAGMA user_version`` 记录版本，启动时按序执行未应用的迁移。
以后改表结构只需往 ``MIGRATIONS`` 末尾追加一条，不必再手写
"判断列是否存在" 之类的临时逻辑，也不会在多实例启动时重复执行。
"""

import logging
import sqlite3
from collections.abc import Callable

LOGGER = logging.getLogger(__name__)

Migration = Callable[[sqlite3.Connection], None]


def _add_sources_json(connection: sqlite3.Connection) -> None:
    """v1：给老的 query_cache 补 sources_json 列。"""
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(query_cache)")
    }

    if "sources_json" not in columns:
        connection.execute(
            "ALTER TABLE query_cache ADD COLUMN sources_json TEXT"
        )


MIGRATIONS: list[tuple[int, Migration]] = [
    (1, _add_sources_json),
]

LATEST_VERSION = max(version for version, _ in MIGRATIONS)


def get_schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def apply_migrations(connection: sqlite3.Connection) -> int:
    current = get_schema_version(connection)

    if current >= LATEST_VERSION:
        return current

    for version, migration in MIGRATIONS:
        if version <= current:
            continue

        migration(connection)
        connection.execute(f"PRAGMA user_version = {int(version)}")
        LOGGER.info("已应用迁移 v%s", version)

    connection.commit()
    return LATEST_VERSION
