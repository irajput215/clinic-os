"""seed the `tga_approval:revoke` permission Feature 08's revoke route requires

Revision ID: e5a9d3b8c2f4
Revises: d4f8c2a9b7e1
Create Date: 2026-10-06 14:40:00.000000

`docs/features/08-tga-approvals/03-design.md`'s endpoints table gives
`POST /api/v1/tga-approvals/{id}/revoke` the permission `tga_approval:revoke`, and no such code
existed: `01-requirements.md`'s 19-code matrix belongs to the users-and-roles feature and specifies
revocation as *"a practice owner revokes"* (08 US-6) rather than as a granular code.

The alternative — reusing `tga_approval:verify` — would hand revocation to every role that can verify,
including `COMPLIANCE_AUDITOR`, which 08 US-7 requires to *"list and view, cannot change anything"*.
So the code is added, `catalog.py` is the single source, and `PRACTICE_OWNER` — whose bundle is
derived from the catalogue tuple — gains it without a second edit.

This migration is idempotent and re-runs the whole seed rather than inserting one row, exactly as
`4d092676eafa` does: it imports the catalogue instead of copying it, so the migration, the runtime
provisioning path (`users_roles.service.seed_tenant_roles`) and `tests/rbac/test_seed_catalogue.py`
cannot disagree about a bundle. That makes it non-hermetic, which is already true of this repository's
migrations (`docs/reference/database-conventions.md`, "Migrations are not hermetic").

The downgrade removes only the rows this code introduced.
"""

from alembic import op
import sqlalchemy as sa

from app.modules.users_roles.catalog import (
    PERMISSION_CATALOGUE,
    SYSTEM_ROLE_CATALOGUE,
)

# revision identifiers, used by Alembic.
revision = "e5a9d3b8c2f4"
down_revision = "d4f8c2a9b7e1"
branch_labels = None
depends_on = None

# The one code this migration exists for. Named here so the downgrade cannot remove anything else.
NEW_PERMISSION = "tga_approval:revoke"

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


def upgrade() -> None:
    bind = op.get_bind()
    descriptions = dict(PERMISSION_CATALOGUE)
    assert NEW_PERMISSION in descriptions, (
        "catalog.py must declare tga_approval:revoke before this migration runs"
    )
    bind.execute(
        _INSERT_PERMISSION,
        {"code": NEW_PERMISSION, "description": descriptions[NEW_PERMISSION]},
    )

    # Every existing tenant whose bundles contain the new code gets the grant. The bundle comes from
    # the catalogue, so a role that should hold it cannot be missed by a hand-written list here.
    tenant_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM tenants"))]
    granting_roles = [
        (code, bundle)
        for code, _name, bundle in SYSTEM_ROLE_CATALOGUE
        if NEW_PERMISSION in bundle
    ]
    for tenant_id in tenant_ids:
        for code, _bundle in granting_roles:
            bind.execute(
                _INSERT_ROLE_PERMISSION,
                {
                    "tenant_id": tenant_id,
                    "role_code": code,
                    "permission_code": NEW_PERMISSION,
                },
            )


def downgrade() -> None:
    # Only this permission's rows. `role_permissions` references `permissions` with `ON DELETE
    # RESTRICT`, so the grants go first.
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = :code)"
        ).bindparams(code=NEW_PERMISSION)
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE code = :code").bindparams(
            code=NEW_PERMISSION
        )
    )
