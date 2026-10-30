"""首次启动时把随包发布的 seed 数据导入空库。

为什么需要：``data/indexes/`` 在 .gitignore 里，新机器启动后提示词库是空的，
FTS 检索链会整体失效。把库导出成 ``data/seed/prompts.jsonl.gz`` 提交进 Git，
启动时按需还原。
"""

import gzip
import json
import logging
from contextlib import closing
from pathlib import Path

from prompt_search_agent.ingest.records import RawPromptRecord
from prompt_search_agent.ingest.transformer import prepare_prompt_records
from prompt_search_agent.storage.database import connect_database
from prompt_search_agent.storage.repository import insert_prompt_records

LOGGER = logging.getLogger(__name__)


def count_prompts(db_path: Path, busy_timeout_ms: int = 5000) -> int:
    with closing(connect_database(db_path, busy_timeout_ms)) as connection:
        row = connection.execute("SELECT COUNT(*) AS total FROM prompts").fetchone()
    return int(row["total"]) if row is not None else 0


def import_seed_if_empty(
    db_path: Path,
    seed_file: Path,
    busy_timeout_ms: int = 5000,
) -> int:
    """仅当 prompts 表为空时导入 seed，返回本次导入条数。"""
    if not seed_file.is_file():
        LOGGER.warning("seed 文件不存在，跳过导入: %s", seed_file)
        return 0

    existing = count_prompts(db_path, busy_timeout_ms)

    if existing:
        LOGGER.info("提示词库已有 %s 条，跳过 seed 导入", existing)
        return 0

    raw_records: list[RawPromptRecord] = []

    with gzip.open(seed_file, "rt", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()

            if not stripped:
                continue

            try:
                item = json.loads(stripped)
            except json.JSONDecodeError:
                LOGGER.warning("seed 第 %s 行不是合法 JSON，已跳过", line_no)
                continue

            prompt_text = str(item.get("prompt_text") or "").strip()

            if not prompt_text:
                continue

            raw_records.append(
                RawPromptRecord(
                    prompt_text=prompt_text,
                    category=item.get("category"),
                    source_file=str(item.get("source_file") or "seed"),
                    source_sheet=str(item.get("source_sheet") or "seed"),
                    source_row=int(item.get("source_row") or 0),
                )
            )

    if not raw_records:
        LOGGER.warning("seed 文件里没有可用记录: %s", seed_file)
        return 0

    inserted = insert_prompt_records(
        db_path,
        prepare_prompt_records(raw_records),
        busy_timeout_ms,
    )
    LOGGER.info("seed 导入完成: %s 条", inserted)
    return inserted
