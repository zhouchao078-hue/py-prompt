"""极简指标登记表：输出 Prometheus 文本格式，不引入额外依赖。

为什么需要它：系统现在有七八个降级分支（熔断、排队、磁盘、上游失败），
没有指标就只能靠翻日志才知道"正在降级"。其中 limiter_waiting 是唯一的
雪崩前兆信号——它持续大于 0，说明上游变慢或并发已满。
"""

import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response

DEFAULT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 45.0)

Labels = tuple[tuple[str, str], ...]

PREFIX = "prompt_atelier_"


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _format_labels(labels: Labels, extra: Labels = ()) -> str:
    merged = dict(labels)
    merged.update(dict(extra))

    if not merged:
        return ""

    body = ",".join(
        f'{key}="{_escape(value)}"' for key, value in sorted(merged.items())
    )
    return "{" + body + "}"


class Metrics:
    def __init__(self, buckets: tuple[float, ...] = DEFAULT_BUCKETS) -> None:
        self._buckets = tuple(buckets)
        self._lock = threading.Lock()
        self._counters: dict[str, dict[Labels, float]] = defaultdict(dict)
        self._histograms: dict[str, dict[Labels, list[float]]] = defaultdict(
            dict
        )

    def inc(
        self,
        name: str,
        labels: Labels = (),
        value: float = 1.0,
    ) -> None:
        with self._lock:
            bucket = self._counters[PREFIX + name]
            bucket[labels] = bucket.get(labels, 0.0) + value

    def observe(
        self,
        name: str,
        value: float,
        labels: Labels = (),
    ) -> None:
        with self._lock:
            entry = self._histograms[PREFIX + name].get(labels)

            if entry is None:
                entry = [0.0] * (len(self._buckets) + 2)
                self._histograms[PREFIX + name][labels] = entry

            for index, bound in enumerate(self._buckets):
                if value <= bound:
                    entry[index] += 1

            entry[-2] += value
            entry[-1] += 1

    def render(self, gauges: dict[str, tuple[float, Labels]] | None = None) -> str:
        lines: list[str] = []

        with self._lock:
            for name, samples in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")

                for labels, value in sorted(samples.items()):
                    lines.append(f"{name}{_format_labels(labels)} {value:g}")

            for name, samples in sorted(self._histograms.items()):
                lines.append(f"# TYPE {name} histogram")

                for labels, entry in sorted(samples.items()):
                    for index, bound in enumerate(self._buckets):
                        lines.append(
                            f"{name}_bucket"
                            f"{_format_labels(labels, (('le', f'{bound:g}'),))}"
                            f" {entry[index]:g}"
                        )

                    lines.append(
                        f"{name}_bucket"
                        f"{_format_labels(labels, (('le', '+Inf'),))}"
                        f" {entry[-1]:g}"
                    )
                    lines.append(
                        f"{name}_sum{_format_labels(labels)} {entry[-2]:g}"
                    )
                    lines.append(
                        f"{name}_count{_format_labels(labels)} {entry[-1]:g}"
                    )

        if gauges:
            for name, (value, labels) in sorted(gauges.items()):
                metric = PREFIX + name
                lines.append(f"# TYPE {metric} gauge")
                lines.append(f"{metric}{_format_labels(labels)} {value:g}")

        return "\n".join(lines) + "\n"


METRICS = Metrics()


def observe_request(request: Request, status: int, elapsed: float) -> None:
    """用路由模板而不是真实路径，避免 uuid 造成标签基数爆炸。"""
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")

    METRICS.inc(
        "requests_total",
        (("path", path), ("status", str(status))),
    )
    METRICS.observe("request_seconds", elapsed, (("path", path),))


def install_metrics(app: FastAPI) -> None:
    """必须装在安全中间件之后：后加的在最外层，被拒绝的请求也要计数。"""

    @app.middleware("http")
    async def metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # 未捕获异常会被外层 ServerErrorMiddleware 转成 500，
            # 这里必须先记一笔，否则 500 永远不进指标。
            observe_request(request, 500, time.perf_counter() - started)
            raise

        observe_request(
            request,
            response.status_code,
            time.perf_counter() - started,
        )
        return response


def metrics_response(gauges: dict[str, tuple[float, Labels]]) -> PlainTextResponse:
    return PlainTextResponse(
        METRICS.render(gauges),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
