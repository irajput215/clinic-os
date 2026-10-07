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
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )


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
