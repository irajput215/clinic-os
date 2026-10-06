"""tga_approvals and tga_approval_events: tables, grain constraint, triggers, RLS and grants

Revision ID: d4f8c2a9b7e1
Revises: b7c1d9e4f2a3
Create Date: 2026-10-06 14:30:00.000000

Feature 08 (`docs/features/08-tga-approvals/`), tasks T2-1 to T2-6. The design document is
`docs/features/08-tga-approvals/03-design.md`; the grain decision is
`docs/reference/decisions/D-006-approval-grain-and-validity-boundary.md`.

## What is enforced here, and why it is here rather than in the service

The grain is a clinical contract — `tenant_id + patient_id + tga_category + dosage_form + validity
window` — and INV-2 is the invariant that a prescription is dispensed only against a live approval at
that grain. Four controls are therefore in the database, where a future caller that bypasses
`app/modules/tga_approvals/service.py` still meets them:

1. **`no_overlapping_active_approvals`** — a partial `EXCLUDE USING gist` over
   `(tenant_id WITH =, patient_id WITH =, tga_category WITH =, dosage_form WITH =,
   validity_interval WITH &&) WHERE (state = 'ACTIVE')`. `btree_gist` is required because the
   constraint mixes equality operators (B-tree by default) with the range-overlap operator.
   `EXCLUDE` cannot be expressed in `SQLModel.metadata`, so it is created here and the model declares
   the GiST index it produces under the same name — see `app/modules/tga_approvals/models.py` for why
   that is the only declaration that keeps `alembic check` and `tests/core/test_schema_conventions.py`
   both honest.
2. **`ck_tga_approvals_max_duration`** — R3's two-year ceiling, next to
   `ck_tga_approvals_window` (`valid_to > valid_from`).
3. **`trg_tga_approval_interval`** — `validity_interval` is *derived* from `(valid_from, valid_to)`
   on every insert and update. The column the exclusion constraint indexes can therefore never
   describe a window other than the one the row's own dates name, which is the only way a derived
   index key is trustworthy.
4. **`trg_tga_approval_lock_verified`** — the Post-Verification Immutability Guard of design §2, the
   control the DoD's control matrix names as `trg_tga_approval_lock_verified` raising
   `VERIFIED_APPROVAL_IMMUTABLE`. It refuses, in one place: a state change outside the legal table
   (`ILLEGAL_STATE_TRANSITION`), any change to the grain, the dates or the provenance once the row has
   left `PENDING`, and any change at all to a terminal row.

   Triggers fire in **name order**, and the interval trigger is deliberately named to sort first
   (`trg_tga_approval_interval` < `trg_tga_approval_lock_verified`): the guard compares the *derived*
   interval against the stored one, so it must run after the derivation.

## RLS

`ENABLE` and `FORCE` on both tables, and two policies on each — a permissive `FOR ALL` (or
`SELECT` + `INSERT` for the event log) that actually grants a caller its own rows, plus a restrictive
floor so a permissive policy added later cannot widen what a caller reaches. A restrictive policy
alone denies every row; that was measured in `134a7201f6d2`, not assumed. The `NULLIF` guard makes an
unset tenant match nothing rather than raise, so the missing-tenant case is fail-closed.

`tga_approval_events` deliberately has **no** `UPDATE` policy and no `DELETE` policy: with the grant
below, a rewrite is refused by privilege, and with no policy it would affect zero rows even if a grant
were added in error. Two independent controls, which is what the design asks for.

The policies are `TO PUBLIC`, following `134a7201f6d2` and `b7c1d9e4f2a3`: the application connects
as the table owner today (and as a `BYPASSRLS` role in the deployed environment), and a policy scoped
to `clinos_app` — which is `NOLOGIN` — would apply to nobody. `FORCE` plus `TO PUBLIC` binds the
owner as well, so isolation holds for the connection that exists today **and** for the least-privilege
role when the deployment switches to it.

## Grants

    GRANT SELECT, INSERT, UPDATE ON tga_approvals TO clinos_app;
    REVOKE DELETE, TRUNCATE ON tga_approvals FROM clinos_app;   -- R13: never hard-deleted
    GRANT SELECT, INSERT ON tga_approval_events TO clinos_app;
    REVOKE UPDATE, DELETE, TRUNCATE ON tga_approval_events FROM clinos_app;   -- append-only

No `ALTER TABLE ... OWNER`: `clinos_migrator` is `NOLOGIN PASSWORD NULL`, and re-owning the table
would make every later migration impossible for the role that actually runs them. The property R15
and Gate 2 require is the negative one — the application role owns nothing and has no `BYPASSRLS` —
and that holds. Recorded as a deviation, as the two earlier migrations did.
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects.postgresql import DATERANGE

# revision identifiers, used by Alembic.
revision = "d4f8c2a9b7e1"
down_revision = "b7c1d9e4f2a3"
branch_labels = None
depends_on = None

# The design's fail-closed tenant guard, byte for byte, on both tables.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# The derived cast/index key. One expression, used by the trigger and by the check that documents it.
_INTERVAL_SQL = "daterange(valid_from, valid_to, '[)')"

_INTERVAL_FUNCTION = f"""
CREATE OR REPLACE FUNCTION tga_approval_interval() RETURNS trigger AS $fn$
BEGIN
    NEW.validity_interval := {_INTERVAL_SQL};
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

