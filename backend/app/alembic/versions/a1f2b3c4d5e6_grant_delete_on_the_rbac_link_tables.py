"""grant DELETE on the RBAC link tables

Revision ID: a1f2b3c4d5e6
Revises: 4d092676eafa
Create Date: 2026-10-06 00:00:00.000000

The role-administration slice (T1-29/T1-30 follow-on). `clinos_app` needs `DELETE` on
`role_permissions` and `user_roles` so a role can actually be **revoked**.

## What this reverses, and why the earlier decision was wrong

`f96bc0861b16` (deviation 3) withheld `DELETE` on both link tables, because the standing control in
`tests/isolation/test_app_role_is_not_owner.py` asserted that `clinos_app` holds no `DELETE` or
`TRUNCATE` on **any** table carrying a `tenant_id`. That control was over-broad. Its purpose is
requirement R14 / the no-hard-delete rule in `03-users-and-roles/01-requirements.md`: *"A user is
deactivated, not hard-deleted; clinical attribution survives"*. That rule is real, but it is not
universal: `03-design.md` §Database privileges says, in so many words,

    GRANT SELECT, INSERT, DELETE ON role_permissions, user_roles TO clinos_app;  -- grant/revoke is real

So the control keeps its breadth and names **one documented exception** instead of shrinking to an
allow-list of the tables someone happened to remember: every tenant table other than these two link
tables still holds no `DELETE` and no `TRUNCATE`, including tables added later (`users` and `roles`
are the ones R14 and the design's own `REVOKE DELETE, TRUNCATE ON users, roles` are about). This
migration implements the design's grant, and `tests/isolation/test_patients_isolation.py` still
proves the runtime refusal.

`TRUNCATE` stays revoked on both link tables. The design revokes it explicitly — *"history in
audit_log"* — and a revoke is a single-row delete, never a table wipe.

## Idempotent

`GRANT` and `REVOKE` are idempotent in PostgreSQL, so a re-run of an interrupted migration is safe.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1f2b3c4d5e6"
down_revision = "4d092676eafa"
branch_labels = None
depends_on = None

# The two link tables the design names — the only tenant tables `clinos_app` may delete from. The
# others are not touched: `permissions` stays `SELECT`-only global reference data (R7), and `users`,
# `roles` and `patients` keep no `DELETE`/`TRUNCATE` (R14).
_LINK_TABLES = "role_permissions, user_roles"


def upgrade() -> None:
    # The design's grant, verbatim: "grant/revoke is real".
    op.execute(f"GRANT DELETE ON {_LINK_TABLES} TO clinos_app")
    # Restated, not newly revoked: the design forbids a table wipe, and `f96bc0861b16` already
    # revoked it. Keeping it here means this migration is the one place the link-table privilege set
    # is readable.
    op.execute(f"REVOKE TRUNCATE ON {_LINK_TABLES} FROM clinos_app")


def downgrade() -> None:
    # Reverse only what this migration introduced. `SELECT, INSERT` on both tables and the
    # `TRUNCATE` refusal predate it, so they are left in force.
    op.execute(f"REVOKE DELETE ON {_LINK_TABLES} FROM clinos_app")
