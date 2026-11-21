"""the TGA inbox extractor role

Revision ID: 9c4e2b7d1a05
Revises: 76d612d39792
Create Date: 2026-11-21 08:00:00.000000

FEAT-09 R14 and `docs/features/09-tga-inbox/03-design.md`, "Privileges":

    GRANT INSERT, SELECT ON tga_extraction_results TO clinos_extractor;
    REVOKE ALL ON tga_approvals FROM clinos_extractor;

`33c56ebab859` deferred this role until its table existed; `76d612d39792` created the table.

## What the role may do

`clinos_extractor` is the role the ingestion pipeline's write transactions run as
(`app/modules/tga_inbox/pipeline.py`, `SET LOCAL ROLE clinos_extractor`). It holds exactly what
ingestion writes and nothing else:

| Object | Privilege | Why |
| --- | --- | --- |
| `tga_inbox_messages` | `SELECT, INSERT` | record the message; the redelivery check reads it |
| `tga_inbox_attachments` | `SELECT, INSERT` | record each file |
| `tga_extraction_results` | `SELECT, INSERT` | the design's grant: the values as read |
| `audit_log` | `SELECT, INSERT` | every stage audits on its own transaction (INV-4); the chain writer reads the head |
| `tga_approvals`, `patients`, everything else | none | **no automated step writes clinical state** (R14) |

No `UPDATE` anywhere: the value as read is immutable, and a message's review state belongs to the
reviewer, who acts as `clinos_app`. Every table above has a `TO PUBLIC` RLS policy pair, so the role is
bound to the transaction's tenant exactly as `clinos_app` is.

## How the application reaches it

`NOLOGIN` and `PASSWORD NULL`, like every role here: no credential in a migration. `clinos_app` is
made a member so the running application can `SET LOCAL ROLE clinos_extractor` inside one transaction
and fall back to itself at commit. Membership is the only change to `clinos_app`: its own privileges are
a superset of the extractor's, so it gains nothing. The role running the migration is made a member
too, for a deployment whose application still connects as that login. An application connecting as
any **other** role needs `GRANT clinos_extractor TO <that role>` before ingestion is switched on, or
every ingest fails with `permission denied to set role`: fail closed, never a silent bypass.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "9c4e2b7d1a05"
down_revision = "76d612d39792"
branch_labels = None
depends_on = None

_ROLE = "clinos_extractor"
_GRANTS = {
    "tga_inbox_messages": "SELECT, INSERT",
    "tga_inbox_attachments": "SELECT, INSERT",
    "tga_extraction_results": "SELECT, INSERT",
    "audit_log": "SELECT, INSERT",
}


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ROLE}') THEN "
        f"CREATE ROLE {_ROLE} "
        "NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOLOGIN PASSWORD NULL; "
        "END IF; END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE}")
    for table, privileges in _GRANTS.items():
        op.execute(f"REVOKE ALL ON {table} FROM {_ROLE}")
        op.execute(f"GRANT {privileges} ON {table} TO {_ROLE}")
    # The design's explicit denial: nothing the extractor runs may touch an approval.
    op.execute(f"REVOKE ALL ON tga_approvals, tga_approval_events, patients FROM {_ROLE}")
    op.execute(f"GRANT {_ROLE} TO clinos_app")
    # A deployment whose application connects as the same login the migrations run as (the default:
    # `MIGRATION_DATABASE_URL` falls back to `DATABASE_URL`) must be able to switch into the role too.
    # On PostgreSQL 16+ creating a role does not let its creator `SET ROLE` to it, so say so here.
    op.execute(f"GRANT {_ROLE} TO CURRENT_USER")


def downgrade() -> None:
    op.execute(f"REVOKE {_ROLE} FROM CURRENT_USER")
    op.execute(f"REVOKE {_ROLE} FROM clinos_app")
    for table in _GRANTS:
        op.execute(f"REVOKE ALL ON {table} FROM {_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {_ROLE}")
