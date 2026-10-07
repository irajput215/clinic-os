"""index the patient name search keys for `POST /api/v1/patients/search`

Revision ID: b9fa64996260
Revises: 9a21387b450c
Create Date: 2026-10-07 14:41:27.511247

Patient search is a case-insensitive **prefix** match on `family_name`, `given_name` and
`preferred_name` (`docs/features/05-patients/03-design.md`: the plaintext name columns are the search
keys). One expression index per column, `(tenant_id, lower(<column>) text_pattern_ops)`:
`text_pattern_ops` is what lets `lower(col) LIKE 'smi%'` become an index range under the database's
non-`C` collation, and `tenant_id` leads as on every other index of this table.

Why an index at all, measured rather than assumed - `EXPLAIN (ANALYZE, BUFFERS)` on PostgreSQL 18 with
400,000 synthetic patients (200,000 in the searched tenant), for a selective term that matches 10 rows:

- before: `Index Scan using ix_patients_tenant_family_name`, `Rows Removed by Filter: 199990`,
  201,537 buffers, **228 ms** - every row of the tenant is read and filtered;
- after: `BitmapOr` of `ix_patients_tenant_family_name_lower` and `ix_patients_tenant_given_name_lower`
  with `Index Cond: lower(family_name) ~>=~ 'zedxanq' AND ~<~ 'zedxanr'`, 16 buffers, **0.2 ms**.

A broad one-letter term still uses the existing `(tenant_id, family_name, given_name)` index in page
order (2 ms), and a date-of-birth term uses `ix_patients_tenant_dob`; neither needed a new index.

Why not `pg_trgm`: the search is prefix, not substring, so a btree serves it with no extension, and a
plain `CREATE INDEX` is safe for a non-superuser migration owner (no `OWNER TO`, no extension, nothing
superuser-only) - proven with the prod-sim recipe in the pull request.

Plain `CREATE INDEX` rather than `CONCURRENTLY`: Alembic runs each migration in a transaction, the
table is small in every deployment today, and the brief write lock is the simpler failure mode.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b9fa64996260"
down_revision = "9a21387b450c"
branch_labels = None
depends_on = None

_SEARCH_COLUMNS = ("family_name", "given_name", "preferred_name")


def upgrade() -> None:
    for column in _SEARCH_COLUMNS:
        op.create_index(
            f"ix_patients_tenant_{column}_lower",
            "patients",
            [
                "tenant_id",
                sa.literal_column(f"lower({column})").label(f"{column}_lower"),
            ],
            unique=False,
            postgresql_ops={f"{column}_lower": "text_pattern_ops"},
        )


def downgrade() -> None:
    for column in reversed(_SEARCH_COLUMNS):
        op.drop_index(f"ix_patients_tenant_{column}_lower", table_name="patients")
