"""The `tenants` table.

`docs/features/01-tenancy-and-clinics/03-design.md`, "Table: tenants (GLOBAL — no RLS)".
A tenant is the customer organisation. The table is global by design: tenant context is
proven from the actor's session and the addressed resource, never read from here, so it
carries no row-level security.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

TenantStatus = Literal["ACTIVE", "SUSPENDED", "CLOSING", "CLOSED"]

# SQLModel cannot map a Literal to a column type, so the vocabulary is enforced by
# the CHECK constraint below and mirrored here for schemas and validators.
STATUS_VOCABULARY: tuple[TenantStatus, ...] = (
    "ACTIVE",
    "SUSPENDED",
    "CLOSING",
    "CLOSED",
)

# Data stays in Australia (INV-6); this release admits one region.
DATA_REGIONS: tuple[str, ...] = ("ap-southeast-2",)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'CLOSING', 'CLOSED')",
            name="ck_tenants_status",
        ),
        # The slug is routing only, never an authorisation input; keeping it
        # lower-case makes the uniqueness guarantee predictable.
        sa.CheckConstraint("slug = lower(slug)", name="ck_tenants_slug_lowercase"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    slug: str = Field(unique=True, index=True, max_length=64)
    legal_name: str = Field(max_length=255)
    status: str = Field(default="ACTIVE", max_length=16)
    data_region: str = Field(default="ap-southeast-2", max_length=32)
    retention_profile: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
