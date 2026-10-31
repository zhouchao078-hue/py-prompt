"""数据库快照备份。

用 `VACUUM INTO` 而不是复制文件：
* 它写出的是事务一致的快照，不会拷到一半的页；
* WAL 里还没合并的内容会被一并写进去，cp 出来的文件可能缺最近的数据。

快照每小时一份、保留最近 N 份（默认 24），文件名带时间戳，
按名字排序就是时间顺序。
"""

import logging
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from prompt_search_agent.storage.database import connect_database

LOGGER = logging.getLogger(__name__)

BACKUP_DIRNAME = "backups"
BACKUP_PREFIX = "prompt_index-"
BACKUP_SUFFIX = ".sqlite3"


def backup_dir(db_path: Path) -> Path:
    return db_path.parent / BACKUP_DIRNAME


def list_backups(db_path: Path) -> list[Path]:
    """按时间升序返回现有快照。"""
    directory = backup_dir(db_path)

    if not directory.is_dir():
        return []

    return sorted(directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))


def prune_backups(db_path: Path, keep: int) -> int:
    """只留最近的 keep 份，返回删除数量。"""
    backups = list_backups(db_path)

    if keep <= 0:
        excess = backups
    elif len(backups) > keep:
        excess = backups[:-keep]
    else:
        return 0

    removed = 0

    for path in excess:
        try:
            path.unlink()
            removed += 1
        except OSError:
            LOGGER.warning("删除旧快照失败: %s", path)

    return removed


def create_backup(
    db_path: Path,
    busy_timeout_ms: int = 5000,
    keep: int = 24,
    now: datetime | None = None,
) -> Path | None:
    """生成一份快照；失败只记日志，不影响主流程。"""
    if not db_path.exists():
        return None

    directory = backup_dir(db_path)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"

    if target.exists():
        # 同一秒内重复调用，直接复用
        return target

    try:
        directory.mkdir(parents=True, exist_ok=True)

        with closing(connect_database(db_path, busy_timeout_ms)) as connection:
            connection.execute("VACUUM INTO ?", (str(target),))
    except Exception:
        LOGGER.warning("数据库快照失败: %s", target, exc_info=True)

        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass

        return None

    prune_backups(db_path, keep)

    LOGGER.info(
        "数据库快照已生成: %s (%.1f MB)",
        target.name,
        target.stat().st_size / 1e6,
    )

    return target
