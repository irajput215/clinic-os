"""In-process rate limiting for the abuse-prone unauthenticated endpoints.

`docs/reference/build-contract.md` control 10 requires per-endpoint rate limits and a
`429` carrying `Retry-After`. This is the smallest honest implementation: a sliding
window held in process memory.

Two things limit how much it buys, and they are recorded here rather than hidden:

- **It is per instance.** More than one worker or replica means each keeps its own
  window, so the effective limit is multiplied. Move to a shared store when that
  matters.
- **It keys on the address in the ASGI scope.** Behind a proxy that does not rewrite
  it, every request shares one bucket. Uvicorn only trusts `X-Forwarded-For` from
  `--forwarded-allow-ips`, so a deployment behind a load balancer must configure that
  or the limit becomes global rather than per client.

Account lockout (task T1-28) is the control for attacks on one account; this is the
control for volume from one source.
"""

import math
from collections import deque
from collections.abc import Callable
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status

from app.core.config import settings


class SlidingWindowLimiter:
    """Counts hits per key inside a moving window."""

    def __init__(self, *, max_keys: int = 10_000) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._max_keys = max_keys

    def hit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> float | None:
        """Record a hit.

        Returns `None` when the request is allowed, otherwise the whole number of
        seconds a client should wait before retrying.
        """
        moment = monotonic() if now is None else now
        cutoff = moment - window_seconds

        with self._lock:
            timestamps = self._hits.setdefault(key, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= limit:
                wait = timestamps[0] + window_seconds - moment
                return float(max(1, math.ceil(wait)))

            timestamps.append(moment)
            if len(self._hits) > self._max_keys:
                # Bounded memory: a client cycling keys must not grow this forever.
                self._hits.pop(next(iter(self._hits)), None)
            return None

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._hits)


limiter = SlidingWindowLimiter()


def rate_limit(
    *, scope: str, limit: int, window_seconds: int = 60
) -> Callable[[Request], None]:
    """Build a dependency enforcing one limit for one scope."""

    def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        client = request.client.host if request.client else "unknown"
        retry_after = limiter.hit(
            f"{scope}:{client}", limit=limit, window_seconds=window_seconds
        )
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(int(retry_after))},
            )

    return dependency


# Policies. `docs/features/01-tenancy-and-clinics/01-requirements.md` R15 sets the
# administrative class at 20/min; authentication is at least as sensitive, and
# password recovery more so because every attempt can send mail.
login_rate_limit = rate_limit(scope="login", limit=20, window_seconds=60)
password_recovery_rate_limit = rate_limit(scope="password-recovery", limit=5)
