"""Questionnaire responses and the safety flags they raise (docs3 Phase 6, feature 05).

Two tenant tables, each with the forced RLS pair (the migration creates the policies):

* `form_responses` — one completed instrument for one patient. **Append-only**: the app role holds
  `SELECT, INSERT` and nothing else. A correction is a new row whose `corrects_id` names the one it
  replaces; the original stays, as every clinical record does here.
* `safety_flags` — raised by a response, in the same transaction. Only the acknowledgement columns
  may change (`acknowledged_by`, `acknowledged_at`, `action_code`, `status`), by column grant.

## What is encrypted

The answers (and the unscored difficulty answer) are clinical information, stored as AES-GCM
ciphertext through `app.core.field_crypto`, bound to the tenant. The total and the band are kept in
plaintext so a patient's history can be listed without decrypting every answer; they are still
clinical information, read only under `clinical_record:read` and never logged or audited.

Instrument definitions are not a table: they are versioned in code (`instruments.py`), and a response
records the code and version it was answered on.
"""

import uuid
from datetime import UTC, datetime
from typing import Final

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.modules.forms.instruments import ACKNOWLEDGE_ACTIONS, FLAG_RULES, INSTRUMENTS


def _sql_list(values: list[str] | tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


INSTRUMENT_CODES: Final[tuple[str, ...]] = tuple(INSTRUMENTS)
FLAG_RULE_CODES: Final[tuple[str, ...]] = tuple(rule.code for rule in FLAG_RULES)
ACTION_CODES: Final[tuple[str, ...]] = tuple(ACKNOWLEDGE_ACTIONS)
ENTRY_METHODS: Final[tuple[str, ...]] = ("STAFF",)
FLAG_STATES: Final[tuple[str, ...]] = ("OPEN", "ACKNOWLEDGED")
BAND_PATTERN: Final[str] = r"^[A-Z][A-Z_]{0,31}$"

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FormResponse(SQLModel, table=True):
    """One completed instrument. Append-only."""

    __tablename__ = "form_responses"
    __table_args__ = (
        sa.CheckConstraint(
            f"instrument IN ({_sql_list(INSTRUMENT_CODES)})", name="instrument"
        ),
        sa.CheckConstraint(
            f"entry_method IN ({_sql_list(ENTRY_METHODS)})", name="entry_method"
        ),
        sa.CheckConstraint(f"band ~ '{BAND_PATTERN}'", name="band"),
        # The widest range any instrument has (PHQ-9 0-27, GAD-7 0-21, K10 10-50).
        sa.CheckConstraint("total_score BETWEEN 0 AND 50", name="total_score"),
        sa.CheckConstraint("corrects_id IS NULL OR corrects_id <> id", name="corrects"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_form_responses_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_form_responses_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "corrects_id"],
            ["form_responses.tenant_id", "form_responses.id"],
            name="fk_form_responses_tenant_corrects",
            ondelete="RESTRICT",
        ),
        # A patient's history, newest first.
        sa.Index(
            "ix_form_responses_tenant_patient_created",
            "tenant_id",
            "patient_id",
            "created_at",
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
    instrument: str = Field(max_length=16)
    instrument_version: str = Field(max_length=16)
    # Ciphertext of the JSON `{"answers": [...], "difficulty": n | null}`.
    answers: bytes
    total_score: int
    band: str = Field(max_length=32)
    entry_method: str = Field(default="STAFF", max_length=16)
    entered_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    corrects_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class SafetyFlag(SQLModel, table=True):
    """A safety rule a response met. Open until a clinician acknowledges it with an action."""

    __tablename__ = "safety_flags"
    __table_args__ = (
        sa.CheckConstraint(
            f"rule_code IN ({_sql_list(FLAG_RULE_CODES)})", name="rule_code"
        ),
        sa.CheckConstraint(f"status IN ({_sql_list(FLAG_STATES)})", name="status"),
        sa.CheckConstraint(
            f"action_code IS NULL OR action_code IN ({_sql_list(ACTION_CODES)})",
            name="action_code",
        ),
        # Acknowledged means who, when and what was done, together.
        sa.CheckConstraint(
            "(status = 'ACKNOWLEDGED') = (acknowledged_by IS NOT NULL)"
            " AND (acknowledged_by IS NULL) = (acknowledged_at IS NULL)"
            " AND (acknowledged_by IS NULL) = (action_code IS NULL)",
            name="acknowledged",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_safety_flags_tenant_id_id"),
        # One flag per rule per response.
        sa.UniqueConstraint(
            "tenant_id",
            "response_id",
            "rule_code",
            name="uq_safety_flags_response_rule",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_safety_flags_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "response_id"],
            ["form_responses.tenant_id", "form_responses.id"],
            name="fk_safety_flags_tenant_response",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_safety_flags_tenant_patient_status", "tenant_id", "patient_id", "status"
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
    response_id: uuid.UUID = Field(nullable=False)
    rule_code: str = Field(max_length=64)
    status: str = Field(default="OPEN", max_length=16)
    raised_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    acknowledged_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="RESTRICT"
    )
    acknowledged_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    action_code: str | None = Field(default=None, max_length=64)
