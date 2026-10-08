"""Appointments service facade - the only place `appointments` and `appointment_settings` are queried.

Contract: `docs2/sdlc/04-calendar-and-booking/api.md` (agreed 2026-10-07, owner).

Rules this module holds to, the same ones every clinical module does:

- **Every query runs inside `tenant_transaction(...)`**, and every query also carries
  `tenant_id = :tenant_id` as a second line of defence below the forced RLS policy.
- **The other modules are reached through their facades**: the practitioner roster through
  `users_roles.service.active_staff_holding`, patient names and the public booking's patient through
  `patients.service`, both on this module's own transaction so a booking and what it depends on are
  one snapshot.
- **Audit in the same transaction (INV-4)**: `appointment.create` with the patient and the source,
  `appointment.state_change` with the two status codes. The public page's new patient is
  `patient.create`, written by the patients module on the same transaction. Nothing clinical, no name,
  no time and no contact detail ever reaches a payload.
- **No PHI in a refusal (INV-5)**. R3 asks that an overlap refusal *"names the clash"*; it names the
  practitioner and the clashing **time**, never the other patient. `docs/` wins over the preview's
  wording, which named the patient.
- **Times are Australia/Sydney (R7), on the database clock.** The slot grid, "today" and the 18+
  check are computed by PostgreSQL `AT TIME ZONE`, so they do not depend on the server's zone or on a
  timezone database being installed in the image.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final, Literal

from sqlalchemy import TextClause, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import tenant_transaction
from app.core.reads import Plan, ReadBatch, run_plan
from app.modules.appointments.models import (
    APPOINTMENT_STATUSES,
    APPOINTMENT_TYPES,
    DEFAULT_CLOSES_AT,
    DEFAULT_OPENS_AT,
    DEFAULT_SLOT_MINUTES,
    DEFAULT_WORKING_DAYS,
    LEGAL_TRANSITIONS,
    RELEASED_STATUSES,
    WEEKDAYS,
    Appointment,
)
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentSettingsRead,
    AppointmentSettingsSaved,
    AppointmentSettingsUpdate,
    DayAppointment,
    DayHours,
    DaySchedule,
    PractitionerRead,
    PublicBookingRequest,
    PublicSlot,
)
from app.modules.audit import service as audit
from app.modules.care_relationships import service as care
from app.modules.patients import service as patients
from app.modules.users_roles import service as users_roles
from app.modules.users_roles.catalog import (
    CLIENT_TENANT_ID_IGNORED,
    PRACTITIONER_ROLE_BY_CODE,
)
from app.modules.users_roles.policy import Actor, Decision

TIMEZONE: Final[str] = "Australia/Sydney"
# The public page offers the next 14 days (contract), starting tomorrow: a same-day online booking
# leaves the clinic no time to see the intake before the patient arrives.
PUBLIC_HORIZON_DAYS: Final[int] = 14
# The calendar's widest read: a week view needs 5 days, a month is the ceiling.
MAX_RANGE: Final[timedelta] = timedelta(days=31)
# R5: online booking is for adults.
MINIMUM_BOOKING_AGE: Final[int] = 18
# A patient's appointment history, newest first, bounded.
MAX_PATIENT_HISTORY: Final[int] = 200

APPOINTMENT_CREATE: Final[str] = "appointment.create"
APPOINTMENT_STATE_CHANGE: Final[str] = "appointment.state_change"
# Registered with T1-34: every read of bookings is audited, a patient's with the relationship and the
# purpose, the calendar's and the Today page's with the kinds of filter and the row count.
APPOINTMENT_READ: Final[str] = "appointment.read"
# The permission a patient's bookings are read under, and the rule is decided for (a booking is part
# of the patient's record: `APPOINTMENT_PERMISSIONS["read"]` is `patient:read`).
_PATIENT_READ: Final[str] = "patient:read"
# The audit `reason` for a patient that is not the caller's own (the clinical-records trail's code).
NOT_FOUND_REASON: Final[str] = "AUTHZ_DENIED_CROSS_TENANT"

# Refusal codes, each with one status (`detail.code` in the RFC 7807 body).
APPOINTMENT_NOT_FOUND: Final[str] = "APPOINTMENT_NOT_FOUND"
PATIENT_NOT_FOUND: Final[str] = "PATIENT_NOT_FOUND"
PRACTITIONER_NOT_FOUND: Final[str] = "PRACTITIONER_NOT_FOUND"
TYPE_NOT_OFFERED: Final[str] = "TYPE_NOT_OFFERED"
APPOINTMENT_OVERLAP: Final[str] = "APPOINTMENT_OVERLAP"
ILLEGAL_STATE_TRANSITION: Final[str] = "ILLEGAL_STATE_TRANSITION"
INVALID_RANGE: Final[str] = "INVALID_RANGE"
SLOT_NOT_OFFERED: Final[str] = "SLOT_NOT_OFFERED"
SLOT_TAKEN: Final[str] = "SLOT_TAKEN"
BOOKING_AGE_NOT_MET: Final[str] = "BOOKING_AGE_NOT_MET"

OVERLAP_CONSTRAINT: Final[str] = "no_overlapping_appointments"

_ROLE_LABEL: Final[dict[str, str]] = {"DOCTOR": "doctor", "NURSE": "nurse"}


class AppointmentRefused(Exception):
    """A decided refusal: the router turns it into `{status, detail: {code, message}}`."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Availability:
    """A tenant's bookable hours and slot length: its own settings, or the module defaults.

    `hours` has one entry per ISO weekday, Monday first; a closed day is `(None, None)`.
    """

    slot_minutes: int
    hours: tuple[tuple[time | None, time | None], ...]
    is_default: bool

    def open_days(self) -> tuple[list[int], list[time], list[time]]:
        """The open weekdays and their times, as three parallel lists (the slot query's input)."""
        weekdays: list[int] = []
        opens: list[time] = []
        closes: list[time] = []
        for weekday, (opens_at, closes_at) in zip(WEEKDAYS, self.hours, strict=True):
            if opens_at is not None and closes_at is not None:
                weekdays.append(weekday)
                opens.append(opens_at)
                closes.append(closes_at)
        return weekdays, opens, closes

    def as_read(self) -> AppointmentSettingsRead:
        return AppointmentSettingsRead(
            slot_minutes=self.slot_minutes,
            hours=[
                DayHours(weekday=weekday, opens_at=opens_at, closes_at=closes_at)
                for weekday, (opens_at, closes_at) in zip(
                    WEEKDAYS, self.hours, strict=True
                )
            ],
            is_default=self.is_default,
        )


