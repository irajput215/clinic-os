"""The `patients` table — the first tenant-scoped table.

Design: `docs/features/05-patients/03-design.md`, "Table: patients". Requirements:
`docs/features/05-patients/01-requirements.md`.

This is the table that makes INV-1 testable. Everything before it was global (`tenants`) or a link
that nothing enforced (`users.tenant_id`); this one carries a **forced** row-level security policy, so
"tenant identity is resolved, never supplied" stops being a statement in a document and becomes
something a test can fail. The policy is created by the migration, not by this model — a model cannot
express `CREATE POLICY`, and `SQLModel.metadata.create_all` would otherwise produce a table that looks
right and enforces nothing.

Two deliberate divergences from the design, both recorded in `docs/progress.md` §4:

- Index names use the repository's `ix_` prefix rather than the design's `idx_`, because
  [`core/metadata.py`](../../core/metadata.py) is the one place index naming is decided. The design's
  substance — `tenant_id` leading on every index — is kept exactly.
- The closed set for `sex_at_birth` is **provisional**. The design requires a closed-set check but does
  not enumerate the values, so this is an engineering choice awaiting the Clinical Safety Officer
  rather than a clinical decision made in code.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Final

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

# PROVISIONAL — see the module docstring. The design says "closed-set check constraint" and stops
# there; these values need the Clinical Safety Officer's confirmation before the pilot.
SEX_AT_BIRTH_VOCABULARY: Final[tuple[str, ...]] = (
    "FEMALE",
    "MALE",
    "INTERSEX",
    "UNKNOWN",
)


# The patient lifecycle (Platform Manual §3.2): exactly one at a time, colour-coded the same everywhere.
# `CLAIMANT` marks a WorkCover/insurer-funded patient; `BLOCKED` stops new bookings and scripts;
# `ARCHIVED` and `DISCHARGED` keep the record but leave the active lists. Nothing is hard-deleted.
PATIENT_STATUSES: Final[tuple[str, ...]] = (
    "CURRENT",
    "REVIEW",
    "WAITING_LIST",
    "CLAIMANT",
    "ARCHIVED",
    "DISCHARGED",
    "BLOCKED",
    "DECEASED",
)
# Hidden from the patient list unless asked for; search still finds them.
INACTIVE_STATUSES: Final[frozenset[str]] = frozenset(
    {"ARCHIVED", "DISCHARGED", "DECEASED"}
)
# A change to one of these needs a reason (the manual: "The reason is recorded").
STATUSES_NEEDING_A_REASON: Final[frozenset[str]] = frozenset(
    {"BLOCKED", "ARCHIVED", "DISCHARGED"}
)
ALERT_TONES: Final[tuple[str, ...]] = ("INFO", "WARN", "DANGER")
DEFAULT_TIMEZONE: Final = "Australia/Sydney"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# A shared TypeEngine instance: types are immutable, and `sa_type` wants an instance or a class,
# not a factory.
_TIMESTAMPTZ = sa.DateTime(timezone=True)


class Patient(SQLModel, table=True):
    __tablename__ = "patients"
    __table_args__ = (
        sa.CheckConstraint(
            "sex_at_birth IN ('FEMALE', 'MALE', 'INTERSEX', 'UNKNOWN')",
            name="sex_at_birth",
        ),
        sa.CheckConstraint(f"status IN ({_in(PATIENT_STATUSES)})", name="status"),
        sa.CheckConstraint("medicare_irn BETWEEN 1 AND 9", name="medicare_irn"),
        # Named explicitly rather than relying on the convention: the convention keys the unique
        # constraint on the first column alone, which would collide with the primary key name.
        sa.UniqueConstraint("tenant_id", "id", name="uq_patients_tenant_id_id"),
        # `tenant_id` leads every index (design, "Indexes (tenant_id leading)"). The plain
        # single-column index the design does not ask for is deliberately absent: the composite
        # indexes below already serve a tenant-scoped scan.
        sa.Index(
            "ix_patients_tenant_family_name", "tenant_id", "family_name", "given_name"
        ),
        sa.Index("ix_patients_tenant_dob", "tenant_id", "date_of_birth"),
        sa.Index(
            "ix_patients_tenant_medicare_blind_index",
            "tenant_id",
            "medicare_blind_index",
        ),
        sa.Index("ix_patients_tenant_ihi_blind_index", "tenant_id", "ihi_blind_index"),
        sa.Index(
            "ix_patients_tenant_active",
            "tenant_id",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    # RESTRICT, not CASCADE or SET NULL: a patient record is clinical history, so removing the
    # organisation that owns it must fail loudly rather than destroy or orphan it. This is the
    # `RESTRICT for clinical records` rule in docs/reference/database-conventions.md.
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    given_name: str
    family_name: str
    preferred_name: str | None = None
    date_of_birth: date
    sex_at_birth: str | None = None
    gender_identity: str | None = None
    # Encrypted at the application boundary with a keyed blind index for exact match. The columns are
    # bytea so the database never holds a searchable plaintext identifier; the key custody decision is
    # OPEN (design, "Blind-index key custody and rotation"), so no value is written yet.
    medicare_number: bytes | None = None
    medicare_blind_index: bytes | None = None
    ihi: bytes | None = None
    ihi_blind_index: bytes | None = None
    address_line: str | None = None
    suburb: str | None = None
    state: str | None = None
    postcode: str | None = None
    phone: str | None = None
    email: str | None = None
    deceased_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    # Self-FK: a merge links the losing record to the survivor and never hard-deletes it
    # (requirement R10/R11). RESTRICT for the same reason as `tenant_id`.
    merged_into_patient_id: uuid.UUID | None = Field(
        default=None, foreign_key="patients.id", ondelete="RESTRICT"
    )
    deleted_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    # Manual §3.2 and §3.4 (docs3 feature 04).
    status: str = Field(
        default="CURRENT", sa_column_kwargs={"server_default": "CURRENT"}
    )
    status_reason: str | None = Field(default=None, max_length=500)
    status_changed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    medicare_irn: int | None = Field(default=None, sa_type=sa.SmallInteger)
    # Off only for an explicit opt-out: it silences reminders and campaigns, never transactional mail.
    receives_communications: bool = Field(
        default=True, sa_column_kwargs={"server_default": sa.true()}
    )
    timezone: str = Field(
        default=DEFAULT_TIMEZONE,
        max_length=64,
        sa_column_kwargs={"server_default": DEFAULT_TIMEZONE},
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class PatientAlert(SQLModel, table=True):
    """A short chip on the patient's header ("payment plan", "interpreter needed"), with a tone.

    Removed, never deleted: `removed_at` hides it and keeps who added and removed it.
    """

    __tablename__ = "patient_alerts"
    __table_args__ = (
        sa.CheckConstraint(f"tone IN ({_in(ALERT_TONES)})", name="tone"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_patient_alerts_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_patient_alerts_tenant_patient", "tenant_id", "patient_id"),
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
    text: str = Field(max_length=120)
    tone: str = Field(default="INFO")
    created_by: uuid.UUID = Field(nullable=False)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    removed_by: uuid.UUID | None = None
    removed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)


class PatientEmergencyContact(SQLModel, table=True):
    """Someone to call for this patient. Removed, never deleted."""

    __tablename__ = "patient_emergency_contacts"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_patient_emergency_contacts_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_patient_emergency_contacts_tenant_patient", "tenant_id", "patient_id"
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
    patient_id: uuid.UUID = Field(nullable=False)
    name: str = Field(max_length=255)
    relationship: str = Field(max_length=100)
    phone: str = Field(max_length=64)
    created_by: uuid.UUID = Field(nullable=False)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    removed_by: uuid.UUID | None = None
    removed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)


# The patient search indexes (`POST /api/v1/patients/search`). Search is a case-insensitive
# **prefix** match on the three plaintext name columns the design names as search keys
# (`03-design.md`, "Field-level encryption decision"), so each index is `lower(<column>)` with
# `text_pattern_ops`: that operator class is what lets `lower(col) LIKE 'smi%'` become an index range
# under a non-`C` collation. `tenant_id` leads, as on every index of this table. Declared after the
# class because an expression index needs the column objects. Measured, not assumed: on a seeded
# table of 200,000 patients in one tenant a selective name search fell from 228 ms (a filter over the
# tenant's whole `ix_patients_tenant_family_name` range) to 0.2 ms (a `BitmapOr` of these indexes);
# the plans are recorded in the migration that creates them.
_patients_table = Patient.metadata.tables["patients"]
for _column in ("family_name", "given_name", "preferred_name"):
    sa.Index(
        f"ix_patients_tenant_{_column}_lower",
        _patients_table.c.tenant_id,
        sa.func.lower(_patients_table.c[_column]).label(f"{_column}_lower"),
        postgresql_ops={f"{_column}_lower": "text_pattern_ops"},
    )
