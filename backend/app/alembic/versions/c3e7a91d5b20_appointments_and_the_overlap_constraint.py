"""appointments and appointment_settings: tables, overlap constraint, triggers, RLS and grants

Revision ID: c3e7a91d5b20
Revises: b9fa64996260
Create Date: 2026-10-07 10:00:00.000000

Feature 04, calendar and booking (`docs2/sdlc/04-calendar-and-booking/api.md`, agreed 2026-10-07 by
the owner). The technique is the TGA grain migration's (`d4f8c2a9b7e1`), copied on purpose:

1. **`no_overlapping_appointments`** - a partial `EXCLUDE USING gist (tenant_id WITH =,
   practitioner_id WITH =, during WITH &&) WHERE (status NOT IN ('CANCELLED', 'NO_SHOW'))`. R3: a
   practitioner cannot be double-booked, and the database is what refuses it, including for two
   concurrent requests. `btree_gist` is already created by `d4f8c2a9b7e1`; the statement is repeated
   (`IF NOT EXISTS`) so this migration does not silently depend on another feature's. It is a trusted
   extension, so a non-superuser owner may create it.
2. **`trg_appointment_during`** derives `during = tstzrange(starts_at, ends_at, '[)')` on every write,
   and `ck_appointments_during` pins it, so the indexed range cannot drift from the row's instants.
3. **`trg_appointment_status_guard`** - R4's machine in SQL (the service refuses first with `409`), and
   the booking's who/what/when are immutable once written. Named to sort after the derivation
   trigger, because triggers fire in name order.
4. **RLS** `ENABLE` + `FORCE` on both tables, a permissive tenant policy and a restrictive floor, with
   the `NULLIF` guard so a missing tenant matches nothing - byte for byte the pattern of the TGA tables.
5. **Grants**: `clinos_app` may read, insert and update a booking, never delete one (a cancelled
   booking is a status, not a deletion); `appointment_settings` is read-only to the application (no
   route edits availability in this phase).
6. **`ck_audit_log_resource_type`** gains `APPOINTMENT`, the resource type of the two actions this
   feature registers in the closed catalogue (`appointment.create`, `appointment.state_change`).

No `ALTER ... OWNER`: production migrates as a non-superuser owner (HANDOFF §4 trap 1).
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects.postgresql import TSTZRANGE

# revision identifiers, used by Alembic.
revision = "c3e7a91d5b20"
down_revision = "b9fa64996260"
branch_labels = None
depends_on = None

_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_DURATION = (
    "(type = 'NURSE_TRIAGE' AND ends_at - starts_at = interval '15 minutes')"
    " OR (type = 'INITIAL_CONSULT' AND ends_at - starts_at = interval '30 minutes')"
    " OR (type = 'FOLLOW_UP' AND ends_at - starts_at = interval '15 minutes')"
)

_DURING_FUNCTION = """
CREATE OR REPLACE FUNCTION appointment_during() RETURNS trigger AS $fn$
BEGIN
    NEW.during := tstzrange(NEW.starts_at, NEW.ends_at, '[)');
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

