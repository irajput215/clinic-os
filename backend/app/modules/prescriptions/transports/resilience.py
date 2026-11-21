"""The FEAT-13 resilience controls, as a wrapper any `DispatchTransport` can sit inside.

`docs/features/13-integration-boundaries/03-design.md`, "Adapter contract":

| Control | Here |
| --- | --- |
| Deadline | `deadline_seconds` from the caller bounds every attempt and every pause between them |
| Retry | At most `max_attempts` (4), full jitter on 1 s, 4 s, 16 s, 64 s; **only** for `NotSent` with a transient class |
| Idempotency | The caller's key is passed unchanged on every attempt |
| Circuit breaker | Opens after `failure_threshold` consecutive failures; refuses with `NotSent("CIRCUIT_OPEN")` until `reset_seconds` pass, then lets one trial through |
| Bulkhead | At most `max_concurrent` calls in flight; the next is refused `NotSent("BULKHEAD_FULL")`, never queued |

## Why an unknown outcome is never retried here

A timeout or an unparsable answer (`ExplicitUnknown`) may mean the prescription **was** created. A
retry would rely on the provider honouring the idempotency key, and Parchment's behaviour there is not
confirmed (D-012 open item 1). So an unknown is returned as it is: the outbox records
`REQUIRES_RECONCILIATION` and reconciliation asks the provider what happened. Only a failure that
provably never reached the provider (`NotSent`) is safe to try again.
"""

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from app.modules.prescriptions.transport import (
    Confirmed,
    DispatchRequest,
    DispatchTransport,
    ExplicitUnknown,
    NotSent,
    Rejected,
    TransportOutcome,
)

# `NotSent` classes worth another attempt: the request never left and the cause may pass.
TRANSIENT_NOT_SENT: Final[frozenset[str]] = frozenset(
    {
        "CONNECTION_REFUSED",
        "CONNECTION_RESET_BEFORE_SEND",
        "DNS_FAILURE",
        "SERVICE_UNAVAILABLE",
    }
)
BACKOFF_SECONDS: Final[tuple[float, ...]] = (1.0, 4.0, 16.0, 64.0)


@dataclass
class _Breaker:
    failure_threshold: int
    reset_seconds: float
    failures: int = 0
    opened_at: float | None = None
    trial_in_flight: bool = False

    def allow(self, now: float) -> bool:
        if self.opened_at is None:
            return True
        if now - self.opened_at < self.reset_seconds or self.trial_in_flight:
            return False
        self.trial_in_flight = True  # half-open: exactly one trial
        return True

    def record(self, outcome: TransportOutcome, now: float) -> None:
        self.trial_in_flight = False
        if isinstance(outcome, Confirmed | Rejected):
            # The provider answered definitively: it is up.
            self.failures, self.opened_at = 0, None
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = now


@dataclass
class ResilientTransport:
    """Wraps `inner` with the deadline, retry, breaker and bulkhead. Thread-safe."""

    inner: DispatchTransport
    max_attempts: int = 4
    failure_threshold: int = 5
    reset_seconds: float = 30.0
    max_concurrent: int = 4
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    jitter: Callable[[], float] = random.random
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _in_flight: int = field(default=0, init=False)
    _breaker: _Breaker = field(init=False)

    def __post_init__(self) -> None:
        self._breaker = _Breaker(self.failure_threshold, self.reset_seconds)

    @property
    def provider(self) -> str:
        return self.inner.provider

    def _enter(self) -> TransportOutcome | None:
        with self._lock:
            if self._in_flight >= self.max_concurrent:
                return NotSent("BULKHEAD_FULL")
            if not self._breaker.allow(self.clock()):
                return NotSent("CIRCUIT_OPEN")
            self._in_flight += 1
            return None

    def _leave(self, outcome: TransportOutcome) -> None:
        with self._lock:
            self._in_flight -= 1
            self._breaker.record(outcome, self.clock())

    def send(
        self, request: DispatchRequest, *, idempotency_key: str, deadline_seconds: float
    ) -> TransportOutcome:
        if not idempotency_key:
            raise ValueError("a send needs an idempotency key")
        refused = self._enter()
        if refused is not None:
            return refused
        outcome: TransportOutcome = NotSent("NOT_ATTEMPTED")
        started = self.clock()
        try:
            for attempt in range(self.max_attempts):
                remaining = deadline_seconds - (self.clock() - started)
                if remaining <= 0:
                    if attempt == 0:
                        outcome = NotSent("DEADLINE_EXCEEDED")
                    break
                outcome = self.inner.send(
                    request, idempotency_key=idempotency_key, deadline_seconds=remaining
                )
                if not (
                    isinstance(outcome, NotSent)
                    and outcome.error_class in TRANSIENT_NOT_SENT
                ):
                    return outcome
                if attempt + 1 == self.max_attempts:
                    break
                pause = (
                    self.jitter()
                    * BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                )
                if self.clock() - started + pause >= deadline_seconds:
                    break
                self.sleep(pause)
            return outcome
        finally:
            self._leave(outcome)

    def lookup(
        self, *, idempotency_key: str, provider_reference: str | None
    ) -> TransportOutcome:
        """Reconciliation reads are not retried here: the next reconciliation run is the retry."""
        refused = self._enter()
        if refused is not None:
            return (
                ExplicitUnknown(refused.error_class)
                if isinstance(refused, NotSent)
                else refused
            )
        outcome: TransportOutcome = ExplicitUnknown("NOT_ATTEMPTED")
        try:
            outcome = self.inner.lookup(
                idempotency_key=idempotency_key, provider_reference=provider_reference
            )
            return outcome
        finally:
            self._leave(outcome)
