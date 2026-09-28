from __future__ import annotations

import pytest

from orchestwin.api.rate_limit import AttemptLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_key_is_blocked_at_the_limit_until_the_window_expires() -> None:
    clock = FakeClock()
    limiter = AttemptLimiter(limit=3, window_seconds=60, clock=clock)

    limiter.record("owner@example.com")
    limiter.record("owner@example.com")

    assert limiter.retry_after("owner@example.com") is None

    limiter.record("owner@example.com")

    assert limiter.retry_after("owner@example.com") == 60

    clock.now += 59.5

    assert limiter.retry_after("owner@example.com") == 1

    clock.now += 0.5

    assert limiter.retry_after("owner@example.com") is None


def test_window_slides_as_each_attempt_expires() -> None:
    clock = FakeClock()
    limiter = AttemptLimiter(limit=3, window_seconds=60, clock=clock)

    for offset in (0, 30, 40):
        clock.now = 1000 + offset
        limiter.record("client")

    assert limiter.retry_after("client") == 20

    clock.now = 1060

    assert limiter.retry_after("client") is None

    limiter.record("client")

    assert limiter.retry_after("client") == 30


def test_reset_forgets_only_the_given_key() -> None:
    limiter = AttemptLimiter(limit=1, window_seconds=60, clock=FakeClock())

    limiter.record("owner@example.com")
    limiter.record("other@example.com")
    limiter.reset("owner@example.com")
    limiter.reset("missing@example.com")

    assert limiter.retry_after("owner@example.com") is None
    assert limiter.retry_after("other@example.com") == 60


def test_keys_are_counted_independently() -> None:
    limiter = AttemptLimiter(limit=2, window_seconds=60, clock=FakeClock())

    limiter.record("first")
    limiter.record("first")
    limiter.record("second")

    assert limiter.retry_after("first") == 60
    assert limiter.retry_after("second") is None
    assert limiter.retry_after("third") is None


def test_expired_keys_are_purged() -> None:
    clock = FakeClock()
    limiter = AttemptLimiter(limit=5, window_seconds=60, clock=clock)

    for key in ("first", "second", "third"):
        limiter.record(key)

    assert limiter.tracked_keys == 3

    clock.now += 60
    limiter.record("fourth")

    assert limiter.tracked_keys == 1


def test_least_recently_recorded_keys_are_dropped_beyond_the_bound() -> None:
    limiter = AttemptLimiter(limit=1, window_seconds=60, clock=FakeClock(), maximum_keys=2)

    limiter.record("first")
    limiter.record("second")
    limiter.record("first")
    limiter.record("third")

    assert limiter.tracked_keys == 2
    assert limiter.retry_after("second") is None
    assert limiter.retry_after("first") == 60
    assert limiter.retry_after("third") == 60


def test_default_bound_keeps_at_most_ten_thousand_keys() -> None:
    limiter = AttemptLimiter(limit=1, window_seconds=60, clock=FakeClock())

    for index in range(10001):
        limiter.record(f"client-{index}")

    assert limiter.tracked_keys == 10000
    assert limiter.retry_after("client-0") is None
    assert limiter.retry_after("client-1") == 60
    assert limiter.retry_after("client-10000") == 60


@pytest.mark.parametrize(
    ("limit", "window_seconds", "maximum_keys"),
    [(0, 60, 10), (1, 0, 10), (1, 60, 0)],
)
def test_limiter_rejects_invalid_configuration(
    limit: int,
    window_seconds: float,
    maximum_keys: int,
) -> None:
    with pytest.raises(ValueError):
        AttemptLimiter(limit, window_seconds, FakeClock(), maximum_keys=maximum_keys)
