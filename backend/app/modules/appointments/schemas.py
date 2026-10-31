"""Request and response models for the appointments API.

Every request model is strict (`extra="forbid"`): a `status`, `ends_at`, `source` or `created_by` in a
body is a `422`, never a silently ignored field, because the server decides each of them. The one
exception is `tenant_id`, which INV-1 says is **ignored and audited** rather than refused: it is dropped
before validation and the router records the attempt in the request's own transaction.

The public booking body accepts the minimum a booking needs and nothing clinical: name, date of birth
and contact details (to create or match the patient), the slot, and the APP 5 consent. The page's
eligibility questions stay in the browser - they decide whether to offer a booking, and a free-text
"what would you like help with" from an anonymous form is health information the clinic does not need
before the consult.
"""

import uuid
from datetime import date, datetime, time
from typing import Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    field_serializer,
    model_validator,
)

from app.modules.intake.schemas import IntakeApplicationIn

AppointmentType = Literal["NURSE_TRIAGE", "INITIAL_CONSULT", "FOLLOW_UP"]
AppointmentStatus = Literal[
    "BOOKED", "CONFIRMED", "ARRIVED", "COMPLETED", "CANCELLED", "NO_SHOW"
]
AppointmentSource = Literal["STAFF", "PUBLIC_BOOKING"]
PractitionerRole = Literal["DOCTOR", "NURSE"]

# An Australian mobile, with or without the country code and the usual spaces (R5).
AU_MOBILE_PATTERN = r"^(\+?61|0)4\d{2} ?\d{3} ?\d{3}$"
# A personal name as typed: letters, spaces and the punctuation names carry. No control characters,
# no markup, bounded - the field reaches a clinical record.
NAME_PATTERN = r"^[^\x00-\x1f\x7f<>]{1,100}$"


class _IgnoresClientTenantId(BaseModel):
    """Strict, except that a `tenant_id` key is dropped and remembered (INV-1: ignored and audited)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    _client_tenant_id_supplied: bool = PrivateAttr(default=False)

    @model_validator(mode="wrap")
    @classmethod
    def _ignore_client_tenant_id(
        cls, data: Any, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        supplied = isinstance(data, dict) and "tenant_id" in data
        if supplied:
            data = {key: value for key, value in data.items() if key != "tenant_id"}
        model = handler(data)
        model._client_tenant_id_supplied = supplied
        return model

    @property
    def client_tenant_id_supplied(self) -> bool:
        """Whether the body carried a `tenant_id` (which was ignored)."""
        return self._client_tenant_id_supplied


class PractitionerRead(BaseModel):
    """A bookable member of staff: an active account holding a Doctor, Authorised Prescriber or
    Nurse role in the session's organisation."""

    id: uuid.UUID
    name: str
    role: PractitionerRole
    title: str


