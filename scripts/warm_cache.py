"""预热高频 query 的 query_cache，让演示首屏秒回。

关键点：cache key 里包含 conversation_context 的 hash，
所以必须用「全新会话」预热，才能和真实首轮命中同一条缓存。
"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from prompt_search_agent.config import Settings
from prompt_search_agent.services.prompt_service import (
    build_prompt_service,
)
from prompt_search_agent.storage import initialize_database

SAMPLE_QUERIES = [
    "雪夜里穿汉服的少女，电影感，低机位，冷色调",
    "一只白色短腿胖小猫在雪山上滑雪，电影感真实摄影，超广角，8k，--ar 2:3",
    "赛博朋克雨夜街头，孤独女杀手，霓虹反光，电影写实，低机位",
    "火星上的紫色机械鲸鱼，赛博朋克，电影感，超广角",
    "秋日午后咖啡馆窗边，胶片质感，浅景深，侧逆光",
    "敦煌壁画风格的飞天，工笔重彩，对称构图",
    "极简产品海报，白色背景，柔光，居中构图",
    "蒸汽朋克飞艇飞越伦敦上空，黄昏，云雾，广角",
    "水下失重感的舞者，蓝绿色调，束状光",
    "老式绿皮火车窗边的旅人，暖黄色调，胶片颗粒",
]


def main() -> int:
    settings = Settings()
    initialize_database(
        settings.prompt_db_path,
        settings.sqlite_busy_timeout_ms,
    )
    service = build_prompt_service(settings)

    warmed_threads: list[str] = []

    for query in SAMPLE_QUERIES:
        result = service.generate(query)
        warmed_threads.append(result.thread_id)
        flag = "CACHE" if result.cached else "MISS "
        print(f"{flag} {query[:30]}")

    _cleanup_threads(settings.prompt_db_path, warmed_threads)
    print(f"完成 {len(SAMPLE_QUERIES)} 条，临时会话已清理")
    return 0


def _cleanup_threads(db_path: Path, thread_ids: list[str]) -> None:
    """预热产生的临时会话不该留在演示库里。"""
    connection = sqlite3.connect(db_path)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executemany(
            "DELETE FROM conversations WHERE thread_id = ?",
            [(thread_id,) for thread_id in thread_ids],
        )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
