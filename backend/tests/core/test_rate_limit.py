"""The sliding-window rate limiter.

The clock is injected through `now` so these tests are deterministic: no sleeping.
"""

from app.core.rate_limit import SlidingWindowLimiter


def test_allows_up_to_the_limit_then_refuses() -> None:
    limiter = SlidingWindowLimiter()

    for _ in range(3):
        assert limiter.hit("key", limit=3, window_seconds=60, now=100.0) is None

    assert limiter.hit("key", limit=3, window_seconds=60, now=100.0) == 60


def test_the_window_slides() -> None:
    limiter = SlidingWindowLimiter()
    for _ in range(3):
        limiter.hit("key", limit=3, window_seconds=60, now=100.0)

    # The first hit falls out of the window at t=160, so t=161 has room again.
    assert limiter.hit("key", limit=3, window_seconds=60, now=161.0) is None


def test_retry_after_counts_down_as_the_window_drains() -> None:
    limiter = SlidingWindowLimiter()
    limiter.hit("key", limit=1, window_seconds=60, now=100.0)

    assert limiter.hit("key", limit=1, window_seconds=60, now=130.0) == 30
    assert limiter.hit("key", limit=1, window_seconds=60, now=159.9) == 1


def test_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter()
    for _ in range(2):
        limiter.hit("first", limit=2, window_seconds=60, now=100.0)

    assert limiter.hit("first", limit=2, window_seconds=60, now=100.0) is not None
    assert limiter.hit("second", limit=2, window_seconds=60, now=100.0) is None


def test_clear_forgets_every_bucket() -> None:
    limiter = SlidingWindowLimiter()
    limiter.hit("key", limit=1, window_seconds=60, now=100.0)

    limiter.clear()

    assert limiter.hit("key", limit=1, window_seconds=60, now=100.0) is None


def test_tracked_keys_are_bounded() -> None:
    """An attacker cycling keys must not grow the dictionary without limit."""
    limiter = SlidingWindowLimiter(max_keys=5)

    for index in range(50):
        limiter.hit(f"key-{index}", limit=1, window_seconds=60, now=100.0)

    assert len(limiter) <= 5
