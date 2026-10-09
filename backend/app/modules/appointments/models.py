"""The `appointments` and `appointment_settings` tables.

Contract: `docs2/sdlc/04-calendar-and-booking/api.md` (agreed 2026-10-07, owner). Requirements:
`docs2/sdlc/04-calendar-and-booking/requirements.md` R1-R7.

## A practitioner cannot be double-booked, and the database is what says so (R3)

`no_overlapping_appointments` is a *partial* `EXCLUDE USING gist` over
`(tenant_id WITH =, practitioner_id WITH =, during WITH &&) WHERE status NOT IN ('CANCELLED',
'NO_SHOW')`, created by the migration. It is the TGA grain technique
(`app/modules/tga_approvals/models.py`), copied rather than re-invented:

* `during` is a stored `tstzrange(starts_at, ends_at, '[)')`, **derived** by the
  `trg_appointment_during` trigger on every write and pinned by `ck_appointments_during`, so the
  range the constraint indexes can never describe a time the row's own columns do not. `[)` makes
  back-to-back bookings legal: 09:00-09:15 and 09:15-09:30 do not overlap.
* Partial, so a cancelled or no-show booking frees its slot without being deleted.
* `btree_gist` supplies the equality operator classes (already created by `d4f8c2a9b7e1`).
* The constraint is declared here as an `Index` of the same name, for the reason the TGA model
  gives: PostgreSQL reports an `EXCLUDE` constraint's backing index to reflection as an index, and a
  same-named GiST index is the only declaration that keeps `alembic check` and
  `tests/core/test_schema_conventions.py` both honest.

## The duration is the type's, and the status machine is R4's, in the database too

`ck_appointments_duration` ties `ends_at - starts_at` to the type (R2), so the server-computed end
cannot be bypassed by a future caller. `trg_appointment_status_guard` refuses a status change outside
`LEGAL_TRANSITIONS` and any change to a booking's who/when/what once it exists - the service refuses
the same transitions first with `409 ILLEGAL_STATE_TRANSITION`; the trigger is the last line.

## No foreign key to the account table

`practitioner_id` and `created_by` name accounts in the legacy `user` table, which has no RLS and no
`(tenant_id, id)` key (T1-03, blocked by D-003). The same choice `tga_approvals.created_by` made: the
service checks the practitioner is a bookable account **of the session's tenant** before every write.
The patient link is the tenant-bound composite key, as on every clinical table.
"""

import uuid
from datetime import UTC, datetime, time
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlmodel import Field, SQLModel

# R2. The type decides the practitioner role and the length; the server computes `ends_at` from it.
APPOINTMENT_TYPES: Final[dict[str, tuple[str, int]]] = {
    "NURSE_TRIAGE": ("NURSE", 15),
    "INITIAL_CONSULT": ("DOCTOR", 30),
    "FOLLOW_UP": ("DOCTOR", 15),
}

APPOINTMENT_STATUSES: Final[tuple[str, ...]] = (
    "BOOKED",
    "CONFIRMED",
    "ARRIVED",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
)

# R4. The service reads this map, the trigger enforces the same table in SQL, and a test asserts the
# two agree.
LEGAL_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "BOOKED": frozenset({"CONFIRMED", "ARRIVED", "CANCELLED", "NO_SHOW"}),
    "CONFIRMED": frozenset({"ARRIVED", "CANCELLED", "NO_SHOW"}),
    "ARRIVED": frozenset({"COMPLETED"}),
    "COMPLETED": frozenset(),
    "CANCELLED": frozenset(),
    "NO_SHOW": frozenset(),
}

# A booking in one of these states no longer holds its slot (the exclusion constraint's predicate).
RELEASED_STATUSES: Final[tuple[str, ...]] = ("CANCELLED", "NO_SHOW")

# R6: where a booking came from. `PUBLIC_BOOKING` marks an intake from the public page.
APPOINTMENT_SOURCES: Final[tuple[str, ...]] = ("STAFF", "PUBLIC_BOOKING")

DURING_SQL: Final[str] = "tstzrange(starts_at, ends_at, '[)')"


