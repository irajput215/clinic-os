"""seed permissions and seven system roles

Revision ID: 4d092676eafa
Revises: f96bc0861b16
Create Date: 2026-10-05 23:58:30.955783

Task T1-09. Seeds the global permission catalogue and the seven system role bundles each existing
tenant is entitled to.

## What is seeded, and from where

The catalogue is the **19 permission codes** and the **seven role bundles** in
`app/modules/users_roles/catalog.py`, which is itself a transcription of
`docs/features/03-users-and-roles/01-requirements.md` "Permission catalogue (role x permission)". No
candidate code from the "Candidate additions named elsewhere" table is granted: **OPEN-1**
(19 vs "20" vs the candidates) is still open, and T1-09 makes the seed provisional until it closes.

The catalogue is imported rather than copied so the migration, the runtime provisioning path and the
seed assertion test cannot disagree about a bundle. That makes this migration **not hermetic** — replay
with a later catalogue seeds the later catalogue — which is already true of this repository's
migrations (`docs/reference/database-conventions.md`, "Migrations are not hermetic").

## Why the roles are per tenant

`roles.tenant_id` is `NOT NULL` and `(tenant_id, code)` is unique: a role is a tenant-scoped bundle.
A single global set of roles would not satisfy the design's RLS policy key or the uniqueness rule.
The migration therefore seeds the seven roles for **every tenant that exists when it runs**, and
`users_roles.service.provision_tenant` / `provision_tenant_roles` do the same for tenants created
afterwards (self-service signup, the demo organisation).

## Idempotent

Every insert is `ON CONFLICT DO NOTHING` on the table's own uniqueness rule, so re-running the seed
logic (the migration once, the service on every new tenant) cannot duplicate a row.
"""
from alembic import op
import sqlalchemy as sa

from app.modules.users_roles.catalog import (
    PERMISSION_CATALOGUE,
    SYSTEM_ROLE_CATALOGUE,
)


# revision identifiers, used by Alembic.
revision = '4d092676eafa'
down_revision = 'f96bc0861b16'
branch_labels = None
depends_on = None


_INSERT_PERMISSION = sa.text(
    "INSERT INTO permissions (id, code, description) "
    "VALUES (gen_random_uuid(), :code, :description) "
    "ON CONFLICT (code) DO NOTHING"
)
_INSERT_ROLE = sa.text(
    "INSERT INTO roles (id, tenant_id, code, name, is_system, created_at, updated_at) "
    "VALUES (gen_random_uuid(), :tenant_id, :code, :name, true, now(), now()) "
    "ON CONFLICT (tenant_id, code) DO NOTHING"
)
_INSERT_ROLE_PERMISSION = sa.text(
    "INSERT INTO role_permissions (role_id, permission_id, tenant_id) "
    "SELECT r.id, p.id, r.tenant_id "
    "FROM roles r JOIN permissions p ON p.code = :permission_code "
    "WHERE r.tenant_id = :tenant_id AND r.code = :role_code "
    "ON CONFLICT DO NOTHING"
)


def _seed_tenant(bind: sa.engine.Connection, tenant_id: object) -> None:
    for code, name, _bundle in SYSTEM_ROLE_CATALOGUE:
        bind.execute(_INSERT_ROLE, {"tenant_id": tenant_id, "code": code, "name": name})
    for code, _name, bundle in SYSTEM_ROLE_CATALOGUE:
        for permission_code in sorted(bundle):
            bind.execute(
                _INSERT_ROLE_PERMISSION,
                {
                    "tenant_id": tenant_id,
                    "role_code": code,
                    "permission_code": permission_code,
                },
            )


def upgrade():
    bind = op.get_bind()
    for code, description in PERMISSION_CATALOGUE:
        bind.execute(_INSERT_PERMISSION, {"code": code, "description": description})

    tenant_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM tenants"))]
    for tenant_id in tenant_ids:
        _seed_tenant(bind, tenant_id)


def downgrade():
    # Reverses the seed by removing the rows it can have written. `user_roles` goes first: it
    # references `roles` with `ON DELETE RESTRICT`, and the table migration's own downgrade drops the
    # tables immediately after this one. This is a development rollback, not a production path.
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM user_roles"))
    bind.execute(sa.text("DELETE FROM role_permissions"))
    bind.execute(sa.text("DELETE FROM roles"))
    bind.execute(sa.text("DELETE FROM permissions"))