DEFAULT_AVAILABILITY: Final[Availability] = Availability(
    slot_minutes=DEFAULT_SLOT_MINUTES,
    hours=tuple(
        (DEFAULT_OPENS_AT, DEFAULT_CLOSES_AT)
        if weekday in DEFAULT_WORKING_DAYS
        else (None, None)
        for weekday in WEEKDAYS
    ),
    is_default=True,
)


# -- practitioners ---------------------------------------------------------------------------------


def _roster(session: Session, *, tenant_id: uuid.UUID) -> list[PractitionerRead]:
    """Bookable staff: active accounts holding a Doctor, Authorised Prescriber or Nurse role.

    One account holding several of those roles is listed once, as a doctor if any of its roles is a
    doctor's. `name` falls back to the email for an account with no full name (staff-only screen);
    `title` is the display name of the role the practitioner is booked as.
    """
    roster: list[PractitionerRead] = []
    for member in users_roles.active_staff_holding(
        session, tenant_id=tenant_id, role_codes=PRACTITIONER_ROLE_BY_CODE
    ):
        role: Literal["DOCTOR", "NURSE"] = (
            "DOCTOR"
            if any(PRACTITIONER_ROLE_BY_CODE[code] == "DOCTOR" for code in member.roles)
            else "NURSE"
        )
        title = next(
            name
            for code, name in sorted(member.roles.items())
            if PRACTITIONER_ROLE_BY_CODE[code] == role
        )
        roster.append(
            PractitionerRead(
                id=member.user_id,
                name=member.full_name or member.email,
                role=role,
                title=title,
            )
        )
    return roster


def list_practitioners(*, tenant_id: uuid.UUID) -> list[PractitionerRead]:
    with tenant_transaction(tenant_id=tenant_id) as session:
        return _roster(session, tenant_id=tenant_id)


# -- reads -----------------------------------------------------------------------------------------


def _convert(
    rows: Sequence[Appointment], names: dict[uuid.UUID, str]
) -> list[AppointmentRead]:
    # Validated, not cast: the check constraints hold the vocabularies, and the schema re-checks them.
    return [
        AppointmentRead.model_validate(
            {
                "id": row.id,
                "patient_id": row.patient_id,
                # A patient record that is no longer live keeps its bookings readable, unnamed.
                "patient_name": names.get(row.patient_id, "Patient record unavailable"),
                "practitioner_id": row.practitioner_id,
                "type": row.type,
                "status": row.status,
                "starts_at": row.starts_at,
                "ends_at": row.ends_at,
                "source": row.source,
                "created_at": row.created_at,
            }
        )
        for row in rows
    ]


def _reads(
    session: Session, *, tenant_id: uuid.UUID, rows: Sequence[Appointment]
) -> list[AppointmentRead]:
    batch = ReadBatch()
    names = patients.queue_display_names(
        batch, tenant_id=tenant_id, patient_ids=[row.patient_id for row in rows]
    )
    batch.send(session)
    return _convert(rows, names.value)


