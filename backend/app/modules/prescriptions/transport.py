"""The pharmacy / eRx transport interface - and the honest fact that **no transport exists**.

`docs/features/13-integration-boundaries/03-design.md` "Adapter contract": one interface per provider,
`dispatch(request, idempotency_key, deadline) -> Confirmed | Rejected | ExplicitUnknown | AdapterError`,
a reconciliation lookup by provider reference **and** idempotency key, and a simulated driver for CI
that no production path can select.

## What is missing before a script can actually reach a pharmacy

Nothing in this repository sends a prescription anywhere. `configured_transport()` returns `None`
unconditionally, so every dispatched prescription stays `QUEUED` in the outbox and the API reports it
as queued, never as sent. Building a real transport is a new third-party data flow, which needs, per
FEAT-13 and the vendor register, at minimum:

1. A certified e-prescribing conformant party and its contract (FEAT-10 OPEN-1, FEAT-13 OPEN-2:
   REQUIRES LEGAL/REGULATORY VALIDATION), with residency and sub-processor positions (DR-04).
2. Credentials held in a secret store, referenced by ARN per environment (FEAT-13 R11), with an owner
   and a rotation procedure.
3. An adapter implementing `DispatchTransport` with connect/read timeouts, a 20 s deadline, at most four
   attempts with full jitter for transient failures only, a circuit breaker and a bulkhead (R4, R6).
4. An egress allow-list entry for the provider host (R10) and TLS 1.2+ (R15).
5. The minimum-data payload allow-list for the rail schema (R19) - the request built from a prescription
   is the HIGHLY_SENSITIVE payload, so its field set is a privacy decision, not a code decision.
6. The signed inbound webhook receiver (FEAT-12) for asynchronous confirmations, and a schedule for
   the reconciliation run (FEAT-10 open item: "nightly reconciliation schedule and its environment").
7. A written outage playbook naming the clinical fallback and its owner (FEAT-13 R18).

Only then does `configured_transport()` return an adapter, and only that change - one function - makes
the outbox drain start sending.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

# The user-facing sentence for every queued prescription while no transport exists.
NOT_SENT_MESSAGE = (
    "Queued in ClinicOS. Not sent: no pharmacy or eRx transport is configured."
)


@dataclass(frozen=True)
class DispatchRequest:
    """What a transport receives. Built from the signed row; never logged (HIGHLY_SENSITIVE)."""

    prescription_id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    prescriber_id: uuid.UUID
    approval_id: uuid.UUID
    medicine_name: str
    tga_category: str
    dosage_form: str
    dose_instruction: str
    quantity: Decimal
    repeats: int
    date_of_service: date


@dataclass(frozen=True)
class Confirmed:
    """The provider accepted the prescription and gave its reference."""

    provider_reference: str


@dataclass(frozen=True)
class Rejected:
    """The provider definitively refused it (a 4xx): not delivered, not retried."""

    error_class: str


@dataclass(frozen=True)
class ExplicitUnknown:
    """No trustworthy answer - a timeout or an unparsable body. Never success, never failure."""

    error_class: str


@dataclass(frozen=True)
class NotSent:
    """The request provably never left (connection refused, breaker open): safe to call failed."""

    error_class: str


TransportOutcome = Confirmed | Rejected | ExplicitUnknown | NotSent


class DispatchTransport(Protocol):
    """One provider. Implementations own their timeout, bounded retry and circuit breaker."""

    @property
    def provider(self) -> str:
        """The closed provider code recorded on the outbox row (lower-case, e.g. `parchment`)."""
        ...

    def send(
        self, request: DispatchRequest, *, idempotency_key: str, deadline_seconds: float
    ) -> TransportOutcome:
        """Deliver once under `idempotency_key`; the same key must never deliver twice."""
        ...

    def lookup(
        self, *, idempotency_key: str, provider_reference: str | None
    ) -> TransportOutcome:
        """What the provider knows about this key: `Confirmed`, `Rejected`, or still unknown."""
        ...


def configured_transport() -> DispatchTransport | None:
    """The transport this deployment may use. **Always `None`: none exists** (see the module docstring).

    There is deliberately no setting that turns a transport on: a configuration key that could point
    the outbox at an unvetted endpoint would itself be the unregistered third-party flow FEAT-13 R1
    forbids. The tests reach the drain with a simulated transport passed as an argument instead.
    """
    return None
