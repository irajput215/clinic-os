"""SOPs, their versions and who acknowledged which version (docs3 feature 02, manual §13).

Three tenant tables with the forced permissive + restrictive RLS pair (created by the migration):

- `sops` - one procedure: its title, the roles it applies to, whether onboarding needs it, and which
  version is current.
- `sop_versions` - every published text. Append-only: the app role holds `SELECT, INSERT`.
- `sop_acknowledgements` - who acknowledged which version, when. Append-only.

A new version un-acknowledges everyone it applies to by construction: acknowledgement is per version
and "acknowledged" means "of the current version".
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Sop(SQLModel, table=True):
    """One standard operating procedure (R5)."""

    __tablename__ = "sops"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "id", name="uq_sops_tenant_id_id"),
        sa.CheckConstraint("current_version >= 1", name="current_version"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    title: str = Field(max_length=200)
    applies_to_roles: list[str] = Field(
        default_factory=list,
        sa_type=sa.ARRAY(sa.Text()),
        sa_column_kwargs={"server_default": "{}"},
    )
    required_for_onboarding: bool = Field(
        default=False, sa_column_kwargs={"server_default": sa.false()}
    )
    current_version: int = Field(default=1)
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class SopVersion(SQLModel, table=True):
    """One published text of an SOP (R6). Never changed or deleted."""

    __tablename__ = "sop_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id", "sop_id", "version", name="uq_sop_versions_tenant_sop_version"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sop_id"],
            ["sops.tenant_id", "sops.id"],
            name="fk_sop_versions_tenant_sop",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version >= 1", name="version"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    sop_id: uuid.UUID
    version: int
    title: str = Field(max_length=200)
    body: str = Field(sa_type=sa.Text)
    published_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    published_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class SopAcknowledgement(SQLModel, table=True):
    """One person's acknowledgement of one version (R7). Never changed or deleted."""

    __tablename__ = "sop_acknowledgements"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id",
            "sop_id",
            "version",
            "user_id",
            name="uq_sop_acknowledgements_tenant_sop_version_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sop_id", "version"],
            ["sop_versions.tenant_id", "sop_versions.sop_id", "sop_versions.version"],
            name="fk_sop_acknowledgements_tenant_sop_version",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_sop_acknowledgements_tenant_user", "tenant_id", "user_id"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    sop_id: uuid.UUID
    version: int
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    acknowledged_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
