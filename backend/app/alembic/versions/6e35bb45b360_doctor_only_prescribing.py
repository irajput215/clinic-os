"""doctor only prescribing

Revision ID: 6e35bb45b360
Revises: 413d1877df50
Create Date: 2026-10-31

Owner decision (2026-10-31): only a prescriber writes a script. The Nurse role loses
`prescription:create` (stage a draft) and `prescription:modify` (edit or cancel one) in every
existing tenant; `app.modules.users_roles.catalog` seeds new tenants the same way. A nurse keeps
`prescription:read`, so the script queue stays visible.

Downgrade restores the two grants.
"""

import sqlalchemy as sa
from alembic import op

revision = "6e35bb45b360"
down_revision = "413d1877df50"
branch_labels = None
depends_on = None

_REMOVED = ("prescription:create", "prescription:modify")

_DELETE = sa.text(
    "DELETE FROM role_permissions rp USING roles r, permissions p "
    "WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.tenant_id = r.tenant_id "
    "AND r.tenant_id = :tenant_id AND r.code = 'NURSE' AND p.code = :code"
)
_INSERT = sa.text(
    "INSERT INTO role_permissions (role_id, permission_id, tenant_id) "
    "SELECT r.id, p.id, r.tenant_id FROM roles r JOIN permissions p ON p.code = :code "
    "WHERE r.tenant_id = :tenant_id AND r.code = 'NURSE' ON CONFLICT DO NOTHING"
)


def _each_tenant(statement: sa.TextClause) -> None:
    bind = op.get_bind()
    for (tenant_id,) in bind.execute(sa.text("SELECT id FROM tenants")).all():
        # The RBAC tables carry forced RLS; scope each statement to its tenant.
        bind.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        for code in _REMOVED:
            bind.execute(statement, {"tenant_id": tenant_id, "code": code})


def upgrade() -> None:
    _each_tenant(_DELETE)


def downgrade() -> None:
    _each_tenant(_INSERT)
