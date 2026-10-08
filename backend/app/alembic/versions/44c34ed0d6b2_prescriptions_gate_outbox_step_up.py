"""prescriptions, prescription_events, dispatch_attempts and step_up_grants; the prescription:read code

Revision ID: 44c34ed0d6b2
Revises: c3e7a91d5b20
Create Date: 2026-10-07 17:18:27.118822

Milestone 2, phase 2D (`docs2/sdlc/07-script-queue/api.md`, agreed 2026-10-07 by the owner). Feature
documents: `docs/features/10-prescription-safety-gate/`, `11-prescribing/`, `13-integration-boundaries/`
and, for the step-up grant, `02-authentication/03-design.md`.

## Database controls created here

* `trg_prescriptions_lock_signed` - the FEAT-11 state machine for every role, and
  `SIGNED_IS_IMMUTABLE`: once a row leaves `DRAFT`, its payload, grain and signature never change.
* `trg_dispatch_attempts_guard` - an outbox row's identity is immutable, its state only moves forward
  (`QUEUED -> DISPATCHED | FAILED | REQUIRES_RECONCILIATION -> DISPATCHED | FAILED`), and a resolved row
  is frozen.
* RLS `ENABLE` + `FORCE` on all four tables, a permissive policy that grants the caller its own rows
  and a restrictive `NULLIF` floor, `TO PUBLIC` like every earlier tenant table (the deployed
  connection is the owner; `FORCE` binds it). `prescription_events` has no `UPDATE`/`DELETE` policy;
  `dispatch_attempts` and `step_up_grants` have no `DELETE` policy.
* Grants for `clinos_app`: `prescriptions` and `dispatch_attempts` `SELECT, INSERT, UPDATE` (no
  `DELETE`/`TRUNCATE`); `prescription_events` `SELECT, INSERT` only; `step_up_grants` `SELECT, INSERT,
  UPDATE`. The documents want outcome columns of `dispatch_attempts` written by a separate worker role;
  no such role exists, so the guard trigger is the control and the deviation is recorded.

## The permission code

`prescription:read` is seeded and granted to `PRACTICE_OWNER`, `AUTHORISED_PRESCRIBER`, `DOCTOR` and
`NURSE` in every existing tenant, from `catalog.py` (the same non-hermetic, idempotent shape as
`e5a9d3b8c2f4`). Recorded under "Controls changed".

No `ALTER ... OWNER`, no superuser-only statement: proven against a non-superuser owner.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

from app.modules.users_roles.catalog import PERMISSION_CATALOGUE, SYSTEM_ROLE_CATALOGUE


# revision identifiers, used by Alembic.
revision = '44c34ed0d6b2'
down_revision = 'c3e7a91d5b20'
branch_labels = None
depends_on = None

_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
NEW_PERMISSION = "prescription:read"

# FEAT-11 "The state machine", written out rather than imported so this revision's meaning never
# changes after it is applied. `app.modules.prescriptions.models.LEGAL_TRANSITIONS` is asserted equal
# by `tests/prescriptions/test_database_controls.py`.
_PRESCRIPTION_TRANSITIONS = (
    ("DRAFT", "SIGNED"),
    ("DRAFT", "CANCELLED"),
    ("SIGNED", "QUEUED"),
    ("SIGNED", "BLOCKED"),
    ("SIGNED", "CANCELLED"),
    ("BLOCKED", "QUEUED"),
    ("BLOCKED", "CANCELLED"),
    ("QUEUED", "DISPATCHED"),
    ("QUEUED", "FAILED"),
    ("QUEUED", "REQUIRES_RECONCILIATION"),
    ("FAILED", "QUEUED"),
    ("FAILED", "CANCELLED"),
    ("REQUIRES_RECONCILIATION", "DISPATCHED"),
    ("REQUIRES_RECONCILIATION", "FAILED"),
    ("DISPATCHED", "REVERSED"),
)
_PAYLOAD_COLUMNS = (
    "patient_id",
    "prescriber_id",
    "drafted_by",
    "medicine_name",
    "tga_category",
    "dosage_form",
    "dose_instruction",
    "quantity",
    "repeats",
    "triage_outcome",
    "conventional_therapy",
    "date_of_service",
    "payload_hash",
    "signed_at",
    "signed_by",
)
_ATTEMPT_IDENTITY = (
    "tenant_id",
    "prescription_id",
    "approval_id",
    "idempotency_key",
    "attempt_seq",
    "request_payload_hash",
    "requested_by",
    "requested_at",
)
_ATTEMPT_ALL = (
    *_ATTEMPT_IDENTITY,
    "state",
    "provider",
    "provider_reference",
    "outcome_class",
    "error_class",
    "resolution_reason",
    "latency_ms",
    "claimed_at",
    "resolved_at",
)


def _row(prefix: str, columns: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"{prefix}.{column}" for column in columns) + ")"


def _pairs(pairs: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(f"('{a}', '{b}')" for a, b in pairs)


_LOCK_SIGNED = f"""
CREATE OR REPLACE FUNCTION prescriptions_lock_signed() RETURNS trigger AS $fn$
BEGIN
    IF (NEW.id, NEW.tenant_id, NEW.created_at) IS DISTINCT FROM (OLD.id, OLD.tenant_id, OLD.created_at) THEN
        RAISE EXCEPTION 'SIGNED_IS_IMMUTABLE: a prescription''s identity cannot change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.state IS DISTINCT FROM OLD.state
       AND (OLD.state, NEW.state) NOT IN ({_pairs(_PRESCRIPTION_TRANSITIONS)}) THEN
        RAISE EXCEPTION 'INVALID_STATE_TRANSITION: % -> % is not a permitted transition',
            OLD.state, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.state <> 'DRAFT'
       AND {_row("NEW", _PAYLOAD_COLUMNS)} IS DISTINCT FROM {_row("OLD", _PAYLOAD_COLUMNS)} THEN
        RAISE EXCEPTION 'SIGNED_IS_IMMUTABLE: a signed prescription cannot be edited; amend by addendum'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.state IN ('CANCELLED', 'REVERSED')
       AND (NEW.state, NEW.approval_id) IS DISTINCT FROM (OLD.state, OLD.approval_id) THEN
        RAISE EXCEPTION 'SIGNED_IS_IMMUTABLE: a terminal prescription is immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

