"""name the tenant checks as the convention intends

Revision ID: f993c55e6eaf
Revises: 0bc1f345552b
Create Date: 2026-10-05 17:44:54.690909

`706856e36a80` declared the two `tenants` checks with names that were *already* conventional —
`name='ck_tenants_status'` — and without `op.f()`, so `app.core.metadata` prepended its own
`ck_<table>_` and Postgres ended up with `ck_tenants_ck_tenants_status`. The model was later
corrected to declare the suffix (`name='status'`), so the metadata and the database have disagreed
about these two names ever since.

`alembic check` cannot see it: autogenerate does not compare check constraints, so the drift is
invisible to the tool this repo relies on. `tests/core/test_schema_conventions.py` now asserts the
names instead, which is the only thing that catches it.

Verified on a database built from scratch: replaying the migrations into an empty database produces
the same doubled names as the deployed one, so this rename is deterministic rather than a patch for
one environment. The constraint names are written literally, not through `op.f()`, so the convention
cannot re-prefix them a second time.

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f993c55e6eaf'
down_revision = '0bc1f345552b'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'ALTER TABLE tenants RENAME CONSTRAINT ck_tenants_ck_tenants_status '
        'TO ck_tenants_status'
    )
    op.execute(
        'ALTER TABLE tenants RENAME CONSTRAINT ck_tenants_ck_tenants_slug_lowercase '
        'TO ck_tenants_slug_lowercase'
    )


def downgrade():
    op.execute(
        'ALTER TABLE tenants RENAME CONSTRAINT ck_tenants_status '
        'TO ck_tenants_ck_tenants_status'
    )
    op.execute(
        'ALTER TABLE tenants RENAME CONSTRAINT ck_tenants_slug_lowercase '
        'TO ck_tenants_ck_tenants_slug_lowercase'
    )