class AppointmentRead(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    practitioner_id: uuid.UUID
    type: AppointmentType
    status: AppointmentStatus
    starts_at: datetime
    ends_at: datetime
    source: AppointmentSource
    created_at: datetime


class DayAppointment(AppointmentRead):
    """One booking on a day's schedule, with the practitioner's display name (Today, R2)."""

    #: `None` when the account is no longer this organisation's.
    practitioner_name: str | None


class DaySchedule(BaseModel):
    """One clinic day's bookings, earliest first, and how many are in each status.

    `by_status` carries every status, zero included, so a client never has to know the vocabulary
    to draw a count.
    """

    by_status: dict[AppointmentStatus, int]
    data: list[DayAppointment]


class AppointmentCreate(_IgnoresClientTenantId):
    """`POST /appointments`. The server computes `ends_at` from the type (R2)."""

    patient_id: uuid.UUID
    practitioner_id: uuid.UUID
    type: AppointmentType
    starts_at: AwareDatetime


class AppointmentStatusUpdate(BaseModel):
    """`POST /appointments/{id}/status`."""

    model_config = ConfigDict(extra="forbid")

    status: AppointmentStatus


class PublicSlot(BaseModel):
    """One free, bookable time. Only what the booking page shows: never another patient's data."""

    practitioner_id: uuid.UUID
    practitioner_name: str
    starts_at: datetime
    ends_at: datetime


class PublicBookingRequest(_IgnoresClientTenantId):
    """`POST /public/{clinic_slug}/bookings`: a slot, who the patient is, and the APP 5 consent."""

    type: AppointmentType
    practitioner_id: uuid.UUID
    starts_at: AwareDatetime
    given_name: str = Field(pattern=NAME_PATTERN)
    family_name: str = Field(pattern=NAME_PATTERN)
    date_of_birth: date
    email: EmailStr = Field(max_length=255)
    phone: str = Field(pattern=AU_MOBILE_PATTERN, max_length=16)
    # R5: consent to the APP 5 collection notice. `true` is the only value that books.
    consent: Literal[True]
    # docs3 feature 03: the six-step application. With it, the booking is held for the clinic to
    # review (Patients > Online applications); without it, a plain booking as before.
    application: IntakeApplicationIn | None = None


class PublicBookingCreated(BaseModel):
    """The confirmation. The same shape whether the patient was new or matched (never says which)."""

    reference: str


# -- clinic hours and slot length (docs2/sdlc/04-calendar-and-booking/api.md, 2026-10-08) -----------

SlotMinutes = Literal[10, 15, 20, 30, 60]
WEEKDAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
# Opening and closing times sit on 5-minute marks (`ck_appointment_hours_on_the_mark`).
_MARK_MINUTES = 5


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


class DayHours(BaseModel):
    """One weekday's hours. Closed is both times `null`."""

    model_config = ConfigDict(extra="forbid")

    weekday: int = Field(ge=1, le=7, description="ISO weekday, Monday = 1")
    opens_at: time | None = None
    closes_at: time | None = None

    @field_serializer("opens_at", "closes_at")
    def _as_hhmm(self, value: time | None) -> str | None:
        return None if value is None else value.strftime("%H:%M")


class AppointmentSettingsRead(BaseModel):
    """`GET /appointment-settings`: the slot length and seven days of hours, Monday first."""

    slot_minutes: int
    hours: list[DayHours]
    #: `True` while the clinic has never saved its own settings (the module defaults apply).
    is_default: bool


class AppointmentSettingsSaved(AppointmentSettingsRead):
    """`PUT /appointment-settings`: the saved settings, and how many upcoming live bookings now fall
    outside the hours. Those bookings are kept; the count lets the screen say so."""

    bookings_outside_hours: int


class AppointmentSettingsUpdate(_IgnoresClientTenantId):
    """`PUT /appointment-settings`. Strict; every rule is a `422` naming the day it is about."""

    slot_minutes: SlotMinutes
    hours: list[DayHours] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def _one_valid_interval_per_day(self) -> Self:
        if sorted(day.weekday for day in self.hours) != list(range(1, 8)):
            raise ValueError("Give each day of the week exactly once.")
        ordered = sorted(self.hours, key=lambda d: d.weekday)
        open_days = 0
        for day in ordered:
            name = WEEKDAY_NAMES[day.weekday - 1]
            if day.opens_at is None and day.closes_at is None:
                continue
            if day.opens_at is None or day.closes_at is None:
                raise ValueError(f"{name}: give both an opening and a closing time.")
            for moment in (day.opens_at, day.closes_at):
                if (
                    moment.minute % _MARK_MINUTES
                    or moment.second
                    or moment.microsecond
                    or moment.tzinfo is not None
                ):
                    raise ValueError(f"{name}: use times on 5-minute marks.")
            if day.closes_at <= day.opens_at:
                raise ValueError(f"{name}: closing must be after opening.")
            if _minutes(day.closes_at) - _minutes(day.opens_at) < self.slot_minutes:
                raise ValueError(
                    f"{name}: open for at least one {self.slot_minutes}-minute slot."
                )
            open_days += 1
        if open_days == 0:
            raise ValueError("Open the clinic on at least one day.")
        self.hours = ordered
        return self


class NotificationRunReport(BaseModel):
    """What one run of the booking-email job did, in counts only."""

    sent: int = 0
    skipped: int = 0
    failed: int = 0
    retried: int = 0
