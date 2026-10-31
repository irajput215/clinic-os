"""Request and response shapes for patient intake (docs3 feature 03).

Every request model is strict (`extra="forbid"`): a `tenant_id`, a status or a flag in a body is a
`422`, never a quietly ignored field. Free text is bounded and stripped. The vocabularies are closed,
so an answer the doctor's briefing does not know how to show cannot be stored.
"""

import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

PrimaryCondition = Literal[
    "CHRONIC_PAIN",
    "SLEEP",
    "ANXIETY",
    "DEPRESSION",
    "PTSD",
    "NAUSEA",
    "NEUROLOGICAL",
    "OTHER",
]
CannabisForm = Literal["DRY_HERB", "OIL", "CAPSULE", "VAPE", "EDIBLE", "OTHER"]
CannabisDuration = Literal[
    "LESS_THAN_6_MONTHS", "SIX_TO_24_MONTHS", "MORE_THAN_2_YEARS"
]
ConsentKind = Literal["PRIVACY", "TELEHEALTH", "TREATMENT"]
AuState = Literal["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]
RejectReason = Literal[
    "NOT_ELIGIBLE", "NEEDS_IN_PERSON_REVIEW", "DUPLICATE", "INCOMPLETE", "OTHER"
]

_STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SafetyAnswers(BaseModel):
    """The safety screen (manual §5.1 step 2). A "yes" is a flag for the doctor, never a stop.

    The question set is provisional until the Clinical Safety Officer confirms it (docs3 R3).
    """

    model_config = _STRICT

    psychosis_history: bool
    pregnant_or_breastfeeding: bool
    heart_condition: bool
    substance_dependence: bool


class OwnPharmacy(BaseModel):
    """The patient's own pharmacy, in full (manual §5.1 step 5)."""

    model_config = _STRICT

    name: str = Field(min_length=1, max_length=255)
    suburb: str = Field(min_length=1, max_length=255)
    address: str = Field(min_length=1, max_length=255)
    email: EmailStr = Field(max_length=255)
    phone: str = Field(min_length=6, max_length=64)
    provider_number: str | None = Field(default=None, max_length=32)


class ConsentGiven(BaseModel):
    model_config = _STRICT

    kind: ConsentKind
    version: str = Field(min_length=1, max_length=32)


class IntakeApplicationIn(BaseModel):
    """Steps 1-6 of the public application, beyond the name, birth date and contact details the
    booking already carries."""

    model_config = _STRICT

    # Step 1 - about you (the rest is on the booking).
    sex_at_birth: Literal["FEMALE", "MALE", "INTERSEX"]
    address_line: str = Field(min_length=1, max_length=255)
    suburb: str = Field(min_length=1, max_length=255)
    state: AuState
    postcode: str = Field(pattern=r"^\d{4}$")
    # Step 2 - health screen.
    primary_condition: PrimaryCondition
    other_conditions: list[str] = Field(default_factory=list, max_length=8)
    current_medicines: str = Field(default="", max_length=500)
    safety: SafetyAnswers
    tried_conventional: bool
    conventional_detail: str = Field(default="", max_length=500)
    # Step 3 - cannabis history.
    cannabis_used_before: bool
    cannabis_forms: list[CannabisForm] = Field(default_factory=list, max_length=6)
    cannabis_duration: CannabisDuration | None = None
    side_effects: str = Field(default="", max_length=300)
    what_helped: str = Field(default="", max_length=300)
    # Step 4 - consents, each at the version shown.
    consents: list[ConsentGiven] = Field(min_length=1, max_length=3)
    # Step 5 - pharmacy: a partner from the clinic's directory, or the patient's own.
    pharmacy_id: uuid.UUID | None = None
    own_pharmacy: OwnPharmacy | None = None
    # Step 6 - the declaration: the patient types their full name.
    declaration_name: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if (self.pharmacy_id is None) == (self.own_pharmacy is None):
            raise ValueError("choose a partner pharmacy or give your own, not both")
        if any(not 0 < len(c.strip()) <= 60 for c in self.other_conditions):
            raise ValueError("each other condition is 1 to 60 characters")
        return self


class PublicConsent(BaseModel):
    kind: str
    version: str
    title: str
    body: str


class PublicPharmacy(BaseModel):
    """A partner pharmacy as the public page shows it: name and suburb only."""

    id: uuid.UUID
    name: str
    suburb: str


class IntakeForm(BaseModel):
    """`GET /public/{clinic_slug}/intake-form`: what the application needs to show."""

    consents: list[PublicConsent]
    partner_pharmacies: list[PublicPharmacy]


# -- staff -----------------------------------------------------------------------------------------


class ApplicationCard(BaseModel):
    """One row of the applications queue: enough to triage, no answers."""

    id: uuid.UUID
    status: str
    created_at: datetime
    patient_id: uuid.UUID
    patient_name: str
    date_of_birth: date
    matched_existing: bool
    flags: list[str]
    appointment_starts_at: datetime | None


class ApplicationDetail(ApplicationCard):
    answers: dict[str, object]
    consents: list[dict[str, str]]
    pharmacy: dict[str, object] | None
    declaration_name: str
    declared_at: datetime
    decided_at: datetime | None
    decision_reason_code: str | None
    decision_note: str | None


class RejectBody(BaseModel):
    model_config = _STRICT

    reason_code: RejectReason
    note: str | None = Field(default=None, max_length=500)


class IntakeBriefing(BaseModel):
    """The doctor's one-glance briefing before the first consult (manual §5.4).

    Built from the patient's own answers. No range suggestion (decision D11), and never shown to the
    patient.
    """

    application_id: uuid.UUID
    submitted_at: datetime
    primary_condition: str
    other_conditions: list[str]
    tried_conventional: bool
    conventional_detail: str
    current_medicines: str
    safety_flags: list[str]
    cannabis_used_before: bool
    cannabis_forms: list[str]
    cannabis_duration: str | None
    side_effects: str
    what_helped: str
    pharmacy: dict[str, object] | None
    declaration_name: str
    declared_at: datetime


class ConsentRecord(BaseModel):
    kind: str
    version: str
    title: str
    method: str
    signed_at: datetime
    current: bool


# -- pharmacies ------------------------------------------------------------------------------------


class PharmacyCreate(BaseModel):
    model_config = _STRICT

    name: str = Field(min_length=1, max_length=255)
    suburb: str = Field(min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    provider_number: str | None = Field(default=None, max_length=32)
    is_partner: bool = False


class PharmacyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    suburb: str
    address: str | None
    email: str | None
    phone: str | None
    provider_number: str | None
    is_partner: bool


class PreferredPharmacy(BaseModel):
    model_config = _STRICT

    pharmacy_id: uuid.UUID | None
