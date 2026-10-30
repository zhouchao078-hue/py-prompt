"""上游熔断。

目的很单纯：一个挂掉的 DeepSeek 不应该把 8 个并发槽位全部吃满。
连续失败到阈值后，冷却期内直接拒绝，让请求快速失败而不是排队等超时。
"""

import logging
import threading
import time

LOGGER = logging.getLogger(__name__)


class UpstreamUnavailable(RuntimeError):
    """熔断打开期间抛出。"""


class GenerationCancelled(Exception):
    """客户端断开后，在阶段边界中止生成，避免继续花上游的钱。"""


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open_locked()

    def _is_open_locked(self) -> bool:
        if self._failures < self.failure_threshold:
            return False

        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            # 冷却结束，放一个探针请求过去。
            self._failures = 0
            return False

        return True

    def guard(self) -> None:
        if self.is_open:
            raise UpstreamUnavailable("上游服务连续失败，已进入冷却期")

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1

            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()
                LOGGER.warning(
                    "熔断打开：连续 %s 次失败，冷却 %ss",
                    self._failures,
                    self.cooldown_seconds,
                )