def list_appointments(
    *,
    actor: Actor,
    starts_from: datetime,
    starts_before: datetime,
    practitioner_id: uuid.UUID | None,
    source_ip: str | None = None,
) -> list[AppointmentRead]:
    """Appointments **starting** in `[starts_from, starts_before)`, earliest first. Audited
    `appointment.read` with the kinds of filter (never a value) and the row count (T1-34)."""
    tenant_id = actor.tenant_id
    if starts_before <= starts_from or starts_before - starts_from > MAX_RANGE:
        raise AppointmentRefused(
            422,
            INVALID_RANGE,
            "Choose a range where 'to' is after 'from' and no more than 31 days later.",
        )
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        source_ip=source_ip,
    ) as session:
        statement = select(Appointment).where(
            Appointment.tenant_id == tenant_id,
            col(Appointment.starts_at) >= starts_from,
            col(Appointment.starts_at) < starts_before,
        )
        if practitioner_id is not None:
            statement = statement.where(Appointment.practitioner_id == practitioner_id)
        rows = session.exec(
            statement.order_by(col(Appointment.starts_at), col(Appointment.id))
        ).all()
        reads = _reads(session, tenant_id=tenant_id, rows=rows)
        audit.record(
            session,
            read_event(
                query_filters=["range"]
                + ([] if practitioner_id is None else ["practitioner"]),
                result_count=len(reads),
                source_ip=source_ip,
            ),
        )
        return reads


def read_event(
    *, query_filters: list[str], result_count: int, source_ip: str | None = None
) -> audit.AuditEvent:
    """The `appointment.read` event for a practice-wide read: filter kinds and a count only."""
    return audit.AuditEvent(
        action=APPOINTMENT_READ,
        result="SUCCESS",
        source_ip=source_ip,
        payload={"query_filters": query_filters, "result_count": result_count},
    )


@dataclass(frozen=True)
class PatientBookings:
    """A patient's bookings, or why not: `found=False` is `404`; `decision` is the `403`."""

    found: bool
    bookings: list[AppointmentRead]
    decision: Decision | None = None


def list_for_patient(
    *, actor: Actor, patient_id: uuid.UUID, source_ip: str | None = None
) -> PatientBookings:
    """One patient's bookings, newest first, under the treating-relationship rule (T1-34).

    Not found (absent, or another tenant's) and refused (a relationship-bound grant without an active
    care relationship) are both audited `DENIED`; a read is audited `SUCCESS` with the relationship id,
    the purpose and the row count.
    """
    tenant_id = actor.tenant_id
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        source_ip=source_ip,
    ) as session:
        # The patient's name, the actor's relationship with it and its bookings in one flight. The
        # bookings are only returned once the patients facade has answered that the patient is this
        # tenant's own and live, and the policy layer has allowed the read.
        batch = ReadBatch()
        names = patients.queue_display_names(
            batch, tenant_id=tenant_id, patient_ids=[patient_id]
        )
        relationship = batch.scalars(
            select(care.actor_relationship_id(actor, patient_id))
        )
        rows = batch.scalars(
            select(Appointment)
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.patient_id == patient_id,
            )
            .order_by(col(Appointment.starts_at).desc(), col(Appointment.id))
            .limit(MAX_PATIENT_HISTORY)
        )
        batch.send(session)

        def denied(reason: str) -> None:
            audit.record(
                session,
                audit.AuditEvent(
                    action=APPOINTMENT_READ,
                    result="DENIED",
                    resource_id=patient_id,
                    reason=reason,
                    source_ip=source_ip,
                    payload={"patient_id": str(patient_id)},
                ),
            )

        if patient_id not in names.value:
            denied(NOT_FOUND_REASON)
            return PatientBookings(found=False, bookings=[])
        access = care.patient_access(
            actor,
            _PATIENT_READ,
            patient_id=patient_id,
            care_relationship_id=relationship.value[0],
        )
        if not access.allowed:
            denied(access.reason)
            return PatientBookings(found=True, bookings=[], decision=access.decision)
        bookings = _convert(rows.value, names.value)
        audit.record(
            session,
            audit.AuditEvent(
                action=APPOINTMENT_READ,
                result="SUCCESS",
                resource_id=patient_id,
                source_ip=source_ip,
                payload={
                    "patient_id": str(patient_id),
                    "result_count": len(bookings),
                    **access.audit_payload(),
                },
            ),
        )
        return PatientBookings(found=True, bookings=bookings)


@dataclass(frozen=True)
class ClinicDay:
    """A clinic day (R7) and its bounds `[starts, ends)` as instants.

    The bounds are the day's `00:00` and the next day's `00:00` in Sydney, so the day of a daylight
    saving change is 23 or 25 hours long, exactly as the clinic lives it.
    """

    day: date
    starts: datetime
    ends: datetime


# Today's date in the clinic and its bounds, from the database clock, in one statement. `now()` is the
# transaction's start time, so every read on one transaction agrees on "today".
_TODAY_SQL = text(
    "SELECT today.day,"
    " today.day::timestamp AT TIME ZONE :zone,"
    " (today.day + 1)::timestamp AT TIME ZONE :zone"
    " FROM (SELECT (now() AT TIME ZONE :zone)::date AS day) AS today"
)
_DAY_BOUNDS_SQL = text(
    "SELECT CAST(:day AS date),"
    " CAST(:day AS date)::timestamp AT TIME ZONE :zone,"
    " (CAST(:day AS date) + 1)::timestamp AT TIME ZONE :zone"
)


