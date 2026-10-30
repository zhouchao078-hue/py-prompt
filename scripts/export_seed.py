"""把本地构建好的提示词库导出为可提交进 Git 的 seed 文件。

用法：
    uv run python scripts/export_seed.py
    uv run python scripts/export_seed.py --db data/indexes/prompt_index.sqlite3
"""

import argparse
import gzip
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "indexes" / "prompt_index.sqlite3"
DEFAULT_OUT = PROJECT_ROOT / "data" / "seed" / "prompts.jsonl.gz"

SELECT_SQL = """
SELECT prompt_text, category, source_file, source_sheet, source_row
FROM prompts
ORDER BY id
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="导出提示词库快照")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"数据库不存在: {args.db}")
        return 1

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(SELECT_SQL).fetchall()
    finally:
        connection.close()

    if not rows:
        print("提示词库为空，未生成 seed 文件")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(args.out, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")

    size = args.out.stat().st_size
    print(f"已导出 {len(rows)} 条 -> {args.out} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