_STATUS_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION appointment_status_guard() RETURNS trigger AS $fn$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT (
            (OLD.status = 'BOOKED' AND NEW.status IN ('CONFIRMED', 'ARRIVED', 'CANCELLED', 'NO_SHOW'))
            OR (OLD.status = 'CONFIRMED' AND NEW.status IN ('ARRIVED', 'CANCELLED', 'NO_SHOW'))
            OR (OLD.status = 'ARRIVED' AND NEW.status = 'COMPLETED')
        ) THEN
            RAISE EXCEPTION
                'ILLEGAL_STATE_TRANSITION: % -> % is not a permitted transition',
                OLD.status, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF (NEW.tenant_id, NEW.patient_id, NEW.practitioner_id, NEW.type, NEW.source,
        NEW.starts_at, NEW.ends_at, NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       (OLD.tenant_id, OLD.patient_id, OLD.practitioner_id, OLD.type, OLD.source,
        OLD.starts_at, OLD.ends_at, OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'APPOINTMENT_IMMUTABLE: only the status of a booking can change'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

_RESOURCE_TYPES_BEFORE = (
    "'PATIENT', 'CLINICAL_RECORD', 'PRESCRIPTION', 'TGA_APPROVAL', 'TGA_DOCUMENT', 'USER',"
    " 'TENANT', 'SESSION', 'AUDIT', 'REPORT', 'INTEGRATION', 'EXPORT'"
)


def _resource_type_check(values: str) -> None:
    op.execute("ALTER TABLE audit_log DROP CONSTRAINT ck_audit_log_resource_type")
    op.execute(
        "ALTER TABLE audit_log ADD CONSTRAINT ck_audit_log_resource_type "
        f"CHECK (resource_type IN ({values}))"
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "appointments",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("practitioner_id", sa.Uuid(), nullable=False),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("during", TSTZRANGE(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('NURSE_TRIAGE', 'INITIAL_CONSULT', 'FOLLOW_UP')",
            name=op.f("ck_appointments_type"),
        ),
        sa.CheckConstraint(
            "status IN ('BOOKED', 'CONFIRMED', 'ARRIVED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')",
            name=op.f("ck_appointments_status"),
        ),
        sa.CheckConstraint(
            "source IN ('STAFF', 'PUBLIC_BOOKING')", name=op.f("ck_appointments_source")
        ),
        sa.CheckConstraint(_DURATION, name=op.f("ck_appointments_duration")),
        sa.CheckConstraint(
            "during = tstzrange(starts_at, ends_at, '[)')",
            name=op.f("ck_appointments_during"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_appointments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_appointments_tenant_patient",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_appointments_tenant_id_id"),
    )
    op.create_index(
        "ix_appointments_tenant_starts", "appointments", ["tenant_id", "starts_at"]
    )
    op.create_index(
        "ix_appointments_tenant_patient_starts",
        "appointments",
        ["tenant_id", "patient_id", "starts_at"],
    )

    op.create_table(
        "appointment_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=False),
        sa.Column("closes_at", sa.Time(), nullable=False),
        sa.Column("working_days", sa.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "closes_at > opens_at", name=op.f("ck_appointment_settings_hours")
        ),
        sa.CheckConstraint(
            "cardinality(working_days) BETWEEN 1 AND 7"
            " AND working_days <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]",
            name=op.f("ck_appointment_settings_working_days"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_appointment_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_appointment_settings")),
    )

    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT no_overlapping_appointments "
        "EXCLUDE USING gist ("
        " tenant_id WITH =, practitioner_id WITH =, during WITH &&"
        ") WHERE (status NOT IN ('CANCELLED', 'NO_SHOW'))"
    )

    op.execute(_DURING_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_appointment_during "
        "BEFORE INSERT OR UPDATE ON appointments "
        "FOR EACH ROW EXECUTE FUNCTION appointment_during()"
    )
    op.execute(_STATUS_GUARD_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_appointment_status_guard "
        "BEFORE UPDATE ON appointments "
        "FOR EACH ROW EXECUTE FUNCTION appointment_status_guard()"
    )

    for table in ("appointments", "appointment_settings"):
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

    op.execute("GRANT SELECT, INSERT, UPDATE ON appointments TO clinos_app")
    op.execute("REVOKE DELETE, TRUNCATE ON appointments FROM clinos_app")
    op.execute("GRANT SELECT ON appointment_settings TO clinos_app")
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON appointment_settings FROM clinos_app"
    )

    _resource_type_check(f"{_RESOURCE_TYPES_BEFORE}, 'APPOINTMENT'")


def downgrade() -> None:
    # Fails loudly if appointment events were ever written: the trail is append-only, so a
    # downgrade past them is not something this migration may quietly allow.
    _resource_type_check(_RESOURCE_TYPES_BEFORE)
    op.execute("DROP TABLE IF EXISTS appointment_settings")
    op.execute("DROP TABLE IF EXISTS appointments")
    op.execute("DROP FUNCTION IF EXISTS appointment_status_guard()")
    op.execute("DROP FUNCTION IF EXISTS appointment_during()")