def _clinic_day(session: Session, statement: TextClause, **values: object) -> ClinicDay:
    day, starts, ends = (
        session.connection().execute(statement, {"zone": TIMEZONE, **values}).one()
    )
    assert isinstance(day, date), "the database clock must answer with a date"
    return ClinicDay(day=day, starts=starts, ends=ends)


def clinic_day(session: Session) -> ClinicDay:
    """Today in the clinic (R7) and its bounds, from the database clock on the caller's transaction.

    One statement for the date and both bounds; the Today page reads it once for every section.
    """
    return _clinic_day(session, _TODAY_SQL)


# A clinic day's schedule is bounded by its practitioners' hours; the ceiling only stops a runaway.
MAX_DAY_SCHEDULE: Final[int] = 500


def day_schedule_plan(*, tenant_id: uuid.UUID, day: ClinicDay) -> Plan[DaySchedule]:
    """Every booking starting on the clinic day `day`, earliest first, as a read plan.

    For the Today page (`dashboard` module), which runs every section's plan on one transaction, so
    the sections are one snapshot and share their round trips (`app.core.reads`): the bookings are
    one step, the patients' and the practitioners' names the next. Cancelled and no-show bookings
    are listed too: the day's record is what happened, and `by_status` lets the screen count what is
    still to come.
    """
    first = ReadBatch()
    bookings = first.scalars(
        select(Appointment)
        .where(
            Appointment.tenant_id == tenant_id,
            col(Appointment.starts_at) >= day.starts,
            col(Appointment.starts_at) < day.ends,
        )
        .order_by(col(Appointment.starts_at), col(Appointment.id))
        .limit(MAX_DAY_SCHEDULE)
    )
    yield first

    rows = bookings.value
    second = ReadBatch()
    patient_names = patients.queue_display_names(
        second, tenant_id=tenant_id, patient_ids=[row.patient_id for row in rows]
    )
    practitioner_names = users_roles.queue_display_names(
        second, tenant_id=tenant_id, user_ids=[row.practitioner_id for row in rows]
    )
    yield second

    reads = _convert(rows, patient_names.value)
    by_status = dict.fromkeys(APPOINTMENT_STATUSES, 0)
    for read in reads:
        by_status[read.status] += 1
    return DaySchedule.model_validate(
        {
            "by_status": by_status,
            "data": [
                DayAppointment(
                    **read.model_dump(),
                    practitioner_name=practitioner_names.value.get(
                        read.practitioner_id
                    ),
                )
                for read in reads
            ],
        }
    )


def day_schedule(session: Session, *, tenant_id: uuid.UUID, day: date) -> DaySchedule:
    """`day_schedule_plan` for any clinic day `day`, run on the caller's transaction."""
    bounds = _clinic_day(session, _DAY_BOUNDS_SQL, day=day)
    return run_plan(session, day_schedule_plan(tenant_id=tenant_id, day=bounds))


# -- writes ----------------------------------------------------------------------------------------


def _is_overlap(error: IntegrityError) -> bool:
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    return getattr(diagnostic, "constraint_name", None) == OVERLAP_CONSTRAINT


def _local_hhmm(session: Session, instant: datetime) -> str:
    value = session.connection().execute(
        text("SELECT to_char(CAST(:at AS timestamptz) AT TIME ZONE :zone, 'HH24:MI')"),
        {"at": instant, "zone": TIMEZONE},
    )
    return str(value.scalar_one())


def _clash_message(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    practitioner: PractitionerRead,
    starts_at: datetime,
    ends_at: datetime,
) -> str:
    """R3 names the clash: who is busy, and when. Never the other patient (INV-5)."""
    clash = session.exec(
        select(Appointment)
        .where(
            Appointment.tenant_id == tenant_id,
            Appointment.practitioner_id == practitioner.id,
            col(Appointment.status).not_in(RELEASED_STATUSES),
            col(Appointment.starts_at) < ends_at,
            col(Appointment.ends_at) > starts_at,
        )
        .order_by(col(Appointment.starts_at))
    ).first()
    if (
        clash is None
    ):  # pragma: no cover - the constraint fired, so a clash exists in this snapshot
        return f"{practitioner.name} is already booked at that time."
    return (
        f"{practitioner.name} is already booked from "
        f"{_local_hhmm(session, clash.starts_at)} to {_local_hhmm(session, clash.ends_at)}."
    )


