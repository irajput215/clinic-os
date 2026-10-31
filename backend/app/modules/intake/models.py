"""Patient intake: the public application, its consents, and the pharmacy directory.

docs3 feature 03 (Platform Manual §5.1, §5.4, §8.1, §12.3). Three tenant tables, each with the forced
permissive + restrictive RLS pair every tenant table carries (created by the migration):

- `pharmacies` - the clinic's directory: partners offered on the public page, and patients' own.
- `intake_applications` - one public application: the answers, the flags the server computed, the
  signed declaration, and the staff decision. The answers are HIGHLY_SENSITIVE: never logged, never
  audited, read only through the queue and the doctor's briefing.
- `patient_consents` - which version of each consent a patient agreed to, when and how. Append-only.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

APPLICATION_STATUSES: Final[tuple[str, ...]] = ("SUBMITTED", "ACCEPTED", "REJECTED")
CONSENT_KINDS: Final[tuple[str, ...]] = ("PRIVACY", "TELEHEALTH", "TREATMENT")
REJECT_REASONS: Final[tuple[str, ...]] = (
    "NOT_ELIGIBLE",
    "NEEDS_IN_PERSON_REVIEW",
    "DUPLICATE",
    "INCOMPLETE",
    "OTHER",
)

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Pharmacy(SQLModel, table=True):
    """A pharmacy in the clinic's directory (manual §8.1). Partners are offered on the public page."""

    __tablename__ = "pharmacies"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "id", name="uq_pharmacies_tenant_id_id"),
        sa.CheckConstraint(
            "created_from IN ('STAFF', 'APPLICATION')", name="created_from"
        ),
        sa.Index("ix_pharmacies_tenant_name", "tenant_id", "name"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    name: str = Field(max_length=255)
    suburb: str = Field(max_length=255)
    address: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    provider_number: str | None = Field(default=None, max_length=32)
    is_partner: bool = Field(
        default=False, sa_column_kwargs={"server_default": sa.false()}
    )
    created_from: str = Field(default="STAFF")
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class IntakeApplication(SQLModel, table=True):
    """One public application (manual §5.1) and the clinic's decision on it (§5.4)."""

    __tablename__ = "intake_applications"
    __table_args__ = (
        sa.CheckConstraint(f"status IN ({_in(APPLICATION_STATUSES)})", name="status"),
        sa.CheckConstraint(
            f"decision_reason_code IS NULL OR decision_reason_code IN ({_in(REJECT_REASONS)})",
            name="decision_reason_code",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_intake_applications_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "appointment_id"],
            ["appointments.tenant_id", "appointments.id"],
            name="fk_intake_applications_tenant_appointment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pharmacy_id"],
            ["pharmacies.tenant_id", "pharmacies.id"],
            name="fk_intake_applications_tenant_pharmacy",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_intake_applications_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        sa.Index("ix_intake_applications_tenant_patient", "tenant_id", "patient_id"),
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
    appointment_id: uuid.UUID | None = None
    # Whether this application created the patient record (a matched record is never changed by a
    # public form, so accepting only fills details into a record it created).
    created_patient: bool = Field(default=False)
    status: str = Field(default="SUBMITTED")
    answers: dict[str, Any] = Field(sa_column=sa.Column(JSONB, nullable=False))
    flags: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
    )
    consents: list[dict[str, str]] = Field(sa_column=sa.Column(JSONB, nullable=False))
    pharmacy_id: uuid.UUID | None = None
    own_pharmacy: dict[str, Any] | None = Field(
        default=None, sa_column=sa.Column(JSONB, nullable=True)
    )
    declaration_name: str = Field(max_length=255)
    declared_at: datetime = Field(sa_type=_TIMESTAMPTZ)
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    decision_reason_code: str | None = None
    decision_note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


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
