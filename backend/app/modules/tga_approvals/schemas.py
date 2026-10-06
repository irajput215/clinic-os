"""One request and one response schema per TGA approval endpoint.

Task T2-7: *"Pydantic v2 schemas per endpoint (list query, create, read, verify, revoke, supersede,
match in/out); unknown fields rejected; no route returns a raw ORM entity."*

Three rules shape every schema here:

* **`extra="forbid"` everywhere.** A `tenant_id`, a `state` or a `verified_by` in a body is a mass
  assignment attempt, and it is a `422` before the service is entered — never a silently ignored
  field (R2, S5). The tenant is resolved from the session and can never be supplied (INV-1).
* **No response model exposes an ORM entity, and none exposes a field the classification table in
  `05-data-and-audit.md` does not put on the wire.** `validity_interval` is deliberately not returned
  as an internal column: the wire shape is the pair of dates the client can act on.
* **Validation errors carry a code and never a value.** The `422` handler in `app.core.errors` drops
  `input`/`ctx`, so a `PydanticCustomError` raised below reaches the client as
  `{type, loc, msg}` — and `type` is the machine-readable code the feature documents name
  (`ERR_WINDOW_EXCEEDS_MAX_DURATION`), which is how R3's acceptance criterion is satisfied without
  echoing a HIGHLY_SENSITIVE value into an error body (INV-5).
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, PydanticCustomError, model_validator

from app.modules.tga_approvals.models import (
    CATEGORY_PATTERN,
    CODE_PATTERN,
    DOSAGE_FORM_PATTERN,
    MAX_DURATION_YEARS,
    REFERENCE_PATTERN,
)

# The code R3 names. It is a Pydantic error `type`, which is the one member of a `422` body that is
# machine-readable and value-free.
WINDOW_EXCEEDS_MAX_DURATION: Final[str] = "ERR_WINDOW_EXCEEDS_MAX_DURATION"
WINDOW_NOT_FORWARD: Final[str] = "ERR_WINDOW_NOT_FORWARD"

_TGA_CATEGORY = Annotated[str, Field(pattern=CATEGORY_PATTERN, max_length=32)]
_DOSAGE_FORM = Annotated[str, Field(pattern=DOSAGE_FORM_PATTERN, max_length=32)]
_REFERENCE = Annotated[str, Field(pattern=REFERENCE_PATTERN, max_length=64)]
_REASON_CODE = Annotated[str, Field(pattern=CODE_PATTERN, max_length=64)]


def _max_valid_to(valid_from: date) -> date:
    """The last date R3 permits: `valid_from` plus two years, clamped like PostgreSQL's interval.

    Kept identical to `ck_tga_approvals_max_duration`'s SQL (`(valid_from + interval '2 years')::date`)
    including the leap-day clamp, so the schema and the database refuse exactly the same dates.
    """
    try:
        anniversary = valid_from.replace(year=valid_from.year + MAX_DURATION_YEARS)
    except ValueError:  # 29 February -> 28 February, which is what PostgreSQL's interval does
        anniversary = valid_from.replace(
            year=valid_from.year + MAX_DURATION_YEARS, day=28
        )
    return anniversary


class _WindowedRequest(BaseModel):
    """The validity window, validated the same way for a create and for a supersede."""

    model_config = ConfigDict(extra="forbid")

    valid_from: date
    valid_to: date

    @model_validator(mode="after")
    def _window(self) -> "_WindowedRequest":
        if self.valid_to <= self.valid_from:
            raise PydanticCustomError(
                WINDOW_NOT_FORWARD,
                "valid_to must be later than valid_from",
            )
        if self.valid_to > _max_valid_to(self.valid_from):
            raise PydanticCustomError(
                WINDOW_EXCEEDS_MAX_DURATION,
                "the validity window may not exceed two years",
            )
        return self


class TgaApprovalCreate(_WindowedRequest):
    """`POST /api/v1/tga-approvals` — a manual entry, which starts `PENDING` (R1, R5, US-1).

    There is no `state`, no `source`, no `created_by`, no `verified_by` and no `tenant_id`: every one
    of those is the server's, and a body that carries one is refused as an unknown field.
    """

    patient_id: uuid.UUID
    tga_category: _TGA_CATEGORY
    dosage_form: _DOSAGE_FORM
    approval_reference: _REFERENCE
    creation_reason: _REASON_CODE


class TgaApprovalSupersede(_WindowedRequest):
    """`POST /api/v1/tga-approvals/{id}/supersede` — the replacement grant (T2-9, design §2).

    The replacement is created `PENDING` like any other manual entry: extensions and dosage changes
    require a new grant record, and a new grant record requires independent verification (R5, R12).
    What makes it a *supersede* is that `supersedes_id` names the grant it replaces, and the
    predecessor moves to `SUPERSEDED` — atomically, in the transaction that activates the
    replacement — rather than being edited in place.
    """

    approval_reference: _REFERENCE
    creation_reason: _REASON_CODE


class TgaApprovalVerify(BaseModel):
    """`POST /api/v1/tga-approvals/{id}/verify` — step 2 of four-eyes (R5, T2-13).

    The verifier must re-enter the application number from the source document: a verification that
    does not carry the reference it is verifying is not a check of anything, and the service refuses
    a mismatch. The actor is never in the body — it is the authenticated session.
    """

    model_config = ConfigDict(extra="forbid")

    tga_application_number: _REFERENCE


class TgaApprovalRevoke(BaseModel):
    """`POST /api/v1/tga-approvals/{id}/revoke` — a mandatory reason **code** (R9, T2-14).

    A code, not free text: `03-design.md` fixes that for `revoked_reason_code`, and free text in a
    revocation reason is clinical narrative that would reach the audit trail and the logs.
    """

    model_config = ConfigDict(extra="forbid")

    reason_code: _REASON_CODE


class TgaMatchRequest(BaseModel):
    """`POST /api/v1/tga-approvals/match` — the point-in-time gate lookup (T2-27, T2-29).

    `POST` and not `GET`, deliberately: `patient_id`, the category, the dosage form and the service
    date are all PHI-adjacent, and a query string is written to access logs, proxy logs and browser
    history. `date_of_service` is the consultation date the decision is evaluated at — never "now",
    which is what makes a late expiry sweep unable to allow an expired approval (design, "Expiry
    handling").
    """

    model_config = ConfigDict(extra="forbid")

    patient_id: uuid.UUID
    tga_category: _TGA_CATEGORY
    dosage_form: _DOSAGE_FORM
    date_of_service: date


class ValidityInterval(BaseModel):
    """The window a match was decided against, with the boundary rule it was read under."""

    valid_from: date
    valid_to: date
    #: `[)` — half-open, D-006 §2's interim fail-safe position. Present in the response so a disputed
    #: dispense can be reconstructed from the response alone.
    bounds: Literal["[)"] = "[)"


class TgaApprovalRead(BaseModel):
    """One approval. No `validity_interval` column, no internals, no document store key."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    tga_category: str
    dosage_form: str
    approval_reference: str
    valid_from: date
    valid_to: date
    state: str
    source: str
    created_by: uuid.UUID
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    revoked_by: uuid.UUID | None
    revoked_at: datetime | None
    revoked_reason_code: str | None
    superseded_by_id: uuid.UUID | None
    supersedes_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class SupersedeChainLink(BaseModel):
    """One row of the reconstructible history: what replaced what, and when it stopped being live."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    state: str
    valid_from: date
    valid_to: date
    supersedes_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None


class TgaApprovalDetail(TgaApprovalRead):
    """The detail read: the approval plus its supersede chain (T2-12)."""

    supersede_chain: list[SupersedeChainLink] = Field(default_factory=list)


class TgaApprovalsPublic(BaseModel):
    """One keyset page of approvals."""

    data: list[TgaApprovalRead]
    count: int
    next_cursor: str | None


class TgaMatchResponse(BaseModel):
    """The gate's answer (T2-27).

    `matched = false` is a `200`, not an error: a non-match is the safety gate working, and the
    reason code is what the prescribing screen explains. `state` and `approval_id` are populated even
    on a refusal when a row at the grain exists, so the clinician can be told *why*.
    """

    matched: bool
    reason_code: str | None
    state: str | None
    approval_id: uuid.UUID | None
    validity_interval: ValidityInterval | None
    date_of_service: date
    evaluated_timezone: str