def _in(values: tuple[str, ...] | list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_DURATION_SQL = " OR ".join(
    f"(type = '{code}' AND ends_at - starts_at = interval '{minutes} minutes')"
    for code, (_role, minutes) in APPOINTMENT_TYPES.items()
)
_RELEASED_SQL = _in(RELEASED_STATUSES)

# Availability defaults (no document fixes them: recorded in the contract). A tenant may hold its own
# `appointment_settings` row and seven `appointment_hours` rows; without them, these apply.
DEFAULT_OPENS_AT: Final[time] = time(9, 0)
DEFAULT_CLOSES_AT: Final[time] = time(17, 0)
# ISO weekdays, Monday = 1.
WEEKDAYS: Final[tuple[int, ...]] = (1, 2, 3, 4, 5, 6, 7)
DEFAULT_WORKING_DAYS: Final[tuple[int, ...]] = (1, 2, 3, 4, 5)
# The step between offered start times (`docs2/sdlc/04-calendar-and-booking/api.md`, "Clinic hours,
# slot length and booking emails"). A closed vocabulary, so the calendar grid stays legible.
SLOT_MINUTES_ALLOWED: Final[tuple[int, ...]] = (10, 15, 20, 30, 60)
DEFAULT_SLOT_MINUTES: Final[int] = 15
# Opening and closing times sit on 5-minute marks.
TIME_GRANULARITY_MINUTES: Final[int] = 5

# The booking emails (`appointment_notifications`): what is sent, and where each row is in its life.
NOTIFICATION_KINDS: Final[tuple[str, ...]] = ("CONFIRMATION", "REMINDER")
NOTIFICATION_STATUSES: Final[tuple[str, ...]] = (
    "PENDING",
    "SENDING",
    "SENT",
    "SKIPPED",
    "FAILED",
)
# Why a row was skipped or failed: codes, never provider text.
NOTIFICATION_OUTCOMES: Final[tuple[str, ...]] = (
    "BOOKING_NOT_LIVE",
    "STARTED",
    "NO_EMAIL",
    "SMTP_ERROR",
)

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Appointment(SQLModel, table=True):
    """One booking of one patient with one practitioner, half-open `[starts_at, ends_at)`."""

    __tablename__ = "appointments"
    __table_args__ = (
        sa.CheckConstraint(f"type IN ({_in(list(APPOINTMENT_TYPES))})", name="type"),
        sa.CheckConstraint(f"status IN ({_in(APPOINTMENT_STATUSES)})", name="status"),
        sa.CheckConstraint(f"source IN ({_in(APPOINTMENT_SOURCES)})", name="source"),
        sa.CheckConstraint(_DURATION_SQL, name="duration"),
        sa.CheckConstraint(f"during = {DURING_SQL}", name="during"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_appointments_tenant_id_id"),
        # A booking can only name a patient of its own tenant.
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_appointments_tenant_patient",
            ondelete="RESTRICT",
        ),
        # R3: the backing index of the partial EXCLUDE constraint the migration creates.
        sa.Index(
            "no_overlapping_appointments",
            "tenant_id",
            "practitioner_id",
            "during",
            unique=False,
            postgresql_using="gist",
            postgresql_where=sa.text(f"status NOT IN ({_RELEASED_SQL})"),
        ),
        # The calendar's read path: one tenant, a time window. `tenant_id` leads every index.
        sa.Index("ix_appointments_tenant_starts", "tenant_id", "starts_at"),
        sa.Index(
            "ix_appointments_tenant_patient_starts",
            "tenant_id",
            "patient_id",
            "starts_at",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    patient_id: uuid.UUID = Field(nullable=False)
    practitioner_id: uuid.UUID = Field(nullable=False)
    type: str
    status: str = Field(default="BOOKED")
    source: str = Field(default="STAFF")
    starts_at: datetime = Field(sa_type=_TIMESTAMPTZ)
    ends_at: datetime = Field(sa_type=_TIMESTAMPTZ)
    # Derived by trigger from the two instants above; never written by the application.
    during: Any = Field(default=None, sa_column=sa.Column(TSTZRANGE, nullable=False))
    # `NULL` for a booking made on the public page, which has no staff actor.
    created_by: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class AppointmentSettings(SQLModel, table=True):
    """A tenant's booking settings. Optional: without a row, the module defaults apply.

    Written by the Practice Owner (`PUT /api/v1/appointment-settings`, `tenant:configure`); its
    opening hours are the seven `appointment_hours` rows that reference it.
    """

    __tablename__ = "appointment_settings"
    __table_args__ = (
        sa.CheckConstraint(
            f"slot_minutes IN ({', '.join(str(m) for m in SLOT_MINUTES_ALLOWED)})",
            name="slot_minutes",
        ),
    )

    tenant_id: uuid.UUID = Field(
        primary_key=True, foreign_key="tenants.id", ondelete="RESTRICT"
    )
    slot_minutes: int = Field(
        default=DEFAULT_SLOT_MINUTES,
        sa_type=sa.SmallInteger(),
        sa_column_kwargs={"server_default": str(DEFAULT_SLOT_MINUTES)},
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )


_ON_THE_MARK = (
    "extract(minute FROM {c})::int % " + str(TIME_GRANULARITY_MINUTES) + " = 0"
    " AND extract(second FROM {c}) = 0"
)


class AppointmentHours(SQLModel, table=True):
    """One weekday's opening hours. Seven rows per configured clinic; closed = both times `NULL`.

    A row per weekday, always, so closing a day is an `UPDATE` and the application role needs no
    `DELETE`. One interval per day: two openings of one day cannot overlap by construction.
    """

    __tablename__ = "appointment_hours"
    __table_args__ = (
        sa.CheckConstraint("weekday BETWEEN 1 AND 7", name="weekday"),
        sa.CheckConstraint(
            "(opens_at IS NULL) = (closes_at IS NULL)", name="open_or_closed"
        ),
        sa.CheckConstraint(
            "opens_at IS NULL OR closes_at > opens_at", name="opens_before_closes"
        ),
        sa.CheckConstraint(
            "opens_at IS NULL OR ("
            + _ON_THE_MARK.format(c="opens_at")
            + " AND "
            + _ON_THE_MARK.format(c="closes_at")
            + ")",
            name="on_the_mark",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["appointment_settings.tenant_id"],
            name="fk_appointment_hours_tenant_settings",
            ondelete="CASCADE",
        ),
    )

    tenant_id: uuid.UUID = Field(primary_key=True)
    weekday: int = Field(primary_key=True, sa_type=sa.SmallInteger())
    opens_at: time | None = None
    closes_at: time | None = None


class AppointmentNotification(SQLModel, table=True):
    """The booking-email outbox (D-009): one confirmation and at most one reminder per booking.

    Written on the booking's own transaction; sent by `app.modules.appointments.notifications`.
    `UNIQUE (tenant_id, appointment_id, kind)` makes a second reminder for one booking
    unrepresentable. No address, name or time is stored here: the sender reads them at send time.
    """

    __tablename__ = "appointment_notifications"
    __table_args__ = (
        sa.CheckConstraint(f"kind IN ({_in(NOTIFICATION_KINDS)})", name="kind"),
        sa.CheckConstraint(f"status IN ({_in(NOTIFICATION_STATUSES)})", name="status"),
        sa.CheckConstraint(
            f"outcome IS NULL OR outcome IN ({_in(NOTIFICATION_OUTCOMES)})",
            name="outcome",
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts"),
        sa.CheckConstraint("(status = 'SENT') = (sent_at IS NOT NULL)", name="sent_at"),
        sa.UniqueConstraint(
            "tenant_id",
            "appointment_id",
            "kind",
            name="uq_appointment_notifications_one_per_kind",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "appointment_id"],
            ["appointments.tenant_id", "appointments.id"],
            name="fk_appointment_notifications_tenant_appointment",
            ondelete="RESTRICT",
        ),
        # The sender's scan: one tenant's due rows.
        sa.Index(
            "ix_appointment_notifications_tenant_status_due",
            "tenant_id",
            "status",
            "due_at",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    appointment_id: uuid.UUID = Field(nullable=False)
    kind: str
    status: str = Field(default="PENDING")
    outcome: str | None = None
    due_at: datetime = Field(sa_type=_TIMESTAMPTZ)
    attempts: int = Field(default=0, sa_type=sa.SmallInteger())
    claimed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    sent_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )
