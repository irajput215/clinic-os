"""Consent library request and response models. Strict: unknown fields are refused."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

ConsentKind = Literal["PRIVACY", "TELEHEALTH", "TREATMENT"]
ConsentStatus = Literal["CURRENT", "NEEDS_RECONSENT", "WITHDRAWN", "NOT_GIVEN"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsentDocumentRead(_Strict):
    kind: ConsentKind
    version: str
    title: str
    body: str
    source: Literal["PLATFORM", "CLINIC"]
    published_at: datetime | None


class ConsentKindLibrary(_Strict):
    kind: ConsentKind
    current: ConsentDocumentRead
    clinic_versions: list[ConsentDocumentRead]
    patients_needing_reconsent: int


class ConsentLibrary(_Strict):
    kinds: list[ConsentKindLibrary]


class PublishConsent(_Strict):
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
    ]
    body: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=20, max_length=10_000)
    ]


class ConsentEvent(_Strict):
    kind: ConsentKind
    event: Literal["CONSENTED", "WITHDRAWN"]
    version: str | None
    title: str | None
    method: str
    at: datetime
    recorded_by: uuid.UUID | None


class KindStatus(_Strict):
    kind: ConsentKind
    title: str
    status: ConsentStatus
    current_version: str
    # The current wording, so staff can show the patient exactly what they are agreeing to.
    current_body: str
    signed_version: str | None
    signed_at: datetime | None
    withdrawn_at: datetime | None
    # What withdrawing or not holding this consent means for the clinic's work. Shown to staff only;
    # nothing is enforced automatically yet.
    stops: str


class PatientConsentStatus(_Strict):
    kinds: list[KindStatus]
    history: list[ConsentEvent]


class RecordConsent(_Strict):
    """A consent given in clinic. The version must be the one currently offered."""

    kind: ConsentKind
    version: Annotated[str, StringConstraints(max_length=32)]


class WithdrawConsent(_Strict):
    method: Literal["IN_PERSON", "PHONE", "WRITTEN"]
