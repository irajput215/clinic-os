"""The RBAC tables: `roles`, `permissions`, `role_permissions`, `user_roles`.

Design: `docs/features/03-users-and-roles/03-design.md`, "Data model". Columns, constraints, indexes
and the RLS shape are taken from there; the migration is what enforces them, because a model cannot
express `CREATE POLICY` and a database built from `SQLModel.metadata.create_all` would otherwise get
tables that look right and enforce nothing.

Three decisions this model makes because no document could, each reported rather than hidden:

- **`user_roles` references the legacy `user` table.** The design names `users(id)` for `user_id` and
  `granted_by`, but the Phase 1 `users` table is task T1-03 and is blocked by **D-003**; `users` does
  not exist. The only FK target that exists today is the template's `user` table, so the reference is
  made to it and moves when T1-03 lands. T1-02 is recorded "blocked by: none", which cannot be true
  of an FK to a table whose migration is blocked — raised, not silently resolved.
- **`roles.tenant_id` is `NOT NULL`.** The design's RLS policy key is `tenant_id` and the
  uniqueness rule is `(tenant_id, code)`; a nullable tenant key would be a tenant table the isolation
  lint cannot attribute to a tenant. A tenant's seven system roles are seeded per tenant.
- **Composite `(tenant_id, ...)` foreign keys are deferred.** The design says composite FKs include
  `tenant_id` "so a grant cannot cross a tenant boundary". That needs `UNIQUE (tenant_id, id)` on the
  referenced tables; `roles` will carry one when a composite FK is added, and the legacy `user` table
  would need a new constraint. Neither is in this slice — the `WITH CHECK` RLS clause plus the
  service always writing `tenant_id` from the session is the interim control. Reported.

`permissions` is global reference data and carries no `tenant_id` and no RLS, exactly as the design
requires.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.modules.users_roles.catalog import SYSTEM_ROLE_CODES

# The design's `CHECK IN` for `roles.code`. A tenant may rename a role's display name; it may not
# invent a role code while OPEN-2 (custom roles) is open.
_ROLE_CODE_CHECK = (
    "code IN (" + ", ".join(f"'{code}'" for code in SYSTEM_ROLE_CODES) + ")"
)

# One shared TypeEngine instance: SQLAlchemy types are immutable, and `sa_type` wants an instance.
_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Permission(SQLModel, table=True):
    """Global, read-only reference data seeded from a versioned migration."""

    __tablename__ = "permissions"
    __table_args__ = (
        # Named explicitly so the name is the one the migration creates and
        # `test_schema_conventions` compares; the convention would otherwise key it on `code`.
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    code: str
    description: str


class Role(SQLModel, table=True):
    """A tenant-scoped, named bundle of permission codes."""

    __tablename__ = "roles"
    __table_args__ = (
        sa.CheckConstraint(_ROLE_CODE_CHECK, name="code"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_id_code"),
        sa.Index("ix_roles_tenant_id", "tenant_id"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    # RESTRICT, not CASCADE: a role is grant metadata that audit history refers to, so removing the
    # organisation that owns it must fail loudly rather than destroy or orphan the grants. This is
    # the `RESTRICT for clinical and audit records` rule in docs/reference/database-conventions.md
    # and T-03.7's "FK ON DELETE RESTRICT on grants".
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    code: str
    name: str
    is_system: bool = Field(
        default=False, sa_column_kwargs={"server_default": sa.text("false")}
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class RolePermission(SQLModel, table=True):
    """The edge between a tenant's role and a global permission."""

    __tablename__ = "role_permissions"
    __table_args__ = (sa.Index("ix_role_permissions_tenant_id", "tenant_id"),)

    # Composite PK; both columns are foreign keys. RESTRICT for the same audit-attribution reason
    # as `roles.tenant_id`: a revoked grant is a delete the append-only audit trail explains, not a
    # cascade a role deletion performs silently.
    role_id: uuid.UUID = Field(
        foreign_key="roles.id", primary_key=True, ondelete="RESTRICT"
    )
    permission_id: uuid.UUID = Field(
        foreign_key="permissions.id", primary_key=True, ondelete="RESTRICT"
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )


class UserRole(SQLModel, table=True):
    """A role granted to an account inside one tenant.

    `user_id` and `granted_by` reference `user`, not the design's `users`: the Phase 1 identity table
    is T1-03, blocked by D-003. See the module docstring.
    """

    __tablename__ = "user_roles"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "role_id",
            name="uq_user_roles_tenant_id_user_id_role_id",
        ),
        # The design names `(tenant_id, user_id)`. The unique constraint above already leads with
        # those two columns, so this index is redundant; it is created because the design names it,
        # and flagged here rather than dropped silently.
        sa.Index("ix_user_roles_tenant_id_user_id", "tenant_id", "user_id"),
    )

    user_id: uuid.UUID = Field(
        foreign_key="user.id", primary_key=True, ondelete="RESTRICT"
    )
    role_id: uuid.UUID = Field(
        foreign_key="roles.id", primary_key=True, ondelete="RESTRICT"
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    # NOT NULL in the design, so the only honest `ondelete` is RESTRICT: the granter is attribution
    # evidence and no hard delete exists. `/users/me` deletes a `user` row today; that is a legacy
    # template path and it will now be refused for any account that has ever granted a role, which
    # is the fail-closed direction. Reported.
    granted_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    granted_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    last_reviewed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
