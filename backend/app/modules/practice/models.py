"""`tenant_settings`: a clinic's practice settings (docs3 feature 01, R5).

One row per tenant, created on first save. A missing row means the default (adult records kept 7
years) and leaves the "Practice settings" setup step undone (fail closed). The forced permissive +
restrictive RLS pair is created by the migration.

Who writes scripts is not a setting: only prescribers do (owner decision, 2026-10-31), so the
staging-roles column of feature 01 R4 was dropped.
"""

import uuid
from datetime import UTC, datetime
from typing import Final

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

MIN_ADULT_RETENTION_YEARS: Final = 7

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TenantSettings(SQLModel, table=True):
    __tablename__ = "tenant_settings"
    __table_args__ = (
        sa.CheckConstraint(
            f"adult_retention_years >= {MIN_ADULT_RETENTION_YEARS}",
            name="adult_retention_years",
        ),
    )

    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", primary_key=True, ondelete="RESTRICT"
    )
    adult_retention_years: int = Field(default=MIN_ADULT_RETENTION_YEARS)
    updated_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