_ATTEMPT_GUARD = f"""
CREATE OR REPLACE FUNCTION dispatch_attempts_guard() RETURNS trigger AS $fn$
BEGIN
    IF OLD.state IN ('DISPATCHED', 'FAILED')
       AND {_row("NEW", _ATTEMPT_ALL)} IS DISTINCT FROM {_row("OLD", _ATTEMPT_ALL)} THEN
        RAISE EXCEPTION 'DISPATCH_ATTEMPT_RESOLVED: a resolved dispatch attempt is immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    IF {_row("NEW", _ATTEMPT_IDENTITY)} IS DISTINCT FROM {_row("OLD", _ATTEMPT_IDENTITY)} THEN
        RAISE EXCEPTION 'DISPATCH_ATTEMPT_IDENTITY_IMMUTABLE: the intent of a dispatch cannot change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
        (OLD.state = 'QUEUED' AND NEW.state IN ('DISPATCHED', 'FAILED', 'REQUIRES_RECONCILIATION'))
        OR (OLD.state = 'REQUIRES_RECONCILIATION' AND NEW.state IN ('DISPATCHED', 'FAILED'))
    ) THEN
        RAISE EXCEPTION 'INVALID_STATE_TRANSITION: dispatch attempt % -> %', OLD.state, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('step_up_grants',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('operation', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("expires_at <= issued_at + interval '120 seconds'", name=op.f('ck_step_up_grants_max_lifetime')),
    sa.CheckConstraint("operation IN ('prescription.sign', 'prescription.dispatch')", name=op.f('ck_step_up_grants_operation')),
    sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_step_up_grants_token_hash')),
    sa.CheckConstraint('consumed_at IS NULL OR consumed_at >= issued_at', name=op.f('ck_step_up_grants_consumed_after_issue')),
    sa.CheckConstraint('expires_at > issued_at', name=op.f('ck_step_up_grants_window')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_step_up_grants_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_step_up_grants_user_id_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_step_up_grants')),
    sa.UniqueConstraint('token_hash', name='uq_step_up_grants_token_hash')
    )
    op.create_index('ix_step_up_grants_tenant_user_issued', 'step_up_grants', ['tenant_id', 'user_id', 'issued_at'], unique=False)
    op.create_table('prescriptions',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('patient_id', sa.Uuid(), nullable=False),
    sa.Column('prescriber_id', sa.Uuid(), nullable=False),
    sa.Column('drafted_by', sa.Uuid(), nullable=False),
    sa.Column('medicine_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('tga_category', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('dosage_form', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('dose_instruction', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('repeats', sa.SmallInteger(), nullable=False),
    sa.Column('triage_outcome', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('conventional_therapy', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('date_of_service', sa.Date(), nullable=False),
    sa.Column('state', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('approval_id', sa.Uuid(), nullable=True),
    sa.Column('payload_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signed_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("char_length(conventional_therapy) BETWEEN 1 AND 300 AND conventional_therapy !~ '[[:cntrl:]]'", name=op.f('ck_prescriptions_conventional_therapy')),
    sa.CheckConstraint("dosage_form ~ '^[A-Z0-9][A-Z0-9_]{0,31}$'", name=op.f('ck_prescriptions_dosage_form')),
    sa.CheckConstraint("char_length(dose_instruction) BETWEEN 1 AND 500 AND dose_instruction !~ '[[:cntrl:]]'", name=op.f('ck_prescriptions_dose_instruction')),
    sa.CheckConstraint("char_length(medicine_name) BETWEEN 1 AND 200 AND medicine_name !~ '[[:cntrl:]]'", name=op.f('ck_prescriptions_medicine_name')),
    sa.CheckConstraint("payload_hash IS NULL OR payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_prescriptions_payload_hash')),
    sa.CheckConstraint("state IN ('DRAFT', 'CANCELLED') OR (signed_at IS NOT NULL AND signed_by IS NOT NULL AND payload_hash IS NOT NULL AND approval_id IS NOT NULL)", name=op.f('ck_prescriptions_signed_evidence')),
    sa.CheckConstraint("state IN ('DRAFT', 'SIGNED', 'BLOCKED', 'QUEUED', 'DISPATCHED', 'FAILED', 'REQUIRES_RECONCILIATION', 'CANCELLED', 'REVERSED')", name=op.f('ck_prescriptions_state')),
    sa.CheckConstraint("tga_category ~ '^[A-Z0-9][A-Z0-9_]{0,31}$'", name=op.f('ck_prescriptions_tga_category')),
    sa.CheckConstraint("char_length(triage_outcome) BETWEEN 1 AND 300 AND triage_outcome !~ '[[:cntrl:]]'", name=op.f('ck_prescriptions_triage_outcome')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_prescriptions_quantity')),
    sa.CheckConstraint('repeats BETWEEN 0 AND 12', name=op.f('ck_prescriptions_repeats')),
    sa.CheckConstraint('signed_by IS NULL OR signed_by = prescriber_id', name=op.f('ck_prescriptions_signer_is_prescriber')),
    sa.ForeignKeyConstraint(['tenant_id', 'approval_id'], ['tga_approvals.tenant_id', 'tga_approvals.id'], name='fk_prescriptions_tenant_approval', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'patient_id'], ['patients.tenant_id', 'patients.id'], name='fk_prescriptions_tenant_patient', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_prescriptions_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prescriptions')),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_prescriptions_tenant_id_id')
    )
    op.create_index('ix_prescriptions_tenant_created', 'prescriptions', ['tenant_id', 'created_at', 'id'], unique=False)
    op.create_index('ix_prescriptions_tenant_patient_created', 'prescriptions', ['tenant_id', 'patient_id', 'created_at'], unique=False)
    op.create_index('ix_prescriptions_tenant_prescriber', 'prescriptions', ['tenant_id', 'prescriber_id'], unique=False)
    op.create_index('ix_prescriptions_tenant_state', 'prescriptions', ['tenant_id', 'state'], unique=False)
    op.create_table('dispatch_attempts',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('prescription_id', sa.Uuid(), nullable=False),
    sa.Column('approval_id', sa.Uuid(), nullable=False),
    sa.Column('idempotency_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('attempt_seq', sa.Integer(), nullable=False),
    sa.Column('state', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('provider_reference', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('request_payload_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('outcome_class', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('error_class', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('resolution_reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("error_class IS NULL OR error_class ~ '^[A-Z][A-Z0-9_]{0,63}$'", name=op.f('ck_dispatch_attempts_error_class')),
    sa.CheckConstraint("idempotency_key ~ '^[0-9a-f]{64}$'", name=op.f('ck_dispatch_attempts_idempotency_key')),
    sa.CheckConstraint("outcome_class IS NULL OR outcome_class IN ('CONFIRMED', 'REJECTED', 'UNKNOWN')", name=op.f('ck_dispatch_attempts_outcome_class')),
    sa.CheckConstraint("provider IS NULL OR provider ~ '^[a-z][a-z0-9_]{0,31}$'", name=op.f('ck_dispatch_attempts_provider')),
    sa.CheckConstraint("provider_reference IS NULL OR provider_reference ~ '^[A-Za-z0-9][A-Za-z0-9/_.:-]{0,127}$'", name=op.f('ck_dispatch_attempts_provider_reference')),
    sa.CheckConstraint("request_payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_dispatch_attempts_request_payload_hash')),
    sa.CheckConstraint("resolution_reason IS NULL OR resolution_reason ~ '^[A-Z][A-Z0-9_]{0,63}$'", name=op.f('ck_dispatch_attempts_resolution_reason')),
    sa.CheckConstraint("state <> 'DISPATCHED' OR (outcome_class = 'CONFIRMED' AND provider IS NOT NULL AND resolved_at IS NOT NULL)", name=op.f('ck_dispatch_attempts_dispatched_confirmed')),
    sa.CheckConstraint("state IN ('QUEUED', 'DISPATCHED', 'FAILED', 'REQUIRES_RECONCILIATION')", name=op.f('ck_dispatch_attempts_state')),
    sa.CheckConstraint('attempt_seq >= 1', name=op.f('ck_dispatch_attempts_attempt_seq')),
    sa.CheckConstraint('latency_ms IS NULL OR latency_ms >= 0', name=op.f('ck_dispatch_attempts_latency_ms')),
    sa.ForeignKeyConstraint(['tenant_id', 'approval_id'], ['tga_approvals.tenant_id', 'tga_approvals.id'], name='fk_dispatch_attempts_tenant_approval', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'prescription_id'], ['prescriptions.tenant_id', 'prescriptions.id'], name='fk_dispatch_attempts_tenant_prescription', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_dispatch_attempts_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dispatch_attempts')),
    sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_dispatch_attempts_tenant_key'),
    sa.UniqueConstraint('tenant_id', 'prescription_id', 'attempt_seq', name='uq_dispatch_attempts_tenant_prescription_seq')
    )
    op.create_index('ix_dispatch_attempts_tenant_state_requested', 'dispatch_attempts', ['tenant_id', 'state', 'requested_at'], unique=False)
    op.create_index('uq_dispatch_attempts_one_live', 'dispatch_attempts', ['tenant_id', 'prescription_id'], unique=True, postgresql_where=sa.text("state IN ('QUEUED', 'REQUIRES_RECONCILIATION')"))
    op.create_table('prescription_events',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('prescription_id', sa.Uuid(), nullable=False),
    sa.Column('from_state', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('to_state', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("from_state IS NULL OR from_state IN ('DRAFT', 'SIGNED', 'BLOCKED', 'QUEUED', 'DISPATCHED', 'FAILED', 'REQUIRES_RECONCILIATION', 'CANCELLED', 'REVERSED')", name=op.f('ck_prescription_events_from_state')),
    sa.CheckConstraint("reason IS NULL OR reason ~ '^[A-Z][A-Z0-9_]{0,63}$'", name=op.f('ck_prescription_events_reason')),
    sa.CheckConstraint("to_state IN ('DRAFT', 'SIGNED', 'BLOCKED', 'QUEUED', 'DISPATCHED', 'FAILED', 'REQUIRES_RECONCILIATION', 'CANCELLED', 'REVERSED')", name=op.f('ck_prescription_events_to_state')),
    sa.CheckConstraint('from_state IS NULL OR from_state <> to_state', name=op.f('ck_prescription_events_transition')),
    sa.ForeignKeyConstraint(['tenant_id', 'prescription_id'], ['prescriptions.tenant_id', 'prescriptions.id'], name='fk_prescription_events_tenant_prescription', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_prescription_events_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prescription_events')),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_prescription_events_tenant_id_id')
    )
    op.create_index('ix_prescription_events_tenant_prescription_occurred', 'prescription_events', ['tenant_id', 'prescription_id', 'occurred_at'], unique=False)
    # ### end Alembic commands ###

    op.execute(_LOCK_SIGNED)
    op.execute(
        "CREATE TRIGGER trg_prescriptions_lock_signed BEFORE UPDATE ON prescriptions "
        "FOR EACH ROW EXECUTE FUNCTION prescriptions_lock_signed()"
    )
    op.execute(_ATTEMPT_GUARD)
    op.execute(
        "CREATE TRIGGER trg_dispatch_attempts_guard BEFORE UPDATE ON dispatch_attempts "
        "FOR EACH ROW EXECUTE FUNCTION dispatch_attempts_guard()"
    )

    tables = ("prescriptions", "prescription_events", "dispatch_attempts", "step_up_grants")
    for table in tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY pol_{table}_tenant_isolation ON {table} "
            "AS RESTRICTIVE FOR ALL TO PUBLIC "
            f"USING ({_TENANT_MATCH}) WITH CHECK ({_TENANT_MATCH})"
        )
    # `prescriptions`: the lifecycle row. No DELETE policy: never hard-deleted (FEAT-11 R14).
    # `dispatch_attempts` and `step_up_grants`: written and moved forward, never deleted.
    for table in ("prescriptions", "dispatch_attempts", "step_up_grants"):
        op.execute(
            f"CREATE POLICY pol_{table}_tenant_select ON {table} "
            f"AS PERMISSIVE FOR SELECT TO PUBLIC USING ({_TENANT_MATCH})"
        )
        op.execute(
            f"CREATE POLICY pol_{table}_tenant_insert ON {table} "
            f"AS PERMISSIVE FOR INSERT TO PUBLIC WITH CHECK ({_TENANT_MATCH})"
        )
        op.execute(
            f"CREATE POLICY pol_{table}_tenant_update ON {table} "
            f"AS PERMISSIVE FOR UPDATE TO PUBLIC "
            f"USING ({_TENANT_MATCH}) WITH CHECK ({_TENANT_MATCH})"
        )
    # `prescription_events`: append-only by policy as well as by grant.
    op.execute(
        "CREATE POLICY pol_prescription_events_tenant_select ON prescription_events "
        f"AS PERMISSIVE FOR SELECT TO PUBLIC USING ({_TENANT_MATCH})"
    )
    op.execute(
        "CREATE POLICY pol_prescription_events_tenant_insert ON prescription_events "
        f"AS PERMISSIVE FOR INSERT TO PUBLIC WITH CHECK ({_TENANT_MATCH})"
    )

    for table in ("prescriptions", "dispatch_attempts", "step_up_grants"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO clinos_app")
        op.execute(f"REVOKE DELETE, TRUNCATE ON {table} FROM clinos_app")
    op.execute("GRANT SELECT, INSERT ON prescription_events TO clinos_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON prescription_events FROM clinos_app")

    # The permission the queue read needs, granted to the roles whose bundle holds it.
    bind = op.get_bind()
    descriptions = dict(PERMISSION_CATALOGUE)
    assert NEW_PERMISSION in descriptions, "catalog.py must declare prescription:read first"
    bind.execute(
        sa.text(
            "INSERT INTO permissions (id, code, description) "
            "VALUES (gen_random_uuid(), :code, :description) ON CONFLICT (code) DO NOTHING"
        ),
        {"code": NEW_PERMISSION, "description": descriptions[NEW_PERMISSION]},
    )
    tenant_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM tenants"))]
    holders = [code for code, _name, bundle in SYSTEM_ROLE_CATALOGUE if NEW_PERMISSION in bundle]
    for tenant_id in tenant_ids:
        for role_code in holders:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id, tenant_id) "
                    "SELECT r.id, p.id, r.tenant_id "
                    "FROM roles r JOIN permissions p ON p.code = :permission_code "
                    "WHERE r.tenant_id = :tenant_id AND r.code = :role_code "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "tenant_id": tenant_id,
                    "role_code": role_code,
                    "permission_code": NEW_PERMISSION,
                },
            )


def downgrade():
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = :code)"
        ).bindparams(code=NEW_PERMISSION)
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=NEW_PERMISSION)
    )
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_prescription_events_tenant_prescription_occurred', table_name='prescription_events')
    op.drop_table('prescription_events')
    op.drop_index('uq_dispatch_attempts_one_live', table_name='dispatch_attempts', postgresql_where=sa.text("state IN ('QUEUED', 'REQUIRES_RECONCILIATION')"))
    op.drop_index('ix_dispatch_attempts_tenant_state_requested', table_name='dispatch_attempts')
    op.drop_table('dispatch_attempts')
    op.drop_index('ix_prescriptions_tenant_state', table_name='prescriptions')
    op.drop_index('ix_prescriptions_tenant_prescriber', table_name='prescriptions')
    op.drop_index('ix_prescriptions_tenant_patient_created', table_name='prescriptions')
    op.drop_index('ix_prescriptions_tenant_created', table_name='prescriptions')
    op.drop_table('prescriptions')
    op.drop_index('ix_step_up_grants_tenant_user_issued', table_name='step_up_grants')
    op.drop_table('step_up_grants')
    # ### end Alembic commands ###
    op.execute("DROP FUNCTION IF EXISTS dispatch_attempts_guard()")
    op.execute("DROP FUNCTION IF EXISTS prescriptions_lock_signed()")
