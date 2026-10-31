"""手动备份 / 查看 / 恢复。

    uv run python scripts/backup.py                # 立刻备份一份
    uv run python scripts/backup.py --list         # 看现有快照
    uv run python scripts/backup.py --restore prompt_index-20261031-101500.sqlite3

恢复时务必先停服务：SQLite 的 -wal / -shm 文件必须一起清掉，否则会读到
旧库的未提交内容。
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prompt_search_agent.backup import (
    backup_dir,
    create_backup,
    list_backups,
)
from prompt_search_agent.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description="数据库快照")
    parser.add_argument("--list", action="store_true", help="列出快照")
    parser.add_argument("--restore", help="用指定快照覆盖当前库")
    args = parser.parse_args()

    settings = Settings()
    db_path = settings.prompt_db_path

    if args.list:
        backups = list_backups(db_path)

        if not backups:
            print(f"还没有快照：{backup_dir(db_path)}")
            return 0

        for path in reversed(backups):
            print(f"{path.name}  {path.stat().st_size / 1e6:.1f} MB")

        return 0

    if args.restore:
        source = backup_dir(db_path) / args.restore

        if not source.is_file():
            print(f"找不到快照：{source}")
            return 1

        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{db_path}{suffix}")
            sidecar.unlink(missing_ok=True)

        shutil.copy2(source, db_path)
        print(f"已用 {source.name} 覆盖 {db_path}")
        print("提示：请确认服务已停止，再重新启动。")
        return 0

    target = create_backup(db_path, settings.sqlite_busy_timeout_ms)

    if target is None:
        print("备份失败，查看日志")
        return 1

    print(f"快照已生成：{target}")
    print(f"现有快照 {len(list_backups(db_path))} 份，保留上限 {settings.backup_keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
