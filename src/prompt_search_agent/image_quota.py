"""图片生成配额。

和全局限流分开的原因：一次生图的成本是文本生成的 10~100 倍，磁盘占用是
50 倍。用同一个桶量两者，便宜的会被贵的挤占，贵的又只受到便宜的保护。

两个维度：
* 每小时 N 张（按 IP），控制总量与账单；
* 同时 M 张在飞（按进程），控制并发——限流管不住这个，
  因为 20 个请求可以均匀分散在一小时内却同时处于"在飞"状态。
"""

import threading
import time
from collections import defaultdict, deque

RATE_WINDOW_SECONDS = 3600.0
TRACKED_IPS_LIMIT = 1024


class ImageQuota:
    def __init__(self, per_ip_per_hour: int, max_in_flight: int) -> None:
        self.per_ip_per_hour = per_ip_per_hour
        self.max_in_flight = max_in_flight
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._slots = threading.BoundedSemaphore(max_in_flight)
        self._lock = threading.Lock()

    def reserve(self, ip: str) -> float | None:
        """成功返回占位时间戳（退还时要带回），失败返回 None。"""
        now = time.monotonic()

        with self._lock:
            if len(self._hits) > TRACKED_IPS_LIMIT:
                self._sweep(now)

            hits = self._hits[ip]

            while hits and now - hits[0] > RATE_WINDOW_SECONDS:
                hits.popleft()

            if len(hits) >= self.per_ip_per_hour:
                return None

        if not self._slots.acquire(blocking=False):
            return None

        with self._lock:
            self._hits[ip].append(now)

        return now

    def release(self, ip: str, stamp: float, refund: bool = False) -> None:
        """任务结束释放并发位；命中缓存时把小时配额也退回去。"""
        self._slots.release()

        if not refund:
            return

        with self._lock:
            hits = self._hits.get(ip)

            if not hits:
                return

            try:
                hits.remove(stamp)
            except ValueError:
                pass

    def _sweep(self, now: float) -> None:
        stale = [
            ip
            for ip, hits in self._hits.items()
            if not hits or now - hits[-1] > RATE_WINDOW_SECONDS
        ]

        for ip in stale:
            del self._hits[ip]
