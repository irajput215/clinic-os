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
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

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
