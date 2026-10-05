"""name the tenant checks as the convention intends

Revision ID: f993c55e6eaf
Revises: 0bc1f345552b
Create Date: 2026-10-05 17:44:54.690909

`706856e36a80` declared the two `tenants` checks with names that were *already* conventional
(`name='ck_tenants_status'`) and without `op.f()`, so whenever `app.core.metadata` was in effect the
convention prepended its own `ck_<table>_`. The model was later corrected to declare the suffix
(`name='status'`), so metadata and database have disagreed about these two names ever since.

**That migration is not hermetic: it produced different names depending on the code around it.**

- It reached the deployed database from PR #12, when `app.core.metadata` did not exist yet, so Postgres
  took the declared name literally and the deployed database has `ck_tenants_status`.
- Every database rebuilt afterwards — including one built from scratch — has the convention active when
  `706856e36a80` replays, so it has `ck_tenants_ck_tenants_status`.

So this migration converges *both* states instead of asserting one. It renames only where the doubled
name is present and the intended name is not: a no-op on the deployed database, a correction everywhere
else. It cannot be a bare `ALTER TABLE ... RENAME CONSTRAINT`, which fails on the deployed database with
`constraint "ck_tenants_ck_tenants_status" does not exist` — learned from Deploy run 37308445828.

`alembic check` cannot see any of this: autogenerate does not compare check constraints.
`tests/core/test_schema_conventions.py` asserts the names instead, which is the only thing that catches it.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f993c55e6eaf'
down_revision = '0bc1f345552b'
branch_labels = None
depends_on = None

# Raw SQL, so `app.core.metadata` cannot re-prefix the names a second time. Guarded in both
# directions because the prior state is environment-dependent (see the module docstring).
_RENAME = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = '{old}' AND conrelid = 'tenants'::regclass)
       AND NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = '{new}' AND conrelid = 'tenants'::regclass) THEN
        ALTER TABLE tenants RENAME CONSTRAINT {old} TO {new};
    END IF;
END $$;
"""

_CHECKS = (
    ('ck_tenants_ck_tenants_status', 'ck_tenants_status'),
    ('ck_tenants_ck_tenants_slug_lowercase', 'ck_tenants_slug_lowercase'),
)


def upgrade():
    for doubled, intended in _CHECKS:
        op.execute(_RENAME.format(old=doubled, new=intended))


def downgrade():
    # Mirrors the upgrade. A perfect inverse does not exist: the state this migration renames from
    # was never the same in every environment.
    for doubled, intended in _CHECKS:
        op.execute(_RENAME.format(old=intended, new=doubled))
