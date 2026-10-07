"""index the tga approvals register page order

Revision ID: 39b9d178ede9
Revises: 9a21387b450c
Create Date: 2026-10-07 14:41:03.152037

`GET /api/v1/tga-approvals` (the practice-wide register, `docs2/sdlc/05-approvals/api.md`, agreed
2026-10-07) pages a tenant's approvals newest first on the same `(created_at, id)` keyset as the
per-patient list. `ix_tga_approvals_tenant_patient_created` cannot serve that order, because
`patient_id` sits between the tenant and the sort key, so the register gets its own
`(tenant_id, created_at, id)` index. `tenant_id` leads, as every index on the table does (T2-6).

A plain `CREATE INDEX`: no ownership change, no superuser-only statement, so the deployment's
non-superuser owner can apply it (HANDOFF section 4 trap 1).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "39b9d178ede9"
down_revision = "9a21387b450c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_tga_approvals_tenant_created",
        "tga_approvals",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tga_approvals_tenant_created", table_name="tga_approvals")
