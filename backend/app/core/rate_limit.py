"""In-process rate limiting for the abuse-prone unauthenticated endpoints.

`docs/reference/build-contract.md` control 10 requires per-endpoint rate limits and a
`429` carrying `Retry-After`. This is the smallest honest implementation: a sliding
window held in process memory.

Two things limit how much it buys, and they are recorded here rather than hidden:

- **It is per instance.** More than one worker or replica means each keeps its own
  window, so the effective limit is multiplied. Move to a shared store when that
  matters.
- **Without a session it keys on the address in the ASGI scope.** A request whose bearer
  token verifies spends its session's budget (`client_key`); every other request spends its
  address's. Behind a proxy that does not rewrite the address, every unauthenticated request
  shares one bucket. Uvicorn only trusts `X-Forwarded-For` from `--forwarded-allow-ips`, so a
  deployment behind a load balancer must configure that or the unauthenticated limit becomes
  global rather than per client.

Account lockout (task T1-28) is the control for attacks on one account; this is the
control for volume from one source.
"""

import math
from collections import deque
from collections.abc import Callable
from threading import Lock
from time import monotonic

import jwt
from fastapi import HTTPException, Request, status
from jwt.exceptions import InvalidTokenError

from app.core import security
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


def client_key(request: Request) -> str:
    """Whose budget this request spends: its session's, else its address's.

    The design limits per session (`03-users-and-roles/04-threat-model.md` T-03.11,
    `01-tenancy-and-clinics/04-threat-model.md` T-TEN-10), so a bearer token that verifies keys the
    budget on its subject: staff behind one clinic address do not share one administrator's budget.
    Anything that does not verify - no token, a forged one, an expired one - keys on the address, so
    rotating junk tokens buys nothing and an unauthenticated flood is bounded per client as before.
    Verifying is the same HMAC check `app.api.deps.get_current_user` makes next; the limiter decides
    nothing beyond which bucket to count in, and authentication still runs after it.
    """
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
            )
        except InvalidTokenError:
            payload = {}
        subject = payload.get("sub")
        if isinstance(subject, str) and subject:
            return f"session:{subject}"
    return f"address:{request.client.host if request.client else 'unknown'}"


def rate_limit(
    *, scope: str, limit: int, window_seconds: int = 60
) -> Callable[[Request], None]:
    """Build a dependency enforcing one limit for one scope."""

    def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        retry_after = limiter.hit(
            f"{scope}:{client_key(request)}", limit=limit, window_seconds=window_seconds
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
# One window for the whole recovery flow: `POST /password-recovery/{email}` and
# `POST /reset-password/` share the `password-recovery` scope, so 5/min caps the flow rather than
# each step of it. Spending a reset token is the step that grants a session, so it is limited too.
password_recovery_rate_limit = rate_limit(scope="password-recovery", limit=5)
# The administrative class: users, roles and permission grants. 20/min per session is the value in
# `docs/features/03-users-and-roles/04-threat-model.md` T-03.11 (see `client_key`).
admin_rate_limit = rate_limit(scope="admin", limit=20, window_seconds=60)
# The single-resource read class: 300/min, the value `docs/features/01-tenancy-and-clinics/
# 01-requirements.md` R15 and `06-clinical-records/04-threat-model.md` T-CLIN-13 give for one
# resource read by id. A read of the caller's own tenant is one of these, not administration: the app
# shell asks for it on every page load, and in the administrative class it spent the budget an
# administrator needs for the administration screen itself.
read_rate_limit = rate_limit(scope="read", limit=300, window_seconds=60)
# Organisation signup. Unauthenticated, and every success creates a tenant, so it is limited like
# login (20/min): the explicit "already exists" answer is a deliberate usability trade (the form says
# which field to fix), and this limit is what bounds how fast that answer can be harvested.
signup_rate_limit = rate_limit(scope="signup", limit=20, window_seconds=60)
# Patient search (`POST /api/v1/patients/search`). An interim value: the threat model leaves "Rate-limit
# values for the search and duplicate-candidate routes" open (`docs/features/05-patients/
# 04-threat-model.md`, T-05.1 and T-05.13). 120/min per session lets the top-bar quick-find search as a
# clinician types (debounced) while bounding a scripted sweep of the tenant's names, which is the
# scraping threat the limit exists for.
patient_search_rate_limit = rate_limit(
    scope="patient-search", limit=120, window_seconds=60
)
