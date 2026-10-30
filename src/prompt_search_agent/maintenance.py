"""磁盘巡检：图片、缓存、会话的定期回收。

为什么要独立模块：此前 `purge_expired_generated_images` 只在启动时调用一次，
常驻进程跑几个月都不会回收，图片是最快的磁盘增长源（实测 2.25MB/张）。
"""

import logging
import shutil
from pathlib import Path

from prompt_search_agent.config import Settings
from prompt_search_agent.storage.conversation import (
    delete_stale_conversations,
)
from prompt_search_agent.storage.database import reclaim_database
from prompt_search_agent.storage.generated_images import (
    purge_expired_generated_images,
)
from prompt_search_agent.storage.query_cache import delete_stale_cache

LOGGER = logging.getLogger(__name__)


def disk_free_bytes(data_dir: Path) -> int:
    """取所在卷的剩余空间；目录还没建出来时向上找最近的已存在祖先。"""
    candidate = data_dir.resolve()
    probe = candidate

    while not probe.exists() and probe.parent != probe:
        probe = probe.parent

    return shutil.disk_usage(probe).free


def run_janitor(settings: Settings) -> dict[str, int]:
    """跑一轮回收，返回各项处理数量。失败只会记日志，不影响服务。"""
    removed_images = 0
    removed_cache = 0
    removed_conversations = 0

    try:
        expired = purge_expired_generated_images(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        )
        removed_images = len(expired)

        for path in expired:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("删除过期图片失败: %s", path)
    except Exception:
        LOGGER.warning("回收过期图片失败", exc_info=True)

    try:
        removed_cache = delete_stale_cache(
            settings.prompt_db_path,
            settings.cache_retention_days,
            settings.sqlite_busy_timeout_ms,
        )
    except Exception:
        LOGGER.warning("回收过期缓存失败", exc_info=True)

    try:
        removed_conversations = delete_stale_conversations(
            settings.prompt_db_path,
            settings.conversation_retention_days,
            settings.sqlite_busy_timeout_ms,
        )
    except Exception:
        LOGGER.warning("回收过期会话失败", exc_info=True)

    try:
        # 删除后把空闲页还给文件系统，否则库文件只涨不缩。
        reclaim_database(
            settings.prompt_db_path,
            settings.sqlite_busy_timeout_ms,
        )
    except Exception:
        LOGGER.warning("回收数据库空间失败", exc_info=True)

    free_gb = disk_free_bytes(settings.data_dir) / 1e9

    LOGGER.info(
        "巡检完成: 图片 %s 张, 缓存 %s 行, 会话 %s 条, 剩余磁盘 %.1fGB",
        removed_images,
        removed_cache,
        removed_conversations,
        free_gb,
    )

    return {
        "images": removed_images,
        "cache": removed_cache,
        "conversations": removed_conversations,
    }