# The immutable grain of a verified approval: everything that identifies what was authorised, and
# everything that says who verified it and when. `updated_at` is deliberately absent — it is the one
# column a lifecycle transition may touch on an active row.
_GRAIN_COLUMNS = (
    "tenant_id",
    "patient_id",
    "tga_category",
    "dosage_form",
    "approval_reference",
    "valid_from",
    "valid_to",
    "validity_interval",
    "source_document_id",
    "created_by",
    "source",
    "creation_reason",
    "verified_by",
    "verified_at",
    "supersedes_id",
)

# A terminal row is frozen entirely: nothing may change but `updated_at`.
_TERMINAL_COLUMNS = (
    *_GRAIN_COLUMNS,
    "state",
    "revoked_by",
    "revoked_at",
    "revoked_reason_code",
    "superseded_by_id",
)


def _row(*prefix_and_columns: str) -> str:
    prefix, *columns = prefix_and_columns
    return "(" + ", ".join(f"{prefix}.{column}" for column in columns) + ")"


_LOCK_FUNCTION = f"""
CREATE OR REPLACE FUNCTION tga_approval_lock_verified() RETURNS trigger AS $fn$
BEGIN
    IF NEW.state IS DISTINCT FROM OLD.state THEN
        IF NOT (
            (OLD.state = 'PENDING' AND NEW.state IN ('ACTIVE', 'REJECTED', 'REVOKED'))
            OR (OLD.state = 'ACTIVE' AND NEW.state IN ('SUPERSEDED', 'EXPIRED', 'REVOKED'))
        ) THEN
            RAISE EXCEPTION
                'ILLEGAL_STATE_TRANSITION: % -> % is not a permitted transition',
                OLD.state, NEW.state
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    IF OLD.state <> 'PENDING' THEN
        IF {_row("NEW", *_GRAIN_COLUMNS)} IS DISTINCT FROM {_row("OLD", *_GRAIN_COLUMNS)} THEN
            RAISE EXCEPTION
                'VERIFIED_APPROVAL_IMMUTABLE: the grain and provenance of a verified approval cannot change'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    IF OLD.state IN ('EXPIRED', 'REJECTED', 'REVOKED', 'SUPERSEDED') THEN
        IF {_row("NEW", *_TERMINAL_COLUMNS)} IS DISTINCT FROM {_row("OLD", *_TERMINAL_COLUMNS)} THEN
            RAISE EXCEPTION
                'VERIFIED_APPROVAL_IMMUTABLE: a terminal approval is immutable'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    # `btree_gist` provides the GiST operator classes for the equality columns of the exclusion
    # constraint. Without it the statement below fails outright — the equality operators are B-tree
    # by default. D-006 open item 5 (availability on the target build) is answered by this statement
    # running: a build without the extension fails the migration loudly rather than degrading the
    # grain rule to nothing.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "tga_approvals",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("tga_category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("dosage_form", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "approval_reference", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        # Derived by `trg_tga_approval_interval` on every write; the exclusion constraint indexes it.
        sa.Column("validity_interval", DATERANGE(), nullable=False),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "creation_reason", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_reason_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "valid_to <= (valid_from + interval '2 years')::date",
            name=op.f("ck_tga_approvals_max_duration"),
        ),
        sa.CheckConstraint(
            "valid_to > valid_from", name=op.f("ck_tga_approvals_window")
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'EXPIRED', 'REJECTED', 'REVOKED', 'SUPERSEDED')",
            name=op.f("ck_tga_approvals_state"),
        ),
        sa.CheckConstraint(
            "source IN ('MANUAL_ENTRY', 'INBOX_EXTRACTION')",
            name=op.f("ck_tga_approvals_source"),
        ),
        sa.CheckConstraint(
            "tga_category ~ '^[A-Z0-9][A-Z0-9_]{0,31}$'",
            name=op.f("ck_tga_approvals_tga_category"),
        ),
        sa.CheckConstraint(
            "dosage_form ~ '^[A-Z0-9][A-Z0-9_]{0,31}$'",
            name=op.f("ck_tga_approvals_dosage_form"),
        ),
        sa.CheckConstraint(
            "approval_reference ~ '^[A-Za-z0-9][A-Za-z0-9/_. -]{0,63}$'",
            name=op.f("ck_tga_approvals_approval_reference"),
        ),
        sa.CheckConstraint(
            "creation_reason ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name=op.f("ck_tga_approvals_creation_reason"),
        ),
        sa.CheckConstraint(
            "revoked_reason_code IS NULL OR revoked_reason_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name=op.f("ck_tga_approvals_revoked_reason_code"),
        ),
        sa.CheckConstraint(
            f"validity_interval = {_INTERVAL_SQL}",
            name=op.f("ck_tga_approvals_validity_interval"),
        ),
        sa.CheckConstraint(
            "state <> 'ACTIVE' OR verified_at IS NOT NULL",
            name=op.f("ck_tga_approvals_active_verified"),
        ),
        sa.CheckConstraint(
            "state <> 'REVOKED' OR revoked_reason_code IS NOT NULL",
            name=op.f("ck_tga_approvals_revoked_reason"),
        ),
        sa.CheckConstraint(
            "state <> 'SUPERSEDED' OR superseded_by_id IS NOT NULL",
            name=op.f("ck_tga_approvals_superseded_link"),
        ),
        sa.CheckConstraint(
            "verified_by IS NULL OR verified_by <> created_by",
            name=op.f("ck_tga_approvals_four_eyes"),
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["tga_approvals.id"],
            name="fk_tga_approvals_supersedes_id_tga_approvals",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tga_approvals_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        # A composite key, not just a patient key: a row can only name a patient of its own tenant.
        # The cross-tenant patient link is refused by the database rather than by a service check.
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_tga_approvals_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tga_approvals")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tga_approvals_tenant_id_id"),
    )
    op.create_index(
        "ix_tga_approvals_tenant_patient_state",
        "tga_approvals",
        ["tenant_id", "patient_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_tga_approvals_tenant_state_valid_to",
        "tga_approvals",
        ["tenant_id", "state", "valid_to"],
        unique=False,
    )
    op.create_index(
        "ix_tga_approvals_tenant_patient_created",
        "tga_approvals",
        ["tenant_id", "patient_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "tga_approval_events",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("from_state", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("to_state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "to_state IN ('PENDING', 'ACTIVE', 'EXPIRED', 'REJECTED', 'REVOKED', 'SUPERSEDED')",
            name=op.f("ck_tga_approval_events_to_state"),
        ),
        sa.CheckConstraint(
            "from_state IS NULL OR from_state IN ('PENDING', 'ACTIVE', 'EXPIRED', 'REJECTED', 'REVOKED', 'SUPERSEDED')",
            name=op.f("ck_tga_approval_events_from_state"),
        ),
        sa.CheckConstraint(
            "from_state IS NULL OR from_state <> to_state",
            name=op.f("ck_tga_approval_events_transition"),
        ),
        sa.CheckConstraint(
            "source IN ('MANUAL_ENTRY', 'INBOX_EXTRACTION')",
            name=op.f("ck_tga_approval_events_source"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name=op.f("ck_tga_approval_events_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tga_approval_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        # The same tenant-bound composite key as the approval link: an event cannot be filed against
        # another tenant's approval.
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["tga_approvals.tenant_id", "tga_approvals.id"],
            name="fk_tga_approval_events_tenant_approval",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tga_approval_events")),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tga_approval_events_tenant_id_id"
        ),
    )
    op.create_index(
        "ix_tga_approval_events_tenant_approval_occurred",
        "tga_approval_events",
        ["tenant_id", "approval_id", "occurred_at"],
        unique=False,
    )

    # D-006 §1 / R11 / Gate 2. `WHERE (state = 'ACTIVE')` is what makes it compatible with the
    # supersede chain: a SUPERSEDED row does not collide with the replacement that superseded it.
    op.execute(
        "ALTER TABLE tga_approvals ADD CONSTRAINT no_overlapping_active_approvals "
        "EXCLUDE USING gist ("
        " tenant_id WITH =, patient_id WITH =, tga_category WITH =, dosage_form WITH =,"
        " validity_interval WITH &&"
        ") WHERE (state = 'ACTIVE')"
    )

    op.execute(_INTERVAL_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_tga_approval_interval "
        "BEFORE INSERT OR UPDATE ON tga_approvals "
        "FOR EACH ROW EXECUTE FUNCTION tga_approval_interval()"
    )
    op.execute(_LOCK_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_tga_approval_lock_verified "
        "BEFORE UPDATE ON tga_approvals "
        "FOR EACH ROW EXECUTE FUNCTION tga_approval_lock_verified()"
    )

    for table in ("tga_approvals", "tga_approval_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        "CREATE POLICY pol_tga_approvals_tenant_access ON tga_approvals "
        "AS PERMISSIVE FOR ALL TO PUBLIC "
        f"USING ({_TENANT_MATCH}) WITH CHECK ({_TENANT_MATCH})"
    )
    op.execute(
        "CREATE POLICY pol_tga_approvals_tenant_isolation ON tga_approvals "
        "AS RESTRICTIVE FOR ALL TO PUBLIC "
        f"USING ({_TENANT_MATCH}) WITH CHECK ({_TENANT_MATCH})"
    )
    # Two policies, and no UPDATE or DELETE policy: an audit-shaped table is append-only by *policy*
    # as well as by grant, so a grant added in error still affects zero rows.
    op.execute(
        "CREATE POLICY pol_tga_approval_events_tenant_select ON tga_approval_events "
        "AS PERMISSIVE FOR SELECT TO PUBLIC "
        f"USING ({_TENANT_MATCH})"
    )
    op.execute(
        "CREATE POLICY pol_tga_approval_events_tenant_insert ON tga_approval_events "
        "AS PERMISSIVE FOR INSERT TO PUBLIC "
        f"WITH CHECK ({_TENANT_MATCH})"
    )
    op.execute(
        "CREATE POLICY pol_tga_approval_events_tenant_isolation ON tga_approval_events "
        "AS RESTRICTIVE FOR ALL TO PUBLIC "
        f"USING ({_TENANT_MATCH}) WITH CHECK ({_TENANT_MATCH})"
    )

    # Least privilege, by grant. `DELETE` and `TRUNCATE` are revoked rather than merely not granted,
    # so this migration is the one place the set is written down and a re-run is a no-op.
    op.execute("GRANT SELECT, INSERT, UPDATE ON tga_approvals TO clinos_app")
    op.execute("REVOKE DELETE, TRUNCATE ON tga_approvals FROM clinos_app")
    op.execute("GRANT SELECT, INSERT ON tga_approval_events TO clinos_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON tga_approval_events FROM clinos_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tga_approval_events")
    op.execute("DROP TABLE IF EXISTS tga_approvals")
    op.execute("DROP FUNCTION IF EXISTS tga_approval_lock_verified()")
    op.execute("DROP FUNCTION IF EXISTS tga_approval_interval()")
    # `btree_gist` is deliberately not dropped: it is a cluster-level extension another table may
    # depend on by the time this downgrade runs, and dropping it would break that table's index.
