"""seed the tenant:read permission and grant it to existing tenants' roles

Revision ID: fbcebceb0686
Revises: 1a1af875311b
Create Date: 2026-10-06 10:11:00.808135

The catalogue in `app/modules/users_roles/catalog.py` gained a twentieth code, `tenant:read`, which
`GET /api/v1/tenants/current` requires (`docs/features/01-tenancy-and-clinics/03-design.md`,
"Endpoints"; recorded there as **OPEN-2**). Permissions are global reference data seeded by migration
(T1-09) and the role bundles are per tenant, so an already-existing tenant holds neither the new row nor
the grant for it until this migration runs.

## What is seeded

`tenant:read` itself, and one `role_permissions` row per (existing tenant, system role) whose bundle in
the catalogue contains the code — `PRACTICE_OWNER` (whose bundle is every code) and
`COMPLIANCE_AUDITOR` (US-7: an auditor's read-only visibility of tenant configuration). The set is
derived from `SYSTEM_ROLE_CATALOGUE` rather than restated, so the migration cannot disagree with the
runtime provisioning path.

Tenants created after this migration need nothing: `users_roles.service.provision_tenant` and
`provision_tenant_roles` seed each new tenant from the same catalogue, including the new code.

Every insert is `ON CONFLICT DO NOTHING` on the table's own uniqueness rule, so a re-run — or an
environment where the grant already exists — cannot duplicate a row. Like `4d092676eafa`, this migration
imports the catalogue and is therefore **not hermetic**
(`docs/reference/database-conventions.md`, "Migrations are not hermetic").
"""
from alembic import op
import sqlalchemy as sa

from app.modules.users_roles.catalog import (
    PERMISSION_CATALOGUE,
    SYSTEM_ROLE_CATALOGUE,
)


# revision identifiers, used by Alembic.
revision = 'fbcebceb0686'
down_revision = '1a1af875311b'
branch_labels = None
depends_on = None

# The code this migration exists for. One name, so `upgrade` and `downgrade` cannot disagree about what
# was seeded.
_SEEDED_PERMISSION_CODE = "tenant:read"

_INSERT_PERMISSION = sa.text(
    "INSERT INTO permissions (id, code, description) "
    "VALUES (gen_random_uuid(), :code, :description) "
    "ON CONFLICT (code) DO NOTHING"
)
_INSERT_ROLE_PERMISSION = sa.text(
    "INSERT INTO role_permissions (role_id, permission_id, tenant_id) "
    "SELECT r.id, p.id, r.tenant_id "
    "FROM roles r JOIN permissions p ON p.code = :permission_code "
    "WHERE r.tenant_id = :tenant_id AND r.code = :role_code "
    "ON CONFLICT DO NOTHING"
)


def _description(code: str) -> str:
    """The catalogue's own description, so the seeded row and the code cannot disagree."""
    for catalogue_code, description in PERMISSION_CATALOGUE:
        if catalogue_code == code:
            return description
    raise RuntimeError(
        f"{code} is no longer in PERMISSION_CATALOGUE; this migration cannot seed it"
    )


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        _INSERT_PERMISSION,
        {
            "code": _SEEDED_PERMISSION_CODE,
            "description": _description(_SEEDED_PERMISSION_CODE),
        },
    )

    roles_holding_it = [
        code
        for code, _name, bundle in SYSTEM_ROLE_CATALOGUE
        if _SEEDED_PERMISSION_CODE in bundle
    ]
    tenant_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM tenants"))]
    for tenant_id in tenant_ids:
        for role_code in roles_holding_it:
            bind.execute(
                _INSERT_ROLE_PERMISSION,
                {
                    "tenant_id": tenant_id,
                    "role_code": role_code,
                    "permission_code": _SEEDED_PERMISSION_CODE,
                },
            )


def downgrade() -> None:
    # The grants go before the permission they reference: `role_permissions.permission_id` is a foreign
    # key. Only the rows this migration can have written are removed, so a downgrade does not touch
    # another permission's grants.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = :code)"
        ),
        {"code": _SEEDED_PERMISSION_CODE},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code = :code"),
        {"code": _SEEDED_PERMISSION_CODE},
    )
