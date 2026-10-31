"""`tenant_settings`: a clinic's practice settings (docs3 feature 01, R4, R5).

One row per tenant, created on first save. A missing row means the defaults (nurses stage drafts,
adult records kept 7 years) and leaves the "Practice workflow" setup step undone (fail closed). The
forced permissive + restrictive RLS pair is created by the migration.
"""

import uuid
from datetime import UTC, datetime
from typing import Final

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

#: Who may be allowed to stage script drafts (R4). Nurses always may.
STAGING_ROLES: Final[tuple[str, ...]] = ("NURSE", "DOCTOR", "ADMINISTRATOR")
DEFAULT_STAGING_ROLES: Final[tuple[str, ...]] = ("NURSE",)
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
        sa.CheckConstraint(
            "'NURSE' = ANY(draft_staging_roles) AND draft_staging_roles <@ "
            "ARRAY[" + ", ".join(f"'{r}'" for r in STAGING_ROLES) + "]::text[]",
            name="draft_staging_roles",
        ),
    )

    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", primary_key=True, ondelete="RESTRICT"
    )
    draft_staging_roles: list[str] = Field(
        default_factory=lambda: list(DEFAULT_STAGING_ROLES),
        sa_type=sa.ARRAY(sa.Text()),
    )
    adult_retention_years: int = Field(default=MIN_ADULT_RETENTION_YEARS)
    updated_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
