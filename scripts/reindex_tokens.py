"""按新的分词规则原地重建 prompts.search_tokens。

分类字段此前没有进入索引，导致「汉服」「婚纱」「玫瑰」这类只存在于
category 里的词完全搜不到。这个脚本把已有数据重算一遍，不重新导入。

    python scripts/reindex_tokens.py
    python scripts/reindex_tokens.py --dry-run
"""

import argparse
import sys
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from prompt_search_agent.config import Settings
from prompt_search_agent.ingest.transformer import (
    build_search_tokens,
)
from prompt_search_agent.storage import connect_database


def main() -> int:
    parser = argparse.ArgumentParser(description="重建提示词索引分词")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    changed = 0
    total = 0

    with closing(
        connect_database(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        )
    ) as connection:
        rows = connection.execute(
            "SELECT id, prompt_text, category, search_tokens FROM prompts"
        ).fetchall()

        for row in rows:
            total += 1
            tokens = " ".join(
                build_search_tokens(row["prompt_text"], row["category"])
            )

            if tokens == row["search_tokens"]:
                continue

            changed += 1

            if args.dry_run:
                continue

            connection.execute(
                "UPDATE prompts SET search_tokens = ? WHERE id = ?",
                (tokens, row["id"]),
            )

        if not args.dry_run:
            connection.commit()

    action = "将更新" if args.dry_run else "已更新"
    print(f"{action} {changed} / {total} 条")

    if args.dry_run:
        print("（dry-run，未写入）")
    else:
        print(f"数据库: {settings.prompt_db_path}")
        print("索引版本已变化，旧查询缓存会自动失效")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
