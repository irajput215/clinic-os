"""The consent library (docs3 Phase 6 feature 06; manual §12.3): what a patient agreed to, the clinic's
own versions of each consent, and withdrawals.

Three tenant tables, each with the forced RLS pair, all **append-only** for the app role
(`SELECT, INSERT`): consent history is never rewritten.

* `patient_consents` — a patient agreed to one version of one consent: the version label and the
  SHA-256 of the exact text shown. Moved here from the intake module (same table, unchanged).
* `consent_versions` — a version a clinic published from Settings. A clinic with none for a kind
  offers the platform default (`documents.py`). Versions number from 1 per kind; a patient's record
  names a clinic version as `clinic-<n>`.
* `consent_withdrawals` — a patient withdrew a consent: when, how, and who recorded it. A later
  consent of the same kind supersedes it; nothing is deleted.
"""

import uuid
from datetime import UTC, datetime
from typing import Final

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

CONSENT_KINDS: Final[tuple[str, ...]] = ("PRIVACY", "TELEHEALTH", "TREATMENT")
CONSENT_METHODS: Final[tuple[str, ...]] = ("ONLINE_APPLICATION", "IN_CLINIC")
WITHDRAWAL_METHODS: Final[tuple[str, ...]] = ("IN_PERSON", "PHONE", "WRITTEN")
MAX_BODY: Final[int] = 10_000

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PatientConsent(SQLModel, table=True):
    """A patient agreed to one version of one consent (manual §12.3). Append-only."""

    __tablename__ = "patient_consents"
    __table_args__ = (
        sa.CheckConstraint(f"kind IN ({_in(CONSENT_KINDS)})", name="kind"),
        sa.CheckConstraint(
            "method IN ('ONLINE_APPLICATION', 'IN_CLINIC')", name="method"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_patient_consents_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_patient_consents_tenant_patient", "tenant_id", "patient_id"),
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
    kind: str
    version: str = Field(max_length=32)
    text_sha256: str = Field(max_length=64)
    method: str
    signed_at: datetime = Field(sa_type=_TIMESTAMPTZ)
    application_id: uuid.UUID | None = Field(
        default=None, foreign_key="intake_applications.id", ondelete="RESTRICT"
    )
    recorded_by: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class ConsentVersion(SQLModel, table=True):
    """A clinic's own version of one consent. Immutable once published."""

    __tablename__ = "consent_versions"
    __table_args__ = (
        sa.CheckConstraint(f"kind IN ({_in(CONSENT_KINDS)})", name="kind"),
        sa.CheckConstraint("version >= 1", name="version"),
        sa.CheckConstraint("octet_length(body_sha256) = 64", name="body_sha256"),
        sa.CheckConstraint(f"char_length(body) BETWEEN 1 AND {MAX_BODY}", name="body"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_consent_versions_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "kind",
            "version",
            name="uq_consent_versions_tenant_kind_version",
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
    kind: str = Field(max_length=16)
    version: int
    title: str = Field(max_length=200)
    body: str = Field(sa_type=sa.Text)
    body_sha256: str = Field(max_length=64)
    published_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    published_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class ConsentWithdrawal(SQLModel, table=True):
    """A patient withdrew one consent. Append-only; a later consent supersedes it."""

    __tablename__ = "consent_withdrawals"
    __table_args__ = (
        sa.CheckConstraint(f"kind IN ({_in(CONSENT_KINDS)})", name="kind"),
        sa.CheckConstraint(f"method IN ({_in(WITHDRAWAL_METHODS)})", name="method"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_consent_withdrawals_tenant_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_consent_withdrawals_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_consent_withdrawals_tenant_patient", "tenant_id", "patient_id"),
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
    kind: str = Field(max_length=16)
    method: str = Field(max_length=16)
    withdrawn_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    recorded_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