def _insert(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    practitioner: PractitionerRead,
    appointment_type: str,
    starts_at: datetime,
    source: str,
    created_by: uuid.UUID | None,
    overlap_code: str,
    source_ip: str | None = None,
) -> Appointment:
    """Insert one booking under a savepoint; the exclusion constraint is the double-booking refusal.

    There is no "is it free?" read before the write: two concurrent bookings would both pass it. The
    constraint is the only authority, and a violation rolls back exactly this savepoint so the clash
    can still be read and named on the same transaction before the whole request is refused.
    """
    _role, minutes = APPOINTMENT_TYPES[appointment_type]
    ends_at = starts_at + timedelta(minutes=minutes)
    appointment = Appointment(
        tenant_id=tenant_id,
        patient_id=patient_id,
        practitioner_id=practitioner.id,
        type=appointment_type,
        source=source,
        starts_at=starts_at,
        ends_at=ends_at,
        created_by=created_by,
    )
    try:
        with session.begin_nested():
            session.add(appointment)
            session.flush()
    except IntegrityError as error:
        if not _is_overlap(error):
            raise
        if overlap_code == SLOT_TAKEN:
            raise AppointmentRefused(
                409, SLOT_TAKEN, "Someone just booked that time. Please choose another."
            ) from None
        raise AppointmentRefused(
            409,
            APPOINTMENT_OVERLAP,
            _clash_message(
                session,
                tenant_id=tenant_id,
                practitioner=practitioner,
                starts_at=starts_at,
                ends_at=ends_at,
            ),
        ) from None
    audit.record(
        session,
        audit.AuditEvent(
            action=APPOINTMENT_CREATE,
            result="SUCCESS",
            resource_id=appointment.id,
            source_ip=source_ip,
            payload={"patient_id": str(patient_id), "source": source},
        ),
    )
    _enqueue_notifications(
        session, tenant_id=tenant_id, appointment_id=appointment.id, starts_at=starts_at
    )
    session.refresh(appointment)
    return appointment


# The booking emails (D-007), written on the booking's own transaction: a confirmation due now, and
# a reminder due 24 hours before the start when that is still ahead. Nothing about the patient is
# stored here; the sender reads the address when it sends.
REMINDER_LEAD: Final[timedelta] = timedelta(hours=24)
_ENQUEUE_SQL = text(
    "INSERT INTO appointment_notifications"
    " (id, tenant_id, appointment_id, kind, status, due_at, attempts, created_at, updated_at)"
    " SELECT gen_random_uuid(), :tenant_id, :appointment_id, k.kind, 'PENDING', k.due_at, 0,"
    " now(), now()"
    " FROM (VALUES ('CONFIRMATION', now()),"
    " ('REMINDER', CAST(:starts_at AS timestamptz) - CAST(:lead AS interval)))"
    " AS k(kind, due_at)"
    " WHERE k.kind = 'CONFIRMATION' OR k.due_at > now()"
)


def _enqueue_notifications(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    appointment_id: uuid.UUID,
    starts_at: datetime,
) -> None:
    """Queue the confirmation and the reminder, only while outgoing email is configured."""
    if not settings.emails_enabled:
        return
    session.connection().execute(
        _ENQUEUE_SQL,
        {
            "tenant_id": tenant_id,
            "appointment_id": appointment_id,
            "starts_at": starts_at,
            "lead": REMINDER_LEAD,
        },
    )


def record_client_tenant_id_ignored(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    source_ip: str | None = None,
) -> None:
    """INV-1: a client-supplied `tenant_id` is ignored **and audited** as a cross-tenant attempt.

    Written on its own transaction, before the booking is attempted, so the attempt is on the trail
    whether or not the booking itself then succeeds.
    """
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        source_ip=source_ip,
    ) as session:
        audit.record(
            session,
            audit.AuditEvent(
                action=APPOINTMENT_CREATE,
                result="DENIED",
                reason=CLIENT_TENANT_ID_IGNORED,
                source_ip=source_ip,
            ),
        )


def create_appointment(*, actor: Actor, body: AppointmentCreate) -> AppointmentRead:
    """Book a patient with a practitioner (staff). The server computes `ends_at` from the type."""
    tenant_id = actor.tenant_id
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        if not patients.display_names(
            session, tenant_id=tenant_id, patient_ids=[body.patient_id]
        ):
            raise AppointmentRefused(404, PATIENT_NOT_FOUND, "Patient not found")
        practitioner = next(
            (
                p
                for p in _roster(session, tenant_id=tenant_id)
                if p.id == body.practitioner_id
            ),
            None,
        )
        if practitioner is None:
            raise AppointmentRefused(
                404, PRACTITIONER_NOT_FOUND, "That practitioner isn't bookable."
            )
        role, _minutes = APPOINTMENT_TYPES[body.type]
        if practitioner.role != role:
            raise AppointmentRefused(
                422,
                TYPE_NOT_OFFERED,
                f"This appointment type is booked with a {_ROLE_LABEL[role]}.",
            )
        appointment = _insert(
            session,
            tenant_id=tenant_id,
            patient_id=body.patient_id,
            practitioner=practitioner,
            appointment_type=body.type,
            starts_at=body.starts_at,
            source="STAFF",
            created_by=actor.user_id,
            overlap_code=APPOINTMENT_OVERLAP,
        )
        return _reads(session, tenant_id=tenant_id, rows=[appointment])[0]


