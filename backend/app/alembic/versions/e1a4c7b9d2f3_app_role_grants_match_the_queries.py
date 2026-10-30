"""the application role's grants match the queries the app runs

Revision ID: e1a4c7b9d2f3
Revises: d8e3f1a6c4b2
Create Date: 2026-10-30 19:30:00.000000

Running the API as `clinos_app` (the role production is meant to connect as) found two mismatches the
test suite could not, because every API test connected as the `postgres` superuser:

* `GET /tenants/current` selects `tenants.created_at` and `updated_at`, which the role could not read,
  so it failed with `permission denied for table tenants`. Both are timestamps with no PHI; they are
  granted. `legal_name` and `retention_profile` stay withheld.
* `UPDATE` on `"user"` was table-wide, so the app role could rewrite `is_superuser` and `tenant_id`:
  one query bug away from an escalation or a move into another clinic. It now holds `UPDATE` only on
  the columns the app writes after an account exists (`email`, `full_name`, `hashed_password`,
  `is_active`). `INSERT` is unchanged: signup and invitations create accounts with their tenant.

`tests/isolation/test_api_as_app_role.py` now drives the API as `clinos_app`, so the next mismatch
fails CI instead of production.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e1a4c7b9d2f3'
down_revision = 'd8e3f1a6c4b2'
branch_labels = None
depends_on = None

_USER_UPDATABLE = "email, full_name, hashed_password, is_active"


def upgrade():
    op.execute("GRANT SELECT (created_at, updated_at) ON tenants TO clinos_app")
    op.execute('REVOKE UPDATE ON "user" FROM clinos_app')
    op.execute(f'GRANT UPDATE ({_USER_UPDATABLE}) ON "user" TO clinos_app')


def downgrade():
    op.execute(f'REVOKE UPDATE ({_USER_UPDATABLE}) ON "user" FROM clinos_app')
    op.execute('GRANT UPDATE ON "user" TO clinos_app')
    op.execute("REVOKE SELECT (created_at, updated_at) ON tenants FROM clinos_app")
