"""The `prescriptions`, `prescription_events` and `dispatch_attempts` tables.

Design: `docs/features/11-prescribing/03-design.md` (the prescription, its state machine and its
history), `docs/features/10-prescription-safety-gate/03-design.md` (`dispatch_attempts`, the outbox the
gate writes) and `docs/features/13-integration-boundaries/03-design.md` (the five-step sequence: the
intent commits before any external call).

## What is a database control here, not a service convention

- **The state machine** (`LEGAL_TRANSITIONS`) is enforced twice: the service refuses an illegal
  transition with `409 INVALID_STATE_TRANSITION`, and the `trg_prescriptions_lock_signed` trigger the
  migration creates refuses it for every role, including the table owner.
- **`SIGNED` is immutable** (FEAT-11 R5, T-11.2). Once a row leaves `DRAFT`, the clinical payload, the
  signature and the grain are frozen by the same trigger (`SIGNED_IS_IMMUTABLE`). Only `state`,
  `approval_id` (the approval the latest gate decision relied on) and `updated_at` may change.
- **The signer is the prescriber of record** (`ck_prescriptions_signer_is_prescriber`).
- **A signed row carries its evidence** (`ck_prescriptions_signed_evidence`): who, when, the payload
  hash and the approval the gate passed on.
- **One live dispatch per prescription** (`uq_dispatch_attempts_one_live`, a partial unique index):
  two dispatches with different client keys cannot both be queued.
- **The outbox row's identity is immutable** and its outcome moves only forward
  (`trg_dispatch_attempts_guard`).

## Deliberate departures from the documents (recorded in the PR)

- `prescription_events` is the one append-only history table. FEAT-11 names both
  `prescription_events` and `prescription_state_history` with identical columns and records the
  divergence as open; one table serves both purposes and the platform `audit_log` is the control record.
- `schedule8_flag`, `supersedes_id` and `cancel_reason_code` are not created: the medicine catalogue
  that would derive the flag is not sourced (T-11.5 open item), and there is no addendum or cancel
  route. A column that is always `false` would be a false clinical claim.
- `dispatch_attempts.provider` is `NULL` while a row is queued: no transport is configured, so naming a
  provider (the documents default to `PARCHMENT`) would claim an integration that does not exist.
- `triage_outcome` and `conventional_therapy` are not in FEAT-11's column list; they are the docs2
  script-queue requirement R1 and are classified HIGHLY_SENSITIVE like every clinical field here.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.modules.tga_approvals.models import CATEGORY_PATTERN, CODE_PATTERN

# FEAT-11 "The state machine". `QUEUED`/`DISPATCHED` rather than the source's
# `SUBMITTING`/`SUBMITTED`/`CONFIRMED` (FEAT-11 OPEN-1): the gate document's names.
PRESCRIPTION_STATES: Final[tuple[str, ...]] = (
    "DRAFT",
    "SIGNED",
    "BLOCKED",
    "QUEUED",
    "DISPATCHED",
    "FAILED",
    "REQUIRES_RECONCILIATION",
    "CANCELLED",
    "REVERSED",
)

LEGAL_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "DRAFT": frozenset({"SIGNED", "CANCELLED"}),
    "SIGNED": frozenset({"QUEUED", "BLOCKED", "CANCELLED"}),
    "BLOCKED": frozenset({"QUEUED", "CANCELLED"}),
    "QUEUED": frozenset({"DISPATCHED", "FAILED", "REQUIRES_RECONCILIATION"}),
    "FAILED": frozenset({"QUEUED", "CANCELLED"}),
    "REQUIRES_RECONCILIATION": frozenset({"DISPATCHED", "FAILED"}),
    "DISPATCHED": frozenset({"REVERSED"}),
    "CANCELLED": frozenset(),
    "REVERSED": frozenset(),
}

# The outbox row's own vocabulary (FEAT-10 `dispatch_attempts.state`).
ATTEMPT_STATES: Final[tuple[str, ...]] = (
    "QUEUED",
    "DISPATCHED",
    "FAILED",
    "REQUIRES_RECONCILIATION",
)
ATTEMPT_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "QUEUED": frozenset({"DISPATCHED", "FAILED", "REQUIRES_RECONCILIATION"}),
    "REQUIRES_RECONCILIATION": frozenset({"DISPATCHED", "FAILED"}),
    "DISPATCHED": frozenset(),
    "FAILED": frozenset(),
}
OUTCOME_CLASSES: Final[tuple[str, ...]] = ("CONFIRMED", "REJECTED", "UNKNOWN")

# Free text a clinician types: bounded, and no control characters, so it cannot smuggle a line break
# into anything that later renders it. The bound is the schema's as well.
def _text_check(column: str, limit: int) -> str:
    # A length test plus a character-class test: PostgreSQL caps a regex repeat count at 255.
    return f"char_length({column}) BETWEEN 1 AND {limit} AND {column} !~ '[[:cntrl:]]'"


_HEX64 = r"^[0-9a-f]{64}$"
_PROVIDER_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
_REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9/_.:-]{0,127}$"

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_STATE_SQL = _sql_list(PRESCRIPTION_STATES)
_ATTEMPT_STATE_SQL = _sql_list(ATTEMPT_STATES)
_OUTCOME_SQL = _sql_list(OUTCOME_CLASSES)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Prescription(SQLModel, table=True):
    """One prescription: drafted, signed by its prescriber of record, then released by the gate."""

    __tablename__ = "prescriptions"
    __table_args__ = (
        sa.CheckConstraint(f"state IN ({_STATE_SQL})", name="state"),
        sa.CheckConstraint(_text_check("medicine_name", 200), name="medicine_name"),
        sa.CheckConstraint(f"tga_category ~ '{CATEGORY_PATTERN}'", name="tga_category"),
        sa.CheckConstraint(f"dosage_form ~ '{CATEGORY_PATTERN}'", name="dosage_form"),
        sa.CheckConstraint(
            _text_check("dose_instruction", 500), name="dose_instruction"
        ),
        sa.CheckConstraint(_text_check("triage_outcome", 300), name="triage_outcome"),
        sa.CheckConstraint(
            _text_check("conventional_therapy", 300), name="conventional_therapy"
        ),
        sa.CheckConstraint("quantity > 0", name="quantity"),
        sa.CheckConstraint("repeats BETWEEN 0 AND 12", name="repeats"),
        sa.CheckConstraint(
            f"payload_hash IS NULL OR payload_hash ~ '{_HEX64}'", name="payload_hash"
        ),
        sa.CheckConstraint(
            "signed_by IS NULL OR signed_by = prescriber_id",
            name="signer_is_prescriber",
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT', 'CANCELLED') OR (signed_at IS NOT NULL AND signed_by IS NOT NULL"
            " AND payload_hash IS NOT NULL AND approval_id IS NOT NULL)",
            name="signed_evidence",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_prescriptions_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_prescriptions_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["tga_approvals.tenant_id", "tga_approvals.id"],
            name="fk_prescriptions_tenant_approval",
            ondelete="RESTRICT",
        ),
        # The queue's page order, newest first by keyset on `(created_at, id)`.
        sa.Index("ix_prescriptions_tenant_created", "tenant_id", "created_at", "id"),
        sa.Index(
            "ix_prescriptions_tenant_patient_created",
            "tenant_id",
            "patient_id",
            "created_at",
        ),
        sa.Index("ix_prescriptions_tenant_state", "tenant_id", "state"),
        sa.Index("ix_prescriptions_tenant_prescriber", "tenant_id", "prescriber_id"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    patient_id: uuid.UUID = Field(nullable=False)
    prescriber_id: uuid.UUID = Field(nullable=False)
    drafted_by: uuid.UUID = Field(nullable=False)
    medicine_name: str
    tga_category: str
    dosage_form: str
    dose_instruction: str
    quantity: Decimal = Field(sa_type=sa.Numeric(10, 2))
    repeats: int = Field(sa_type=sa.SmallInteger())
    triage_outcome: str
    conventional_therapy: str
    date_of_service: date
    state: str = Field(default="DRAFT")
    approval_id: uuid.UUID | None = None
    payload_hash: str | None = None
    signed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    signed_by: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class PrescriptionEvent(SQLModel, table=True):
    """One transition of one prescription: the append-only clinical history (FEAT-11 R14)."""

    __tablename__ = "prescription_events"
    __table_args__ = (
        sa.CheckConstraint(f"to_state IN ({_STATE_SQL})", name="to_state"),
        sa.CheckConstraint(
            f"from_state IS NULL OR from_state IN ({_STATE_SQL})", name="from_state"
        ),
        sa.CheckConstraint(
            "from_state IS NULL OR from_state <> to_state", name="transition"
        ),
        sa.CheckConstraint(
            f"reason IS NULL OR reason ~ '{CODE_PATTERN}'", name="reason"
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_prescription_events_tenant_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "prescription_id"],
            ["prescriptions.tenant_id", "prescriptions.id"],
            name="fk_prescription_events_tenant_prescription",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_prescription_events_tenant_prescription_occurred",
            "tenant_id",
            "prescription_id",
            "occurred_at",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    prescription_id: uuid.UUID = Field(nullable=False)
    from_state: str | None = None
    to_state: str
    reason: str | None = None
    # `NULL` for the outbox worker, which has no human actor.
    actor_id: uuid.UUID | None = None
    occurred_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class DispatchAttempt(SQLModel, table=True):
    """The transactional outbox: one clinical intent to send one signed prescription.

    Written in the **same transaction** as the `SIGNED/BLOCKED/FAILED -> QUEUED` transition and its
    `prescription.dispatch` audit event, so the intent exists if and only if the gate passed. A
    transport (none is configured) later claims it, sends it with `idempotency_key`, and records the
    outcome; an unknown outcome is `REQUIRES_RECONCILIATION`, never success.
    """

    __tablename__ = "dispatch_attempts"
    __table_args__ = (
        sa.CheckConstraint(f"state IN ({_ATTEMPT_STATE_SQL})", name="state"),
        sa.CheckConstraint(f"idempotency_key ~ '{_HEX64}'", name="idempotency_key"),
        sa.CheckConstraint(
            f"request_payload_hash ~ '{_HEX64}'", name="request_payload_hash"
        ),
        sa.CheckConstraint("attempt_seq >= 1", name="attempt_seq"),
        sa.CheckConstraint(
            f"outcome_class IS NULL OR outcome_class IN ({_OUTCOME_SQL})",
            name="outcome_class",
        ),
        sa.CheckConstraint(
            f"error_class IS NULL OR error_class ~ '{CODE_PATTERN}'", name="error_class"
        ),
        sa.CheckConstraint(
            f"resolution_reason IS NULL OR resolution_reason ~ '{CODE_PATTERN}'",
            name="resolution_reason",
        ),
        sa.CheckConstraint(
            f"provider IS NULL OR provider ~ '{_PROVIDER_PATTERN}'", name="provider"
        ),
        sa.CheckConstraint(
            f"provider_reference IS NULL OR provider_reference ~ '{_REFERENCE_PATTERN}'",
            name="provider_reference",
        ),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_ms"),
        # A row is reported as delivered only with the provider's confirmation behind it.
        sa.CheckConstraint(
            "state <> 'DISPATCHED' OR (outcome_class = 'CONFIRMED'"
            " AND provider IS NOT NULL AND resolved_at IS NOT NULL)",
            name="dispatched_confirmed",
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_dispatch_attempts_tenant_key"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "prescription_id",
            "attempt_seq",
            name="uq_dispatch_attempts_tenant_prescription_seq",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "prescription_id"],
            ["prescriptions.tenant_id", "prescriptions.id"],
            name="fk_dispatch_attempts_tenant_prescription",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["tga_approvals.tenant_id", "tga_approvals.id"],
            name="fk_dispatch_attempts_tenant_approval",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "uq_dispatch_attempts_one_live",
            "tenant_id",
            "prescription_id",
            unique=True,
            postgresql_where=sa.text("state IN ('QUEUED', 'REQUIRES_RECONCILIATION')"),
        ),
        sa.Index(
            "ix_dispatch_attempts_tenant_state_requested",
            "tenant_id",
            "state",
            "requested_at",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    prescription_id: uuid.UUID = Field(nullable=False)
    approval_id: uuid.UUID = Field(nullable=False)
    idempotency_key: str
    attempt_seq: int
    state: str = Field(default="QUEUED")
    provider: str | None = None
    provider_reference: str | None = None
    request_payload_hash: str
    outcome_class: str | None = None
    error_class: str | None = None
    resolution_reason: str | None = None
    latency_ms: int | None = None
    requested_by: uuid.UUID = Field(nullable=False)
    requested_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    # Set when a transport claims the row, **before** it is sent: a row claimed and never resolved
    # is an unknown outcome for reconciliation to resolve, never a candidate to send again.
    claimed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    resolved_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