def change_status(
    *, actor: Actor, appointment_id: uuid.UUID, status: str
) -> AppointmentRead:
    """Move a booking through R4's machine. The row is locked so two desks cannot race a change."""
    tenant_id = actor.tenant_id
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        appointment = session.exec(
            select(Appointment)
            .where(Appointment.tenant_id == tenant_id, Appointment.id == appointment_id)
            .with_for_update()
        ).first()
        if appointment is None:
            raise AppointmentRefused(
                404, APPOINTMENT_NOT_FOUND, "Appointment not found"
            )
        current = appointment.status
        if status not in LEGAL_TRANSITIONS[current]:
            raise AppointmentRefused(
                409,
                ILLEGAL_STATE_TRANSITION,
                f"A {current.lower().replace('_', ' ')} appointment can't be marked "
                f"{status.lower().replace('_', ' ')}.",
            )
        appointment.status = status
        session.add(appointment)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=APPOINTMENT_STATE_CHANGE,
                result="SUCCESS",
                resource_id=appointment.id,
                payload={"from_state": current, "to_state": status},
            ),
        )
        session.refresh(appointment)
        return _reads(session, tenant_id=tenant_id, rows=[appointment])[0]


# -- public booking --------------------------------------------------------------------------------


# The settings row and its seven days in one statement. No row: the module defaults.
_AVAILABILITY_SQL = text(
    "SELECT s.slot_minutes, h.weekday, h.opens_at, h.closes_at"
    " FROM appointment_settings s"
    " LEFT JOIN appointment_hours h ON h.tenant_id = s.tenant_id"
    " WHERE s.tenant_id = :tenant_id"
    " ORDER BY h.weekday"
)


def _availability(session: Session, *, tenant_id: uuid.UUID) -> Availability:
    rows = (
        session.connection().execute(_AVAILABILITY_SQL, {"tenant_id": tenant_id}).all()
    )
    if not rows:
        return DEFAULT_AVAILABILITY
    by_day = {row[1]: (row[2], row[3]) for row in rows if row[1] is not None}
    # A weekday with no row is closed: fail closed, never open by omission.
    return Availability(
        slot_minutes=int(rows[0][0]),
        hours=tuple(by_day.get(weekday, (None, None)) for weekday in WEEKDAYS),
        is_default=False,
    )


# The slot grid, in SQL, so "tomorrow", "09:00" and "Monday" are Sydney's (R7) on the database clock.
# Days: tomorrow to `horizon` days out, open days only, each with its own hours. Times: from opening,
# one start every `step` minutes (the clinic's slot length), each lasting the type's length and the
# last one ending at or before closing. A local time is turned into an instant with
# `timestamp AT TIME ZONE`, which is what makes 09:00 mean 09:00 in Sydney through a DST change.
_SLOTS_SQL = text(
    """
    WITH today AS (SELECT (now() AT TIME ZONE :zone)::date AS d),
    hours AS (
        SELECT * FROM unnest(
            CAST(:weekdays AS int[]), CAST(:opens AS time[]), CAST(:closes AS time[])
        ) AS h(weekday, opens_at, closes_at)
    ),
    days AS (
        SELECT t.d + n AS day, h.opens_at, h.closes_at
        FROM today t
        CROSS JOIN generate_series(1, :horizon) AS n
        JOIN hours h ON h.weekday = extract(isodow FROM t.d + n)::int
    ),
    candidates AS (
        SELECT p.practitioner_id, (local_start AT TIME ZONE :zone) AS starts_at
        FROM days
        CROSS JOIN LATERAL generate_series(
            days.day + days.opens_at,
            days.day + days.closes_at - make_interval(mins => :minutes),
            make_interval(mins => :step)
        ) AS local_start
        CROSS JOIN unnest(CAST(:practitioner_ids AS uuid[])) AS p(practitioner_id)
    )
    SELECT c.practitioner_id, c.starts_at, c.starts_at + make_interval(mins => :minutes) AS ends_at
    FROM candidates c
    WHERE (CAST(:only_practitioner AS uuid) IS NULL OR c.practitioner_id = :only_practitioner)
      AND (CAST(:only_start AS timestamptz) IS NULL OR c.starts_at = :only_start)
      AND (NOT :free_only OR NOT EXISTS (
            SELECT 1 FROM appointments a
            WHERE a.tenant_id = :tenant_id
              AND a.practitioner_id = c.practitioner_id
              AND a.status NOT IN ('CANCELLED', 'NO_SHOW')
              AND a.during && tstzrange(
                    c.starts_at, c.starts_at + make_interval(mins => :minutes), '[)')
      ))
    ORDER BY c.starts_at, c.practitioner_id
    """
)


def _slots(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    appointment_type: str,
    practitioners: list[PractitionerRead],
    free_only: bool,
    only_practitioner: uuid.UUID | None = None,
    only_start: datetime | None = None,
) -> list[dict[str, Any]]:
    if not practitioners:
        return []
    availability = _availability(session, tenant_id=tenant_id)
    weekdays, opens, closes = availability.open_days()
    _role, minutes = APPOINTMENT_TYPES[appointment_type]
    result = session.connection().execute(
        _SLOTS_SQL,
        {
            "zone": TIMEZONE,
            "horizon": PUBLIC_HORIZON_DAYS,
            "weekdays": weekdays,
            "opens": opens,
            "closes": closes,
            "minutes": minutes,
            "step": availability.slot_minutes,
            "practitioner_ids": [p.id for p in practitioners],
            "only_practitioner": only_practitioner,
            "only_start": only_start,
            "free_only": free_only,
            "tenant_id": tenant_id,
        },
    )
    return [dict(row) for row in result.mappings()]


