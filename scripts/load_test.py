"""一次性打满：并发压测客户端。

    python scripts/load_test.py --url http://127.0.0.1:8030 --concurrency 50

只依赖 httpx（已经在开发依赖里）。输出状态码分布、延迟分位与吞吐。
"""

import argparse
import asyncio
import time

import httpx

PROMPT_BODY = {"message": "雪夜里穿汉服的少女，电影感"}


async def hit(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[int, float]:
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{url}/api/prompt",
            json=PROMPT_BODY,
            timeout=120.0,
        )
        return response.status_code, time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 请求异常: {type(exc).__name__}: {exc}")
        return -1, time.perf_counter() - started


async def probe_health(
    client: httpx.AsyncClient,
    url: str,
    stop: asyncio.Event,
    samples: list[float],
) -> None:
    """压测期间持续探活：事件循环如果被阻塞，这里会立刻体现出来。"""
    while not stop.is_set():
        started = time.perf_counter()
        try:
            await client.get(f"{url}/api/health", timeout=5.0)
            samples.append(time.perf_counter() - started)
        except Exception:  # noqa: BLE001
            samples.append(float("inf"))
        await asyncio.sleep(0.1)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = min(int(len(ordered) * ratio), len(ordered) - 1)
    return ordered[index]


async def main() -> int:
    parser = argparse.ArgumentParser(description="一次性打满压测")
    parser.add_argument("--url", default="http://127.0.0.1:8030")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    headers = (
        {"Authorization": f"Bearer {args.token}"} if args.token else {}
    )
    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )

    async with httpx.AsyncClient(headers=headers, limits=limits) as client:
        stop = asyncio.Event()
        health_samples: list[float] = []
        probe = asyncio.create_task(
            probe_health(client, args.url, stop, health_samples)
        )

        started = time.perf_counter()
        results = await asyncio.gather(
            *(hit(client, args.url) for _ in range(args.concurrency))
        )
        wall = time.perf_counter() - started

        stop.set()
        await probe

    statuses: dict[int, int] = {}

    for status, _ in results:
        statuses[status] = statuses.get(status, 0) + 1

    latencies = [latency for _, latency in results]

    print(f"并发 {args.concurrency}  →  墙钟 {wall:.2f}s  "
          f"吞吐 {args.concurrency / wall:.1f} req/s")
    print("状态码分布: " + ", ".join(
        f"{status}×{count}" for status, count in sorted(statuses.items())
    ))
    print(
        f"延迟: p50={percentile(latencies, 0.50):.2f}s "
        f"p95={percentile(latencies, 0.95):.2f}s "
        f"p99={percentile(latencies, 0.99):.2f}s "
        f"max={max(latencies):.2f}s"
    )

    if health_samples:
        finite = [value for value in health_samples if value != float("inf")]
        lost = len(health_samples) - len(finite)
        print(
            f"压测期间 /api/health: 采样 {len(health_samples)} 次, "
            f"失败 {lost} 次, "
            f"p95={percentile(finite, 0.95) * 1000:.0f}ms"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
