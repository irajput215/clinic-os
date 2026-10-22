"""appointment hours per weekday, slot length, and the booking-email outbox

Revision ID: d8e3f1a6c4b2
Revises: b7d2e4f6a8c1
Create Date: 2026-10-08 14:20:00.000000

Contract: `docs2/sdlc/04-calendar-and-booking/api.md`, "Clinic hours, slot length and booking
emails"; scheduling: `docs/reference/decisions/D-009-scheduled-jobs-and-booking-reminders.md`.

* `appointment_settings` loses `opens_at`, `closes_at` and `working_days` (one interval for every
  working day) and gains `slot_minutes` (`ck_appointment_settings_slot_minutes`, default 15).
* `appointment_hours`: seven rows per configured clinic, one per ISO weekday; closed = both times
  `NULL`. Each existing settings row is copied onto it: its interval on its working days, the other
  days closed. Nothing is lost, and slots are offered exactly where they were (the step changes to
  15 minutes, as the contract records).
* `appointment_notifications`: the outbox. `UNIQUE (tenant_id, appointment_id, kind)`.

All three are tenant tables with forced RLS (the same permissive + restrictive pair the appointments
migration created, `NULLIF` guard included). The application role may now write the settings and the
hours (`SELECT, INSERT, UPDATE`; no `DELETE`: closing a day is an `UPDATE`) and the outbox (`SELECT,
INSERT, UPDATE`; no `DELETE`).

The downgrade folds the hours back into one interval (earliest opening to latest closing over the open
days; a clinic closed all week gets the old defaults) and drops the outbox. That interval can be wider
than the hours were, which is the only lossy step, and it only runs on a rollback.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'd8e3f1a6c4b2'
down_revision = 'b7d2e4f6a8c1'
branch_labels = None
depends_on = None

_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_ON_THE_MARK = (
    "extract(minute FROM {c})::int % 5 = 0 AND extract(second FROM {c}) = 0"
)


def _rls(table: str) -> None:
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


def upgrade():
    op.add_column(
        'appointment_settings',
        sa.Column('slot_minutes', sa.SmallInteger(), server_default='15', nullable=False),
    )
    op.create_check_constraint(
        op.f('ck_appointment_settings_slot_minutes'),
        'appointment_settings',
        'slot_minutes IN (10, 15, 20, 30, 60)',
    )

    op.create_table(
        'appointment_hours',
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('weekday', sa.SmallInteger(), nullable=False),
        sa.Column('opens_at', sa.Time(), nullable=True),
        sa.Column('closes_at', sa.Time(), nullable=True),
        sa.CheckConstraint(
            '(opens_at IS NULL) = (closes_at IS NULL)',
            name=op.f('ck_appointment_hours_open_or_closed'),
        ),
        sa.CheckConstraint(
            'opens_at IS NULL OR ('
            + _ON_THE_MARK.format(c='opens_at')
            + ' AND '
            + _ON_THE_MARK.format(c='closes_at')
            + ')',
            name=op.f('ck_appointment_hours_on_the_mark'),
        ),
        sa.CheckConstraint(
            'opens_at IS NULL OR closes_at > opens_at',
            name=op.f('ck_appointment_hours_opens_before_closes'),
        ),
        sa.CheckConstraint(
            'weekday BETWEEN 1 AND 7', name=op.f('ck_appointment_hours_weekday')
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['appointment_settings.tenant_id'],
            name='fk_appointment_hours_tenant_settings',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('tenant_id', 'weekday', name=op.f('pk_appointment_hours')),
    )

    # Copy each clinic's one interval onto its working days; every other day closed. The old checks
    # guaranteed `closes_at > opens_at`; a time off the 5-minute mark is rounded down to it (and the
    # closing time kept after the opening), so the copy always satisfies the new checks.
    op.execute(
        """
        INSERT INTO appointment_hours (tenant_id, weekday, opens_at, closes_at)
        SELECT s.tenant_id, d.weekday,
               CASE WHEN d.weekday = ANY(s.working_days) THEN o.opens END,
               CASE WHEN d.weekday = ANY(s.working_days)
                    THEN greatest(c.closes, o.opens + interval '5 minutes') END
        FROM appointment_settings s
        CROSS JOIN generate_series(1, 7) AS d(weekday)
        CROSS JOIN LATERAL (SELECT s.opens_at - make_interval(
            mins => extract(minute FROM s.opens_at)::int % 5,
            secs => extract(second FROM s.opens_at)) AS opens) AS o
        CROSS JOIN LATERAL (SELECT s.closes_at - make_interval(
            mins => extract(minute FROM s.closes_at)::int % 5,
            secs => extract(second FROM s.closes_at)) AS closes) AS c
        """
    )

    op.drop_constraint(
        op.f('ck_appointment_settings_hours'), 'appointment_settings', type_='check'
    )
    op.drop_constraint(
        op.f('ck_appointment_settings_working_days'), 'appointment_settings', type_='check'
    )
    op.drop_column('appointment_settings', 'closes_at')
    op.drop_column('appointment_settings', 'opens_at')
    op.drop_column('appointment_settings', 'working_days')

    op.create_table(
        'appointment_notifications',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('appointment_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('outcome', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.SmallInteger(), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'SENT') = (sent_at IS NOT NULL)",
            name=op.f('ck_appointment_notifications_sent_at'),
        ),
        sa.CheckConstraint(
            "kind IN ('CONFIRMATION', 'REMINDER')",
            name=op.f('ck_appointment_notifications_kind'),
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN"
            " ('BOOKING_NOT_LIVE', 'STARTED', 'NO_EMAIL', 'SMTP_ERROR')",
            name=op.f('ck_appointment_notifications_outcome'),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENDING', 'SENT', 'SKIPPED', 'FAILED')",
            name=op.f('ck_appointment_notifications_status'),
        ),
        sa.CheckConstraint(
            'attempts >= 0', name=op.f('ck_appointment_notifications_attempts')
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'appointment_id'],
            ['appointments.tenant_id', 'appointments.id'],
            name='fk_appointment_notifications_tenant_appointment',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['tenants.id'],
            name=op.f('fk_appointment_notifications_tenant_id_tenants'),
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_appointment_notifications')),
        sa.UniqueConstraint(
            'tenant_id',
            'appointment_id',
            'kind',
            name='uq_appointment_notifications_one_per_kind',
        ),
    )
    op.create_index(
        'ix_appointment_notifications_tenant_status_due',
        'appointment_notifications',
        ['tenant_id', 'status', 'due_at'],
        unique=False,
    )

    for table in ('appointment_hours', 'appointment_notifications'):
        _rls(table)
    for table in ('appointment_settings', 'appointment_hours', 'appointment_notifications'):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO clinos_app")
        op.execute(f"REVOKE DELETE, TRUNCATE ON {table} FROM clinos_app")


def downgrade():
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON appointment_settings FROM clinos_app"
    )
    op.drop_index(
        'ix_appointment_notifications_tenant_status_due',
        table_name='appointment_notifications',
    )
    op.drop_table('appointment_notifications')

    op.add_column('appointment_settings', sa.Column('opens_at', sa.Time(), nullable=True))
    op.add_column('appointment_settings', sa.Column('closes_at', sa.Time(), nullable=True))
    op.add_column(
        'appointment_settings',
        sa.Column('working_days', sa.ARRAY(sa.SmallInteger()), nullable=True),
    )
    op.execute(
        """
        UPDATE appointment_settings s SET
            opens_at = coalesce(h.opens, time '09:00'),
            closes_at = coalesce(h.closes, time '17:00'),
            working_days = coalesce(h.days, ARRAY[1, 2, 3, 4, 5]::smallint[])
        FROM (
            SELECT s2.tenant_id,
                   min(ah.opens_at) AS opens,
                   max(ah.closes_at) AS closes,
                   array_agg(ah.weekday ORDER BY ah.weekday)
                       FILTER (WHERE ah.opens_at IS NOT NULL) AS days
            FROM appointment_settings s2
            LEFT JOIN appointment_hours ah ON ah.tenant_id = s2.tenant_id
            GROUP BY s2.tenant_id
        ) AS h
        WHERE h.tenant_id = s.tenant_id
        """
    )
    op.alter_column('appointment_settings', 'opens_at', nullable=False)
    op.alter_column('appointment_settings', 'closes_at', nullable=False)
    op.alter_column('appointment_settings', 'working_days', nullable=False)
    op.create_check_constraint(
        op.f('ck_appointment_settings_hours'), 'appointment_settings', 'closes_at > opens_at'
    )
    op.create_check_constraint(
        op.f('ck_appointment_settings_working_days'),
        'appointment_settings',
        "cardinality(working_days) BETWEEN 1 AND 7"
        " AND working_days <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]",
    )
    op.drop_table('appointment_hours')
    op.drop_constraint(
        op.f('ck_appointment_settings_slot_minutes'), 'appointment_settings', type_='check'
    )
    op.drop_column('appointment_settings', 'slot_minutes')