def _public_name(practitioner: PractitionerRead) -> str:
    """The name the public page may show: the full name, never an email address."""
    if "@" in practitioner.name:
        return practitioner.title
    return practitioner.name


def _bookable_for(
    session: Session, *, tenant_id: uuid.UUID, appointment_type: str
) -> list[PractitionerRead]:
    role, _minutes = APPOINTMENT_TYPES[appointment_type]
    return [p for p in _roster(session, tenant_id=tenant_id) if p.role == role]


def public_slots(*, tenant_id: uuid.UUID, appointment_type: str) -> list[PublicSlot]:
    """The free slots for one appointment type over the next 14 days (contract)."""
    with tenant_transaction(tenant_id=tenant_id) as session:
        practitioners = _bookable_for(
            session, tenant_id=tenant_id, appointment_type=appointment_type
        )
        by_id = {p.id: p for p in practitioners}
        return [
            PublicSlot(
                practitioner_id=row["practitioner_id"],
                practitioner_name=_public_name(by_id[row["practitioner_id"]]),
                starts_at=row["starts_at"],
                ends_at=row["ends_at"],
            )
            for row in _slots(
                session,
                tenant_id=tenant_id,
                appointment_type=appointment_type,
                practitioners=practitioners,
                free_only=True,
            )
        ]


def clinic_today(session: Session) -> date:
    """Today's date in the clinic (R7), from the database clock on the caller's transaction.

    `now()` is the transaction's start time, so every read on one transaction agrees on "today".
    """
    return clinic_day(session).day


def _age_on(date_of_birth: date, today: date) -> int:
    before_birthday = (today.month, today.day) < (
        date_of_birth.month,
        date_of_birth.day,
    )
    return today.year - date_of_birth.year - (1 if before_birthday else 0)


def booking_reference(appointment_id: uuid.UUID) -> str:
    """The reference the patient is shown (`BK-1A2B3C`): derived from the booking's random id."""
    return f"BK-{appointment_id.hex[:6].upper()}"


