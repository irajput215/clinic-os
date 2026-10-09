"""Request and response schemas for the prescriptions API.

Every request model forbids unknown fields (FEAT-11 R2, R7; FEAT-10 R8): a body carrying `state`,
`tenant_id`, `approval_id`, `signed_by` or `schedule8_flag` is a `422` before any query runs, so a
client can neither choose a state, nor assert an approval, nor place a row in another tenant.

`prescriber_id` **is** accepted on staging, and that is a recorded reconciliation: FEAT-11 R2 lists it
among the refused fields while its own US-6 has a Nurse stage a draft "with the prescriber of record
recorded separately", and the docs2 script-queue requirement R1 makes the reviewing doctor required.
The server validates it - the account must be active, in the caller's organisation and hold
`prescription:sign` - and only that account can ever sign the row (a database check as well).

Clinical text fields (`medicine_name`, `dose_instruction`, `triage_outcome`,
`conventional_therapy`) are HIGHLY_SENSITIVE (`11-prescribing/05-data-and-audit.md`): they are stored
and returned to the clinic, and never reach a log line, an audit payload or an error body - a `422`
carries `type`/`loc`/`msg` only (`app.core.errors`).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.modules.tga_approvals.models import CATEGORY_PATTERN
from app.modules.tga_approvals.schemas import TgaMatchResponse

_CONTROL = frozenset(chr(code) for code in (*range(0x20), 0x7F))


def _clinical_text(limit: int) -> AfterValidator:
    def check(value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        if len(value) > limit:
            raise ValueError(f"must be at most {limit} characters")
        if any(character in _CONTROL for character in value):
            raise ValueError("must not contain control characters")
        return value

    return AfterValidator(check)


_TEXT_200 = Annotated[str, Field(max_length=400), _clinical_text(200)]
_TEXT_300 = Annotated[str, Field(max_length=600), _clinical_text(300)]
_TEXT_500 = Annotated[str, Field(max_length=1000), _clinical_text(500)]
_GRAIN_TOKEN = Annotated[str, Field(pattern=CATEGORY_PATTERN, max_length=32)]
# A step-up token is `secrets.token_urlsafe(32)`: 43 URL-safe characters. Bounded so a hostile value
# never reaches the hash.
_STEP_UP_TOKEN = Annotated[str, Field(min_length=16, max_length=128)]


class PrescriptionCreate(BaseModel):
    """`POST /api/v1/prescriptions`: stage a draft (FEAT-11 R1; docs2 07 R1)."""

    model_config = ConfigDict(extra="forbid")

    patient_id: uuid.UUID
    prescriber_id: uuid.UUID
    medicine_name: _TEXT_200
    tga_category: _GRAIN_TOKEN
    dosage_form: _GRAIN_TOKEN
    dose_instruction: _TEXT_500
    quantity: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
    repeats: Annotated[int, Field(ge=0, le=12)]
    triage_outcome: _TEXT_300
    conventional_therapy: _TEXT_300
    date_of_service: date


class _PayloadChange(BaseModel):
    """The clinical fields a draft edit or an addendum may change; every one optional.

    A field the client sends must carry a value: an explicit `null` is a `422` (each column is NOT
    NULL), and a body that changes nothing is a `422` too. `state`, `tenant_id`, `patient_id`,
    `approval_id` and the signature are not fields here, so a body carrying one is refused as unknown.
    """

    model_config = ConfigDict(extra="forbid")

    medicine_name: _TEXT_200 | None = None
    tga_category: _GRAIN_TOKEN | None = None
    dosage_form: _GRAIN_TOKEN | None = None
    dose_instruction: _TEXT_500 | None = None
    quantity: (
        Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)] | None
    ) = None
    repeats: Annotated[int, Field(ge=0, le=12)] | None = None
    triage_outcome: _TEXT_300 | None = None
    conventional_therapy: _TEXT_300 | None = None
    date_of_service: date | None = None

    @model_validator(mode="after")
    def _changes_something(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        nulls = sorted(
            name for name in self.model_fields_set if getattr(self, name) is None
        )
        if nulls:
            raise ValueError(f"these fields cannot be cleared: {', '.join(nulls)}")
        return self

    def changes(self) -> dict[str, object]:
        """The fields the client sent, with their values (for the row, never for a log line)."""
        return {name: getattr(self, name) for name in sorted(self.model_fields_set)}


class PrescriptionUpdate(_PayloadChange):
    """`PATCH /api/v1/prescriptions/{id}`: correct a `DRAFT` (FEAT-11 R3, US-2).

    The reviewing doctor may be changed while the script is a draft; the server validates the new one
    exactly as on staging.
    """

    prescriber_id: uuid.UUID | None = None


class PrescriptionAddendum(_PayloadChange):
    """`POST /api/v1/prescriptions/{id}/addendum`: the correction to a signed script (FEAT-11 R5).

    The new version keeps the original's patient and prescriber of record; it starts as a `DRAFT` and
    is signed like any other. The intent key is the `Idempotency-Key` header.
    """


#: The reasons a person may give for cancelling (decision D-010, interim; the vocabulary is OPEN with
#: the Clinical Safety Officer). `SUPERSEDED_BY_ADDENDUM` is the server's own and is not offered.
CancelReason = Literal[
    "ENTERED_IN_ERROR", "CLINICALLY_NOT_REQUIRED", "PATIENT_DECLINED", "DUPLICATE"
]


class PrescriptionCancel(BaseModel):
    """`POST /api/v1/prescriptions/{id}/cancel`: a reason **code**, never free text (FEAT-11 R11)."""

    model_config = ConfigDict(extra="forbid")

    reason_code: CancelReason


class PrescriptionSign(BaseModel):
    """`POST /api/v1/prescriptions/{id}/sign`: the single-use step-up proof, and nothing else."""

    model_config = ConfigDict(extra="forbid")

    step_up_token: _STEP_UP_TOKEN


class PrescriptionDispatch(BaseModel):
    """`POST /api/v1/prescriptions/{id}/dispatch`: the step-up proof. The intent key is a header."""

    model_config = ConfigDict(extra="forbid")

    step_up_token: _STEP_UP_TOKEN


class DispatchRead(BaseModel):
    """The latest outbox row for a prescription - what the clinic may be told about delivery.

    `transport_configured` is the honest half of the answer: while it is `false`, a `QUEUED` row
    has been accepted by ClinicOS and **has not been sent to any pharmacy**.
    """

    model_config = ConfigDict(from_attributes=True)

    state: str
    attempt_seq: int
    provider: str | None
    provider_reference: str | None
    outcome_class: str | None
    requested_at: datetime
    resolved_at: datetime | None
    transport_configured: bool


class PrescriptionRead(BaseModel):
    """One prescription with the names a clinical list shows and, when actionable, the live gate."""

    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None
    prescriber_id: uuid.UUID
    prescriber_name: str | None
    drafted_by: uuid.UUID
    drafted_by_name: str | None
    medicine_name: str
    tga_category: str
    dosage_form: str
    dose_instruction: str
    quantity: Decimal
    repeats: int
    triage_outcome: str
    conventional_therapy: str
    date_of_service: date
    state: str
    approval_id: uuid.UUID | None
    created_at: datetime
    signed_at: datetime | None
    #: Set when the script was cancelled: the reason code (decision D-010).
    cancel_reason_code: str | None = None
    #: An addendum names the signed original it corrects (FEAT-11 R5).
    supersedes_id: uuid.UUID | None = None
    #: The gate re-evaluated **now**, against the approvals as they are now, for a prescription that
    #: still needs an action (docs2 07 R2). `None` for a terminal or in-flight one.
    gate: TgaMatchResponse | None
    dispatch: DispatchRead | None


class PrescriptionsPublic(BaseModel):
    """One keyset page of the queue and its history, newest first."""

    data: list[PrescriptionRead]
    next_cursor: str | None


class PrescriptionQueueSummary(BaseModel):
    """The script queue at a glance (the Today page, `docs2/sdlc/08-today`).

    `by_state` carries every state, zero included. `QUEUED` while `transport_configured` is `false`
    means accepted by ClinicOS and **not sent** to any pharmacy.
    """

    by_state: dict[str, int]
    transport_configured: bool
    #: The newest prescriptions still needing a human action, each with the gate's answer now.
    actionable: list[PrescriptionRead]
    #: How many of the `gate_checked` newest actionable prescriptions the gate refuses now.
    gate_refused: int
    #: How many actionable prescriptions were asked (all of them, up to a bound of 100).
    gate_checked: int


class PrescriberRead(BaseModel):
    """An account that may sign: the reviewing-doctor choice when staging."""

    id: uuid.UUID
    name: str


class PrescribersPublic(BaseModel):
    data: list[PrescriberRead]


class PrescriptionEventRead(BaseModel):
    """One transition of a prescription, oldest first: who moved it, when, and the reason code."""

    from_state: str | None
    to_state: str
    reason: str | None
    actor_id: uuid.UUID | None
    actor_name: str | None
    occurred_at: datetime


class PrescriptionHistory(BaseModel):
    """`GET /api/v1/prescriptions/{id}/history` (FEAT-11 US-10): the ordered transition list, and
    the versions either side of an addendum."""

    prescription_id: uuid.UUID
    supersedes_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None
    data: list[PrescriptionEventRead]
