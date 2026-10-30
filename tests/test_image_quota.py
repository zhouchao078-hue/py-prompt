"""图片配额：小时总量、在飞并发、缓存退还。"""

from prompt_search_agent.image_quota import ImageQuota


def test_hourly_limit_blocks_extra_reservations() -> None:
    quota = ImageQuota(per_ip_per_hour=2, max_in_flight=10)

    first = quota.reserve("1.1.1.1")
    second = quota.reserve("1.1.1.1")

    assert first is not None
    assert second is not None
    assert quota.reserve("1.1.1.1") is None


def test_hourly_limit_is_per_ip() -> None:
    quota = ImageQuota(per_ip_per_hour=1, max_in_flight=10)

    assert quota.reserve("1.1.1.1") is not None
    assert quota.reserve("1.1.1.1") is None
    # 另一个 IP 不受影响
    assert quota.reserve("2.2.2.2") is not None


def test_in_flight_limit_blocks_concurrency() -> None:
    quota = ImageQuota(per_ip_per_hour=100, max_in_flight=2)

    first = quota.reserve("1.1.1.1")
    second = quota.reserve("1.1.1.1")

    assert first is not None
    assert second is not None
    # 前两个还没释放，第三个不能进
    assert quota.reserve("1.1.1.1") is None

    quota.release("1.1.1.1", first)

    assert quota.reserve("1.1.1.1") is not None


def test_cache_hit_refunds_hourly_quota() -> None:
    quota = ImageQuota(per_ip_per_hour=1, max_in_flight=4)

    stamp = quota.reserve("1.1.1.1")
    assert stamp is not None
    assert quota.reserve("1.1.1.1") is None

    quota.release("1.1.1.1", stamp, refund=True)

    assert quota.reserve("1.1.1.1") is not None


def test_release_without_refund_keeps_hourly_usage() -> None:
    quota = ImageQuota(per_ip_per_hour=1, max_in_flight=4)

    stamp = quota.reserve("1.1.1.1")
    assert stamp is not None

    quota.release("1.1.1.1", stamp, refund=False)

    assert quota.reserve("1.1.1.1") is None