def public_book(
    *, tenant_id: uuid.UUID, body: PublicBookingRequest, source_ip: str | None
) -> uuid.UUID:
    """Book from the public page: validate the slot, create or match the patient, book, audit.

    One transaction: the patient record, the booking and both audit events commit together or not at
    all, so a refused booking (`409 SLOT_TAKEN`) leaves no stray patient behind. The answer is the
    booking's id, whose reference (`booking_reference`) is the same shape whether the patient was new
    or matched.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_role="PUBLIC_BOOKING", source_ip=source_ip
    ) as session:
        if _age_on(body.date_of_birth, clinic_today(session)) < MINIMUM_BOOKING_AGE:
            raise AppointmentRefused(
                422, BOOKING_AGE_NOT_MET, "You need to be 18 or over to book online."
            )
        practitioners = _bookable_for(
            session, tenant_id=tenant_id, appointment_type=body.type
        )
        practitioner = next(
            (p for p in practitioners if p.id == body.practitioner_id), None
        )
        offered = practitioner is not None and _slots(
            session,
            tenant_id=tenant_id,
            appointment_type=body.type,
            practitioners=[practitioner],
            free_only=False,
            only_practitioner=practitioner.id,
            only_start=body.starts_at,
        )
        if practitioner is None or not offered:
            raise AppointmentRefused(
                422,
                SLOT_NOT_OFFERED,
                "That time isn't available. Please choose another.",
            )
        patient_id = patients.match_or_create_for_booking(
            session,
            tenant_id=tenant_id,
            given_name=body.given_name,
            family_name=body.family_name,
            date_of_birth=body.date_of_birth,
            email=str(body.email),
            phone=body.phone,
            source_ip=source_ip,
        )
        appointment = _insert(
            session,
            tenant_id=tenant_id,
            patient_id=patient_id,
            practitioner=practitioner,
            appointment_type=body.type,
            starts_at=body.starts_at,
            source="PUBLIC_BOOKING",
            created_by=None,
            overlap_code=SLOT_TAKEN,
            source_ip=source_ip,
        )
        return appointment.id


# -- clinic hours and slot length ------------------------------------------------------------------
#
# `docs2/sdlc/04-calendar-and-booking/api.md`, "Clinic hours, slot length and booking emails". The
# hours are PUBLIC (every member reads them; the booking page offers slots inside them). A change is
# the Practice Owner's (`tenant:configure`, decided by the router) and is audited
# `tenant.config_changed` on its own transaction (INV-4).

TENANT_CONFIG_CHANGED: Final[str] = "tenant.config_changed"


def get_settings(*, tenant_id: uuid.UUID) -> AppointmentSettingsRead:
    with tenant_transaction(tenant_id=tenant_id) as session:
        return _availability(session, tenant_id=tenant_id).as_read()


def _record_settings_change(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    result: str,
    changed_fields: Sequence[str],
    reason: str | None = None,
) -> None:
    audit.record(
        session,
        audit.AuditEvent(
            action=TENANT_CONFIG_CHANGED,
            result=result,
            resource_id=tenant_id,
            reason=reason,
            payload={"changed_fields": list(changed_fields), "step_up": False},
        ),
    )


_SETTINGS_FIELDS: Final[tuple[str, ...]] = ("hours", "slot_minutes")


def record_settings_denial(*, actor: Actor, reason: str) -> None:
    """Audit a refused change on its own transaction; a failure here fails the request closed."""
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        _record_settings_change(
            session,
            tenant_id=actor.tenant_id,
            result="DENIED",
            changed_fields=_SETTINGS_FIELDS,
            reason=reason,
        )


_UPSERT_SETTINGS_SQL = text(
    "INSERT INTO appointment_settings (tenant_id, slot_minutes, created_at, updated_at)"
    " VALUES (:tenant_id, :slot_minutes, now(), now())"
    " ON CONFLICT (tenant_id) DO UPDATE"
    " SET slot_minutes = EXCLUDED.slot_minutes, updated_at = now()"
)
_UPSERT_HOURS_SQL = text(
    "INSERT INTO appointment_hours (tenant_id, weekday, opens_at, closes_at)"
    " SELECT :tenant_id, h.weekday, h.opens_at, h.closes_at"
    " FROM unnest(CAST(:weekdays AS smallint[]), CAST(:opens AS time[]),"
    " CAST(:closes AS time[])) AS h(weekday, opens_at, closes_at)"
    " ON CONFLICT (tenant_id, weekday) DO UPDATE"
    " SET opens_at = EXCLUDED.opens_at, closes_at = EXCLUDED.closes_at"
)
# Upcoming live bookings that start or end outside their day's new hours (or on a closed day). They
# are kept: the count only tells the owner to look. Local times are Sydney's (R7).
_OUTSIDE_HOURS_SQL = text(
    """
    SELECT count(*) FROM appointments a
    LEFT JOIN unnest(CAST(:weekdays AS int[]), CAST(:opens AS time[]), CAST(:closes AS time[]))
        AS h(weekday, opens_at, closes_at)
        ON h.weekday = extract(isodow FROM a.starts_at AT TIME ZONE :zone)::int
    WHERE a.tenant_id = :tenant_id
      AND a.starts_at > now()
      AND a.status NOT IN ('CANCELLED', 'NO_SHOW', 'COMPLETED')
      AND (h.weekday IS NULL
           OR (a.starts_at AT TIME ZONE :zone)::time < h.opens_at
           OR (a.ends_at AT TIME ZONE :zone)::time > h.closes_at
           OR (a.ends_at AT TIME ZONE :zone)::date <> (a.starts_at AT TIME ZONE :zone)::date)
    """
)


def update_settings(
    *,
    actor: Actor,
    body: AppointmentSettingsUpdate,
    client_tenant_id_supplied: bool,
) -> AppointmentSettingsSaved:
    """Save the slot length and the seven days (upserts; the caller authorised `tenant:configure`).

    The current settings are read first so the event names only what changed; saving what the
    clinic already has writes nothing and records nothing. A `tenant_id` the client sent was dropped
    by the schema and is recorded `DENIED` `CLIENT_TENANT_ID_IGNORED` on the same transaction.
    """
    tenant_id = actor.tenant_id
    wanted = Availability(
        slot_minutes=body.slot_minutes,
        hours=tuple((day.opens_at, day.closes_at) for day in body.hours),
        is_default=False,
    )
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        if client_tenant_id_supplied:
            _record_settings_change(
                session,
                tenant_id=tenant_id,
                result="DENIED",
                changed_fields=_SETTINGS_FIELDS,
                reason=CLIENT_TENANT_ID_IGNORED,
            )
        current = _availability(session, tenant_id=tenant_id)
        changed = [
            name
            for name, differs in (
                ("hours", current.hours != wanted.hours),
                ("slot_minutes", current.slot_minutes != wanted.slot_minutes),
            )
            if differs or current.is_default
        ]
        weekdays, opens, closes = wanted.open_days()
        if changed:
            connection = session.connection()
            connection.execute(
                _UPSERT_SETTINGS_SQL,
                {"tenant_id": tenant_id, "slot_minutes": wanted.slot_minutes},
            )
            connection.execute(
                _UPSERT_HOURS_SQL,
                {
                    "tenant_id": tenant_id,
                    "weekdays": list(WEEKDAYS),
                    "opens": [opens_at for opens_at, _ in wanted.hours],
                    "closes": [closes_at for _, closes_at in wanted.hours],
                },
            )
            _record_settings_change(
                session,
                tenant_id=tenant_id,
                result="SUCCESS",
                changed_fields=sorted(changed),
            )
        outside = (
            session.connection()
            .execute(
                _OUTSIDE_HOURS_SQL,
                {
                    "tenant_id": tenant_id,
                    "zone": TIMEZONE,
                    "weekdays": weekdays,
                    "opens": opens,
                    "closes": closes,
                },
            )
            .scalar_one()
        )
        return AppointmentSettingsSaved(
            **wanted.as_read().model_dump(), bookings_outside_hours=int(outside)
        )
