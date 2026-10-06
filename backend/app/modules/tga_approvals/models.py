"""The `tga_approvals` and `tga_approval_events` tables.

Design: `docs/features/08-tga-approvals/03-design.md` ("Table: `tga_approval`", "RLS", "SQL Grants &
Post-Verification Immutability"). Requirements: `docs/features/08-tga-approvals/01-requirements.md`
R1-R13. Task breakdown: `docs/tasks/02-phase-2-tga-approval-engine.md` T2-1 to T2-6.

## The grain is a clinical contract, and the database enforces it

Grain = `tenant_id + patient_id + tga_category + dosage_form + validity window`. The two properties
that decide whether a prescription may be dispensed are enforced by the database, not by the service:

1. **One live approval per grain.** `no_overlapping_active_approvals` is a *partial* `EXCLUDE USING
   gist` over `(tenant_id, patient_id, tga_category, dosage_form, validity_interval) WHERE state =
   'ACTIVE'` — decision D-006 §1, and the Gate 2 check *"the approval grain is enforced by a GiST
   exclusion constraint on overlapping active intervals"*. Partial is what makes it compatible with
   the supersede chain doc 08 §4 contradicts itself about: a `SUPERSEDED` row never collides with its
   replacement.
2. **At most two years of validity.** `ck_tga_approvals_max_duration` (R3).

`btree_gist` is required: the constraint mixes the equality operators with the range-overlap operator,
and the equality operators are B-tree by default.

## The `EXCLUDE` constraint is declared to `SQLModel.metadata` as an `Index` of the same name

`CREATE TABLE ... EXCLUDE` creates a GiST index named after the constraint, and PostgreSQL reports
that index to every reflection API — it is **not** a check, unique, primary-key or foreign-key
constraint, so `sqlalchemy.inspect` lists it under `get_indexes()`. Measured, not assumed (SQLAlchemy
2.0 / PostgreSQL 18: `duplicates_constraint` is set, `get_unique_constraints` omits it).

Two repository checks read that reflection, and each fails in one direction:

* `tests/core/test_schema_conventions.py` compares every declared constraint/index name against the
  live database **both ways** — so the name must appear exactly once on each side;
* `alembic check` compares the tables the models describe against the database.

Declaring the constraint as `postgresql.ExcludeConstraint` would put its name in the *constraint* set
the model declares and in the *index* set the database reports, and the test would fail on the
mismatch. Declaring nothing would leave the database reporting an index the models do not know about,
and the same test would fail the other way. Declaring a same-named `Index` whose predicate and access
method match the constraint's is therefore the only description that keeps both checks honest, and the
real exclusion semantics are created by the migration (`tga_approval_grain_exclusion`), which is the
only layer that can express `EXCLUDE`. The migration and this declaration are asserted to agree by
`tests/tga/test_constraints.py` and by `tests/core/test_schema_conventions.py`.

## Immutability and the state machine are database controls, not service conventions

Two `BEFORE` triggers, created by the migration:

* `trg_tga_approval_validity_interval` — the `validity_interval` the exclusion constraint indexes is
  **derived** from `(valid_from, valid_to)` on every insert and update, so it cannot drift from the
  dates it is supposed to represent. Deriving it in the database rather than in Python is what makes
  the "dates changed but the interval did not" bug unrepresentable.
* `trg_tga_approval_lock_verified` — once a row is `ACTIVE`, the core grain, the validity dates and the
  provenance are immutable (`VERIFIED_APPROVAL_IMMUTABLE`, design §2 / F10 / S12d), the terminal
  states are immutable outright, and a state change outside the legal table is refused
  (`ILLEGAL_STATE_TRANSITION`). The service refuses the same transitions with `409` first; this is the
  last line of defence, and the one that still holds if a future caller bypasses the service.

## Naming

The lead's task and the phase task list (`docs/tasks/02-phase-2-tga-approval-engine.md` T2-1)
name these tables `tga_approvals` and `tga_approval_events`;
`docs/features/08-tga-approvals/03-design.md` names the table `tga_approval` (singular) while its own
grant list and the test plan name `tga_approval_events` (plural). Both cannot hold. The phase task
list and the task board are followed — plural — and the divergence is recorded in the PR body rather
than hidden.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import DATERANGE
from sqlmodel import Field, SQLModel

# The controlled state vocabulary (R4). `PENDING -> ACTIVE -> SUPERSEDED | EXPIRED | REVOKED`, with
# `PENDING -> REJECTED | REVOKED` as the refusal path a verifier takes when the source document does
# not support the entry. `REJECTED`, `SUPERSEDED`, `EXPIRED` and `REVOKED` are terminal.
APPROVAL_STATES: Final[tuple[str, ...]] = (
    "PENDING",
    "ACTIVE",
    "EXPIRED",
    "REJECTED",
    "REVOKED",
    "SUPERSEDED",
)

# The transitions the state machine permits. The service reads this map, the `BEFORE UPDATE` trigger
# enforces the same map in SQL, and a test asserts the two agree — so the machine has one definition
# per layer and no third, drifting copy.
LEGAL_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "PENDING": frozenset({"ACTIVE", "REJECTED", "REVOKED"}),
    "ACTIVE": frozenset({"SUPERSEDED", "EXPIRED", "REVOKED"}),
    "EXPIRED": frozenset(),
    "REJECTED": frozenset(),
    "REVOKED": frozenset(),
    "SUPERSEDED": frozenset(),
}

# How an approval came to exist. Only `MANUAL_ENTRY` is reachable today: the TGA inbox (task T2-17
# onwards, a later slice) is the other producer, and the closed set is declared at its full width now
# so that slice extends a vocabulary rather than altering a check constraint on a live table.
APPROVAL_SOURCES: Final[tuple[str, ...]] = ("MANUAL_ENTRY", "INBOX_EXTRACTION")

# The state vocabulary as one SQL literal list, so the check constraint and the Python tuple above
# cannot drift.
_STATE_SQL = ", ".join(f"'{state}'" for state in APPROVAL_STATES)
_SOURCE_SQL = ", ".join(f"'{source}'" for source in APPROVAL_SOURCES)

# The `validity_interval` the exclusion constraint indexes, derived from the dates by the
# `trg_tga_approval_validity_interval` trigger. `[)` is D-006 §2's interim fail-safe boundary, and it
# is the same boundary `within_validity_window()` applies in Python (see `service.py`).
VALIDITY_INTERVAL_SQL: Final[str] = "daterange(valid_from, valid_to, '[)')"

# PROVISIONAL — the same situation `patients.sex_at_birth` records. `03-design.md` says `category` and
# `dosage_form` come from a "controlled list" and does not enumerate it, and no source document in the
# repository does either. Inventing a clinical vocabulary in code is not this change's decision, so
# the database enforces the *shape* a controlled token has (bounded, uppercase, no free text — which
# is also what keeps free-text PHI out of a HIGHLY_SENSITIVE column) and the enumeration is recorded
# as open for the Clinical Safety Officer in the PR.
CATEGORY_PATTERN = r"^[A-Z0-9][A-Z0-9_]{0,31}$"
# The same shape for the dosage form, named separately so the two can diverge when the Clinical
# Safety Officer specifies them, without a rename rippling through the schemas.
DOSAGE_FORM_PATTERN = CATEGORY_PATTERN
# A regulator reference as entered: bounded, no control characters, no newlines (a free-text field
# here would be an INV-5 hazard, because references reach log lines and error bodies elsewhere).
REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9/_. -]{0,63}$"
# A reason **code**, never free text: `03-design.md` fixes that for `revoked_reason_code`, and the
# same rule is applied to the manual-entry reason so neither column can hold clinical narrative.
CODE_PATTERN = r"^[A-Z][A-Z0-9_]{0,63}$"

# The two years R3 allows. The SQL and the Python schema validation are the same rule expressed twice,
# on purpose: the schema answers R3's `422 ERR_WINDOW_EXCEEDS_MAX_DURATION` without touching the
# database, and the check constraint refuses the row if anything ever bypasses the schema. Both clamp
# a leap day the way PostgreSQL's interval does (2024-02-29 + 2 years = 2026-02-28), so the two agree
# on the boundary rather than on the easy cases only.
MAX_DURATION_YEARS: Final[int] = 2
MAX_DURATION_SQL: Final[str] = f"(valid_from + interval '{MAX_DURATION_YEARS} years')::date"

# A shared TypeEngine instance: types are immutable, and `sa_column` wants an instance.
_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TgaApproval(SQLModel, table=True):
    """One TGA approval: patient, category, dosage form and the window it authorises."""

    __tablename__ = "tga_approvals"
    __table_args__ = (
        # R3 — the maximum validity window. Enforced here *and* in the service: the service answers
        # `422 ERR_WINDOW_EXCEEDS_MAX_DURATION` with a field error, and this refuses the row if the
        # service is ever bypassed.
        sa.CheckConstraint(
            f"valid_to <= {MAX_DURATION_SQL}", name="max_duration"
        ),
        # The window runs forwards. A zero-length or reversed window is not an approval.
        sa.CheckConstraint("valid_to > valid_from", name="window"),
        # R4 — the controlled state vocabulary.
        sa.CheckConstraint(f"state IN ({_STATE_SQL})", name="state"),
        sa.CheckConstraint(f"source IN ({_SOURCE_SQL})", name="source"),
        # HIGHLY_SENSITIVE shape, not a clinical vocabulary: see the module docstring.
        sa.CheckConstraint(
            f"tga_category ~ '{CATEGORY_PATTERN}'", name="tga_category"
        ),
        sa.CheckConstraint(
            f"dosage_form ~ '{CATEGORY_PATTERN}'", name="dosage_form"
        ),
        sa.CheckConstraint(
            f"approval_reference ~ '{REFERENCE_PATTERN}'", name="approval_reference"
        ),
        sa.CheckConstraint(
            f"creation_reason ~ '{CODE_PATTERN}'", name="creation_reason"
        ),
        sa.CheckConstraint(
            f"revoked_reason_code IS NULL OR revoked_reason_code ~ '{CODE_PATTERN}'",
            name="revoked_reason_code",
        ),
        # The interval the exclusion constraint indexes is derived from the dates, so a row cannot
        # claim a window its own dates do not describe. The trigger keeps it true; this check makes
        # the invariant readable in the schema and survives a trigger being disabled.
        sa.CheckConstraint(
            f"validity_interval = {VALIDITY_INTERVAL_SQL}",
            name="validity_interval",
        ),
        # T2-4: an `ACTIVE` row is one a clinician verified, so it must carry the verification.
        sa.CheckConstraint(
            "state <> 'ACTIVE' OR verified_at IS NOT NULL", name="active_verified"
        ),
        # T2-4: a revocation carries its reason code.
        sa.CheckConstraint(
            "state <> 'REVOKED' OR revoked_reason_code IS NOT NULL",
            name="revoked_reason",
        ),
        # T2-9: the supersede chain is reconstructible, so a `SUPERSEDED` row always names the grant
        # that replaced it.
        sa.CheckConstraint(
            "state <> 'SUPERSEDED' OR superseded_by_id IS NOT NULL",
            name="superseded_link",
        ),
        # T2-10 four-eyes, at the database — the control T-04.10 asks for by name.
        sa.CheckConstraint(
            "verified_by IS NULL OR verified_by <> created_by", name="four_eyes"
        ),
        # Child tables (and future ones) carry a tenant-bound foreign key.
        sa.UniqueConstraint("tenant_id", "id", name="uq_tga_approvals_tenant_id_id"),
        # The composite key that makes the patient link tenant-safe: a row can only reference a
        # patient of its **own** tenant, so a cross-tenant patient link is refused by the database
        # rather than by a service check somebody can forget.
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_tga_approvals_tenant_patient",
            ondelete="RESTRICT",
        ),
        # The approval of a later date may name the grant it replaces, so the chain is walkable in
        # both directions (`supersedes_id` forward, `superseded_by_id` back).
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["tga_approvals.id"],
            name="fk_tga_approvals_supersedes_id_tga_approvals",
            ondelete="RESTRICT",
        ),
        # D-006 §1 / T2-3 / Gate 2: the GiST backing index of the partial EXCLUDE constraint the
        # migration creates. See the module docstring for why it is declared as an index.
        sa.Index(
            "no_overlapping_active_approvals",
            "tenant_id",
            "patient_id",
            "tga_category",
            "dosage_form",
            "validity_interval",
            unique=False,
            postgresql_using="gist",
            postgresql_where=sa.text("state = 'ACTIVE'"),
        ),
        # T2-6. `tenant_id` leads every index.
        sa.Index(
            "ix_tga_approvals_tenant_patient_state",
            "tenant_id",
            "patient_id",
            "state",
        ),
        sa.Index(
            "ix_tga_approvals_tenant_state_valid_to",
            "tenant_id",
            "state",
            "valid_to",
        ),
        # The read path's page order: newest first, per patient, keyset on `(created_at, id)`.
        # Plain ASC columns rather than `created_at DESC, id DESC` expressions: the read path scans
        # this index backwards to get newest-first, and a plain column list is what reflection and
        # `alembic check` compare exactly. An expression index here would be skipped by the
        # comparator and could drift from the database without any check noticing.
        sa.Index(
            "ix_tga_approvals_tenant_patient_created",
            "tenant_id",
            "patient_id",
            "created_at",
            "id",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    # RESTRICT: an approval is clinical and regulatory history, so removing the organisation that owns
    # it must fail loudly rather than destroy or orphan it.
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    patient_id: uuid.UUID = Field(nullable=False)
    tga_category: str
    dosage_form: str
    approval_reference: str
    valid_from: date
    valid_to: date
    # Derived by trigger from the dates above; never written by the application. The exclusion
    # constraint indexes this column, which is why it exists at all.
    validity_interval: Any = Field(
        default=None, sa_column=sa.Column(DATERANGE, nullable=False)
    )
    state: str = Field(default="PENDING")
    source: str = Field(default="MANUAL_ENTRY")
    creation_reason: str
    # PROVISIONAL, like `patients.medicare_number`: the private document store key is
    # SENSITIVE and the store itself is a later slice (T2-20), so nothing writes this yet and no URL
    # or filename is ever stored.
    source_document_id: uuid.UUID | None = None
    created_by: uuid.UUID = Field(nullable=False)
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    revoked_by: uuid.UUID | None = None
    revoked_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    revoked_reason_code: str | None = None
    superseded_by_id: uuid.UUID | None = None
    supersedes_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class TgaApprovalEvent(SQLModel, table=True):
    """One state transition of one approval — the append-only clinical history.

    Design §"Post-Verification Immutability Guard": *"each must be accompanied by an append-only event
    row in `tga_approval_events` in the same transaction"*. The app role holds `SELECT, INSERT` and
    nothing else, so the history cannot be rewritten even by the application that wrote it (T2-5).

    It is deliberately **not** a copy of `audit_log`: `audit_log` is the platform's hash-chained
    control record (`app.modules.audit.service`), and this table is the clinical reconstruction of one
    approval's lifecycle, in the domain's own vocabulary (`from_state`, `to_state`). Both are written
    on the same transaction for every transition, and neither is derived from the other.
    """

    __tablename__ = "tga_approval_events"
    __table_args__ = (
        sa.CheckConstraint(f"to_state IN ({_STATE_SQL})", name="to_state"),
        sa.CheckConstraint(
            f"from_state IS NULL OR from_state IN ({_STATE_SQL})", name="from_state"
        ),
        # A "transition" to the state it is already in is not a transition; the service refuses it and
        # the database will not store one.
        sa.CheckConstraint(
            "from_state IS NULL OR from_state <> to_state", name="transition"
        ),
        sa.CheckConstraint(f"source IN ({_SOURCE_SQL})", name="source"),
        sa.CheckConstraint(
            f"reason IS NULL OR reason ~ '{CODE_PATTERN}'", name="reason"
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tga_approval_events_tenant_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["tga_approvals.tenant_id", "tga_approvals.id"],
            name="fk_tga_approval_events_tenant_approval",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_tga_approval_events_tenant_approval_occurred",
            "tenant_id",
            "approval_id",
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
    approval_id: uuid.UUID = Field(nullable=False)
    # `NULL` for the creation event: nothing preceded it.
    from_state: str | None = None
    to_state: str
    # The reason **code** the transition was taken under, never free text.
    reason: str | None = None
    # `NULL` for a system transition (the expiry sweep), which has no human actor.
    actor_id: uuid.UUID | None = None
    source: str = Field(default="MANUAL_ENTRY")
    occurred_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
