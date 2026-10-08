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
# row in `appointment_settings`; without one, these apply.
DEFAULT_OPENS_AT: Final[time] = time(9, 0)
DEFAULT_CLOSES_AT: Final[time] = time(17, 0)
# ISO weekdays, Monday = 1.
DEFAULT_WORKING_DAYS: Final[tuple[int, ...]] = (1, 2, 3, 4, 5)

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
    """A tenant's bookable hours. Optional: without a row, the module defaults apply.

    Availability editing is out of scope for this phase (requirements, "Out of scope"), so no route
    writes this table; it exists so the hours are tenant configuration rather than a code constant,
    and an operator can set them before the admin screen does.
    """

    __tablename__ = "appointment_settings"
    __table_args__ = (
        sa.CheckConstraint("closes_at > opens_at", name="hours"),
        sa.CheckConstraint(
            "cardinality(working_days) BETWEEN 1 AND 7"
            " AND working_days <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]",
            name="working_days",
        ),
    )

    tenant_id: uuid.UUID = Field(
        primary_key=True, foreign_key="tenants.id", ondelete="RESTRICT"
    )
    opens_at: time = Field(default=DEFAULT_OPENS_AT)
    closes_at: time = Field(default=DEFAULT_CLOSES_AT)
    working_days: list[int] = Field(
        default_factory=lambda: list(DEFAULT_WORKING_DAYS),
        sa_column=sa.Column(sa.ARRAY(sa.SmallInteger()), nullable=False),
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )
