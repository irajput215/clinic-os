"""clinical_records and clinical_record_versions, append-only and tenant-isolated

Revision ID: d4c9b7a1e5f2
Revises: b7c1d9e4f2a3
Create Date: 2026-10-06

Feature 06, task T1-06. `docs/features/06-clinical-records/03-design.md` §"Schema",
§"Database privileges", §"RLS" and §"Immutability mechanism at two layers"; requirements R1-R17.

Four controls live in this migration, and three of them are enforced by PostgreSQL rather than by
application convention — *"Enforcement is by grant, not by convention. A convention is bypassed by a
determined developer; a missing privilege is not."*

1. **Tenant isolation.** `ENABLE` + `FORCE ROW LEVEL SECURITY` on both tables, with the design's
   policy expression `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. The
   `NULLIF` is what makes a missing tenant context return **zero rows rather than every row**: an
   unset or empty setting becomes `NULL`, and `tenant_id = NULL` matches nothing. Every query the
   module runs also carries an explicit `tenant_id` predicate, as a second line of defence for the
   connection role that still owns the tables (`docs/progress.md` §4).

   The policy is declared twice, exactly as the patients migration does: a **permissive** policy is
   what grants a caller its own rows (a restrictive policy can only narrow, never grant), and a
   **restrictive** policy of the same expression is the floor that keeps a later permissive policy
   from widening access.

2. **Immutability, primary layer — the grant.** `clinos_app` receives exactly `SELECT, INSERT` on
   `clinical_record_versions`. `UPDATE`, `DELETE` and `TRUNCATE` are revoked, so an in-place
   alteration raises `42501 insufficient_privilege`. `clinical_records` receives `SELECT, INSERT`
   plus a **column-scoped** `UPDATE (current_version, signed_at, deleted_at)`, so `tenant_id`,
   `patient_id`, `record_type` and `author_id` cannot be rewritten even by the application role.

3. **Immutability, defence in depth — the trigger.** A grant binds only its grantee, so
   `trg_clinical_record_versions_immutable` is a `BEFORE UPDATE OR DELETE ... FOR EACH STATEMENT`
   trigger that raises for **every role, including the table owner and the migration role**. No role
   exemption, no disabling setting (`03-design.md` §3; R14).

   One consequence is deliberate and worth stating: this trigger is why clinical test fixtures clean
   up with `TRUNCATE` rather than `DELETE`. `TRUNCATE` fires no `BEFORE UPDATE OR DELETE` trigger,
   and the application role holds no `TRUNCATE` privilege — so the escape hatch exists for the test
   owner and for nobody in production.

4. **Append-only provenance.** `UNIQUE (tenant_id, clinical_record_id, version)` is one row per
   `(record, version)` (R8); `supersedes_version` names the version a correction replaces (R6), and
   the composite foreign keys are tenant-bound so a row can never reference another tenant's record
   or patient.

Two deliberate resolutions of open items are recorded here rather than hidden:

- **The timeline index is on `created_at`, not `signed_at`.** `03-design.md` records that choice as
  an open item; `signed_at` is NULL for every unsigned record, so a timeline ordered by it cannot be
  chronological. The keyset read orders by `created_at DESC, id DESC` and this index serves it.
- **`clinical_record_versions.signed_at` is not written by this slice.** The design fixes the
  application role's privileges on that table at exactly `SELECT, INSERT`, and the trigger refuses
  every `UPDATE` for every role, so no permitted statement can set a column on an existing version
  row. The signature clock is `clinical_records.signed_at` — the column the design's own privilege
  block grants for exactly that purpose — and the `clinical_record.write` audit event written on the
  same transaction is the durable per-version signature evidence. Resolving where a per-version
  signature should live is reported as an open item; inventing an `UPDATE` grant to satisfy it would
  break the feature's own S7-S11 immutability suite.
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "d4c9b7a1e5f2"
down_revision = "b7c1d9e4f2a3"
branch_labels = None
depends_on = None

# Raw SQL, so the naming convention cannot rewrite the policy names or the setting key.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_CLINICAL_TABLES = ("clinical_records", "clinical_record_versions")

# The composite foreign keys are named explicitly in the models, so the names are pinned here with
# the exact spelling the models declare — the convention would render `fk_..._tenant_id_patients`
# and drop the second column from the name.
_FK_CLINICAL_RECORDS_PATIENT = "fk_clinical_records_tenant_id_patient_id_patients"
_FK_VERSIONS_RECORD = "fk_clinical_record_versions_tenant_id_clinical_record_id"

_IMMUTABLE_FUNCTION = "clinos_clinical_record_versions_immutable"
_IMMUTABLE_TRIGGER = "trg_clinical_record_versions_immutable"
_IMMUTABLE_MESSAGE = (
    "CLINICAL_RECORD_VERSION_IMMUTABLE: clinical record versions are append-only; "
    "append a new version instead of altering this one"
)


def _enable_forced_rls(table: str) -> None:
    """Turn the policy on, force it on the owner, and declare both halves of the design's policy."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY pol_{table}_tenant_access ON {table} "
        "AS PERMISSIVE FOR ALL TO PUBLIC "
        f"USING ({_TENANT_MATCH}) WITH CHECK ({_TENANT_MATCH})"
    )
    op.execute(
        f"CREATE POLICY pol_{table}_tenant_isolation ON {table} "
        "AS RESTRICTIVE FOR ALL TO PUBLIC "
        f"USING ({_TENANT_MATCH}) WITH CHECK ({_TENANT_MATCH})"
    )


def upgrade() -> None:
    op.create_table(
        "clinical_records",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "record_type IN ('NOTE', 'OBSERVATION', 'HISTORY', 'ADDENDUM', 'RESULT')",
            name=op.f("ck_clinical_records_record_type"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["user.id"],
            name=op.f("fk_clinical_records_author_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name=_FK_CLINICAL_RECORDS_PATIENT,
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_clinical_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinical_records")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_clinical_records_tenant_id_id"),
    )
    op.create_index(
        "ix_clinical_records_tenant_patient_created_at",
        "clinical_records",
        ["tenant_id", "patient_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "clinical_record_versions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("clinical_record_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("body_format", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_version", sa.Integer(), nullable=True),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "signature_digest", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.CheckConstraint(
            "body_format IN ('MARKDOWN', 'PLAIN')",
            name=op.f("ck_clinical_record_versions_body_format"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_clinical_record_versions_version_minimum")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["user.id"],
            name=op.f("fk_clinical_record_versions_author_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "clinical_record_id"],
            ["clinical_records.tenant_id", "clinical_records.id"],
            name=_FK_VERSIONS_RECORD,
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_clinical_record_versions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinical_record_versions")),
        sa.UniqueConstraint(
            "tenant_id",
            "clinical_record_id",
            "version",
            name="uq_clinical_record_versions_tenant_record_version",
        ),
    )
    # The narrative full-text index. `to_tsvector` over the single `body` column, GIN, partial on
    # non-empty revisions. The predicate deliberately contains no `now()`: a volatile expression in
    # an index predicate is not immutable and the planner will not use the index.
    op.create_index(
        "ix_clinical_record_versions_body_fts",
        "clinical_record_versions",
        [sa.text("to_tsvector('english'::regconfig, body)")],
        unique=False,
        postgresql_using="gin",
        postgresql_where=sa.text("body <> ''"),
    )

    for table in _CLINICAL_TABLES:
        _enable_forced_rls(table)

    # The trigger: defence in depth, and the only control that binds the owner and the migration
    # role. `FOR EACH STATEMENT` because the design names a statement-level trigger; there is no
    # `WHEN` clause and no role check, so there is no shape of `UPDATE`/`DELETE` it lets through.
    op.execute(
        f"CREATE FUNCTION {_IMMUTABLE_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN RAISE EXCEPTION '{_IMMUTABLE_MESSAGE}' "
        "USING ERRCODE = 'raise_exception'; END $$"
    )
    op.execute(
        f"CREATE TRIGGER {_IMMUTABLE_TRIGGER} "
        "BEFORE UPDATE OR DELETE ON clinical_record_versions "
        f"FOR EACH STATEMENT EXECUTE FUNCTION {_IMMUTABLE_FUNCTION}()"
    )

    # Least privilege for the application role. `clinos_app` was created by the patients migration
    # and holds no ownership and no BYPASSRLS.
    op.execute("GRANT SELECT, INSERT ON clinical_records TO clinos_app")
    op.execute(
        "GRANT UPDATE (current_version, signed_at, deleted_at) "
        "ON clinical_records TO clinos_app"
    )
    op.execute("REVOKE DELETE, TRUNCATE ON clinical_records FROM clinos_app")
    # Exactly SELECT, INSERT — the grant is the primary immutability control (R13), and the feature's
    # S11 assertion reads this exact set back out of `information_schema.role_table_grants`.
    op.execute("GRANT SELECT, INSERT ON clinical_record_versions TO clinos_app")
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON clinical_record_versions FROM clinos_app"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER {_IMMUTABLE_TRIGGER} ON clinical_record_versions")
    op.execute(f"DROP FUNCTION {_IMMUTABLE_FUNCTION}()")
    for table in reversed(_CLINICAL_TABLES):
        op.execute(f"DROP POLICY pol_{table}_tenant_isolation ON {table}")
        op.execute(f"DROP POLICY pol_{table}_tenant_access ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_clinical_record_versions_body_fts",
        table_name="clinical_record_versions",
        postgresql_using="gin",
        postgresql_where=sa.text("body <> ''"),
    )
    op.drop_table("clinical_record_versions")
    op.drop_index(
        "ix_clinical_records_tenant_patient_created_at", table_name="clinical_records"
    )
    op.drop_table("clinical_records")
