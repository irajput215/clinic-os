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

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.db import tenant_transaction
from app.modules.appointments.models import (
    APPOINTMENT_TYPES,
    DEFAULT_CLOSES_AT,
    DEFAULT_OPENS_AT,
    DEFAULT_WORKING_DAYS,
    LEGAL_TRANSITIONS,
    RELEASED_STATUSES,
    Appointment,
    AppointmentSettings,
)
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentRead,
    PractitionerRead,
    PublicBookingRequest,
    PublicSlot,
)
from app.modules.audit import service as audit
from app.modules.patients import service as patients
from app.modules.users_roles import service as users_roles
from app.modules.users_roles.catalog import (
    CLIENT_TENANT_ID_IGNORED,
    PRACTITIONER_ROLE_BY_CODE,
)
from app.modules.users_roles.policy import Actor

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
    """A tenant's bookable hours: its `appointment_settings` row, or the module defaults."""

    opens_at: time
    closes_at: time
    working_days: tuple[int, ...]


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


def _reads(
    session: Session, *, tenant_id: uuid.UUID, rows: Sequence[Appointment]
) -> list[AppointmentRead]:
    names = patients.display_names(
        session, tenant_id=tenant_id, patient_ids=[row.patient_id for row in rows]
    )
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


def list_appointments(
    *,
    tenant_id: uuid.UUID,
    starts_from: datetime,
    starts_before: datetime,
    practitioner_id: uuid.UUID | None,
) -> list[AppointmentRead]:
    """Appointments **starting** in `[starts_from, starts_before)`, earliest first."""
    if starts_before <= starts_from or starts_before - starts_from > MAX_RANGE:
        raise AppointmentRefused(
            422,
            INVALID_RANGE,
            "Choose a range where 'to' is after 'from' and no more than 31 days later.",
        )
    with tenant_transaction(tenant_id=tenant_id) as session:
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
        return _reads(session, tenant_id=tenant_id, rows=rows)


def list_for_patient(
    *, tenant_id: uuid.UUID, patient_id: uuid.UUID
) -> list[AppointmentRead] | None:
    """One patient's bookings, newest first; `None` when the patient is absent or another tenant's."""
    with tenant_transaction(tenant_id=tenant_id) as session:
        if not patients.display_names(
            session, tenant_id=tenant_id, patient_ids=[patient_id]
        ):
            return None
        rows = session.exec(
            select(Appointment)
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.patient_id == patient_id,
            )
            .order_by(col(Appointment.starts_at).desc(), col(Appointment.id))
            .limit(MAX_PATIENT_HISTORY)
        ).all()
        return _reads(session, tenant_id=tenant_id, rows=rows)


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
    session.refresh(appointment)
    return appointment


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


def _availability(session: Session, *, tenant_id: uuid.UUID) -> Availability:
    row = session.exec(
        select(AppointmentSettings).where(AppointmentSettings.tenant_id == tenant_id)
    ).first()
    if row is None:
        return Availability(DEFAULT_OPENS_AT, DEFAULT_CLOSES_AT, DEFAULT_WORKING_DAYS)
    return Availability(row.opens_at, row.closes_at, tuple(row.working_days))


# The slot grid, in SQL, so "tomorrow", "09:00" and "Monday" are Sydney's (R7) on the database clock.
# Days: tomorrow to `horizon` days out, working days only. Times: from opening, one slot per type
# length, the last one ending at or before closing. A local time is turned into an instant with
# `timestamp AT TIME ZONE`, which is what makes 09:00 mean 09:00 in Sydney through a DST change.
_SLOTS_SQL = text(
    """
    WITH today AS (SELECT (now() AT TIME ZONE :zone)::date AS d),
    days AS (
        SELECT t.d + n AS day
        FROM today t, generate_series(1, :horizon) AS n
        WHERE extract(isodow FROM t.d + n)::int = ANY(:working_days)
    ),
    candidates AS (
        SELECT p.practitioner_id, (local_start AT TIME ZONE :zone) AS starts_at
        FROM days
        CROSS JOIN LATERAL generate_series(
            days.day + CAST(:opens_at AS time),
            days.day + CAST(:closes_at AS time) - make_interval(mins => :minutes),
            make_interval(mins => :minutes)
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
    hours = _availability(session, tenant_id=tenant_id)
    _role, minutes = APPOINTMENT_TYPES[appointment_type]
    result = session.connection().execute(
        _SLOTS_SQL,
        {
            "zone": TIMEZONE,
            "horizon": PUBLIC_HORIZON_DAYS,
            "working_days": list(hours.working_days),
            "opens_at": hours.opens_at,
            "closes_at": hours.closes_at,
            "minutes": minutes,
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


def _clinic_today(session: Session) -> date:
    value = session.connection().execute(
        text("SELECT (now() AT TIME ZONE :zone)::date"), {"zone": TIMEZONE}
    )
    today = value.scalar_one()
    assert isinstance(today, date)
    return today


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
) -> str:
    """Book from the public page: validate the slot, create or match the patient, book, audit.

    One transaction: the patient record, the booking and both audit events commit together or not at
    all, so a refused booking (`409 SLOT_TAKEN`) leaves no stray patient behind. The answer is the
    same reference whether the patient was new or matched.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_role="PUBLIC_BOOKING", source_ip=source_ip
    ) as session:
        if _age_on(body.date_of_birth, _clinic_today(session)) < MINIMUM_BOOKING_AGE:
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
        return booking_reference(appointment.id)
