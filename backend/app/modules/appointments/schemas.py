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
from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    model_validator,
)

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


class PublicBookingCreated(BaseModel):
    """The confirmation. The same shape whether the patient was new or matched (never says which)."""

    reference: str
