"""users roles permissions with forced row level security

Revision ID: f96bc0861b16
Revises: 33c56ebab859
Create Date: 2026-10-05 23:58:12.402364

Task T1-02. The four RBAC tables of `docs/features/03-users-and-roles/03-design.md`, "Data model":
`permissions` (global reference data, no RLS), and `roles`, `role_permissions`, `user_roles`
(tenant-scoped, `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy shape from the design's "RLS" section).

## Deliberate deviations, each reported

1. **`user_roles.user_id` and `user_roles.granted_by` reference the legacy `user` table, not `users`.**
   The design names `users(id)`, but the Phase 1 `users` table is task T1-03 and is `blocked by: D-003`;
   `users` does not exist, and an FK cannot be created to it. T1-02 is recorded "blocked by: none",
   which is not true of an FK to a table whose own migration is blocked. The reference is made to the
   table that exists and moves when T1-03 lands.

2. **No composite `(tenant_id, ...)` foreign key.** The design says composite FKs include `tenant_id`
   "so a grant cannot cross a tenant boundary". That needs `UNIQUE (tenant_id, id)` on `user` and
   `users`; neither exists, and adding a constraint to the legacy identity table is a schema change on
   a table D-003 will re-shape. Interim control: `tenant_id` is `NOT NULL` and the RLS `WITH CHECK`
   refuses a row whose tenant does not match the transaction's `app.tenant_id`.

3. **`DELETE` is not granted on `role_permissions` / `user_roles`.** The design grants
   `SELECT, INSERT, DELETE` ("grant/revoke is real"). That conflicts with the standing control in
   `tests/isolation/test_app_role_is_not_owner.py`: `clinos_app` holds no `DELETE` or `TRUNCATE` on
   any table carrying a `tenant_id`. The two cannot both hold. This migration keeps the narrower
   grant (`SELECT, INSERT`, no hard delete) and the no-revoke endpoint is out of this slice. Revisit
   when the role-revocation endpoint lands.

4. **`clinos_app` may `INSERT` on `tenants`.** The tenancy design (`REVOKE ALL ON tenants`) assumes
   central provisioning; self-service organisation signup is a shipped feature (D17) and inserts the
   tenant. Approved deviation, recorded against that decision.

5. **`clinos_app` reads `user.hashed_password`.** `02-authentication/03-design.md` Branch B routes the
   credential path through a second role, `clinos_auth`, with `REVOKE SELECT (hashed_password)`. The
   approved decision is one runtime connection for now, so `clinos_app` holds table-level
   `SELECT, INSERT, UPDATE ON "user"` (a table-level `SELECT` survives a column-level `REVOKE`, so the
   Branch B column grant is not applied). Revisit when D-003 lands and the second connection exists.

## Policies

The design names `pol_users_tenant_isolation` (for the `users` table T1-03 will create). For the three
tenant tables here, this migration follows the pattern `134a7201f6d2` established for `patients`: a
**permissive** `pol_<table>_tenant_access` that grants a caller its own rows, plus the design's
**restrictive** `pol_<table>_tenant_isolation` floor, both `TO PUBLIC` because `clinos_app` still has no
credential and the application connects as the table owner. A restrictive policy alone grants nothing —
measured during T1-05 — so the permissive policy is required for the tables to be usable at all.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'f96bc0861b16'
down_revision = '33c56ebab859'
branch_labels = None
depends_on = None

# Raw SQL, so the naming convention cannot rewrite the policy name or the setting key.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# The three tenant-scoped tables this migration adds a policy to. `permissions` is global and carries
# no tenant key and no policy.
_TENANT_TABLES = ("roles", "role_permissions", "user_roles")


def upgrade():
    op.create_table('permissions',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permissions')),
    sa.UniqueConstraint('code', name='uq_permissions_code')
    )
    op.create_table('roles',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("code IN ('PRACTICE_OWNER', 'AUTHORISED_PRESCRIBER', 'DOCTOR', 'NURSE', 'ADMINISTRATOR', 'PHARMACY', 'COMPLIANCE_AUDITOR')", name=op.f('ck_roles_code')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_roles_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_roles_tenant_id_code')
    )
    op.create_index('ix_roles_tenant_id', 'roles', ['tenant_id'], unique=False)
    op.create_table('role_permissions',
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('permission_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], name=op.f('fk_role_permissions_permission_id_permissions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_role_permissions_role_id_roles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_role_permissions_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('role_id', 'permission_id', name=op.f('pk_role_permissions'))
    )
    op.create_index('ix_role_permissions_tenant_id', 'role_permissions', ['tenant_id'], unique=False)
    op.create_table('user_roles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('granted_by', sa.Uuid(), nullable=False),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['granted_by'], ['user.id'], name=op.f('fk_user_roles_granted_by_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_user_roles_role_id_roles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_user_roles_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_user_roles_user_id_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('user_id', 'role_id', name=op.f('pk_user_roles')),
    sa.UniqueConstraint('tenant_id', 'user_id', 'role_id', name='uq_user_roles_tenant_id_user_id_role_id')
    )
    op.create_index('ix_user_roles_tenant_id_user_id', 'user_roles', ['tenant_id', 'user_id'], unique=False)

    # The isolation boundary, per table. `ENABLE` turns the policy on; `FORCE` applies it to the table
    # owner too. Both a permissive grant and the design's restrictive floor, `TO PUBLIC` for the same
    # reason as `patients`: `clinos_app` does not yet have a credential.
    for table in _TENANT_TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY pol_{table}_tenant_access ON {table} '
            'AS PERMISSIVE FOR ALL TO PUBLIC '
            f'USING ({_TENANT_MATCH}) '
            f'WITH CHECK ({_TENANT_MATCH})'
        )
        op.execute(
            f'CREATE POLICY pol_{table}_tenant_isolation ON {table} '
            'AS RESTRICTIVE FOR ALL TO PUBLIC '
            f'USING ({_TENANT_MATCH}) '
            f'WITH CHECK ({_TENANT_MATCH})'
        )

    # Grants. `roles` is mutable (a tenant edits a display name); `permissions` is global read-only
    # reference data; the grant tables may insert and never hard-delete (deviation 3).
    op.execute('GRANT SELECT, INSERT, UPDATE ON roles TO clinos_app')
    op.execute('REVOKE DELETE, TRUNCATE ON roles FROM clinos_app')
    op.execute('GRANT SELECT ON permissions TO clinos_app')
    op.execute('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON permissions FROM clinos_app')
    op.execute('GRANT SELECT, INSERT ON role_permissions, user_roles TO clinos_app')
    op.execute('REVOKE UPDATE, DELETE, TRUNCATE ON role_permissions, user_roles FROM clinos_app')

    # Approved deviation 4: self-service organisation signup inserts the tenant.
    op.execute('GRANT INSERT ON tenants TO clinos_app')
    # Approved deviation 5: the single runtime connection reads `hashed_password` as `clinos_app`.
    op.execute('GRANT SELECT, INSERT, UPDATE ON "user" TO clinos_app')
    op.execute('REVOKE DELETE, TRUNCATE ON "user" FROM clinos_app')


def downgrade():
    op.execute('REVOKE INSERT ON tenants FROM clinos_app')
    op.execute('REVOKE SELECT, INSERT, UPDATE ON "user" FROM clinos_app')
    op.execute('REVOKE SELECT, INSERT ON role_permissions, user_roles FROM clinos_app')
    op.execute('REVOKE SELECT ON permissions FROM clinos_app')
    op.execute('REVOKE SELECT, INSERT, UPDATE ON roles FROM clinos_app')

    for table in reversed(_TENANT_TABLES):
        op.execute(f'DROP POLICY pol_{table}_tenant_isolation ON {table}')
        op.execute(f'DROP POLICY pol_{table}_tenant_access ON {table}')
        op.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')

    op.drop_index('ix_user_roles_tenant_id_user_id', table_name='user_roles')
    op.drop_table('user_roles')
    op.drop_index('ix_role_permissions_tenant_id', table_name='role_permissions')
    op.drop_table('role_permissions')
    op.drop_index('ix_roles_tenant_id', table_name='roles')
    op.drop_table('roles')
    op.drop_table('permissions')
