"""Request and response schemas for the clinical-records module.

Design: `docs/features/06-clinical-records/03-design.md` §"Deny-by-default request path" step 7
(*"validate the body against a strict Pydantic model; unknown fields are rejected `422`"*) and
§"Endpoints". Requirements: R1, R2, R3, R7.

Every request model is strict — `extra="forbid"` — so a body carrying `tenant_id`, `author_id`,
`signed_at`, `version`, `id` or `current_version` is a `422` rather than a quietly ignored field
(R2, and threat T-CLIN-11's mass assignment). The attribution columns are server-set from the
session in every case.

The narrative is **one field**. A client may send either `body` (+ `body_format`) or the `soap`
authoring surface; a validator refuses a request that sends both, sends neither, or sends an empty
one (a `soap` whose every section is blank counts as empty). When `soap` is sent the service serialises it into `clinical_record_versions.body` — the single
narrative column R3 fixes — so there are no SOAP columns and no second notes table.

Response models declare exactly what the API returns. `ClinicalRecordVersionRead` exposes the
amendment reason under the design's API name (`amendment_reason`); the audit trail never does — see
`service.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Final, Self

from pydantic import AfterValidator, Field, model_validator
from sqlmodel import SQLModel

# PRIVATE API, deliberately: SQLModel annotates `model_config` as `SQLModelConfig`, so a plain
# `ConfigDict` is rejected by both mypy --strict and ty. The patients module records the same
# constraint for the same reason.
from sqlmodel._compat import SQLModelConfig

from app.modules.clinical_records.models import (
    BODY_FORMAT_VOCABULARY,
    RECORD_TYPE_VOCABULARY,
)

# The server-side bound on one narrative. The design fixes no number, so this is a repo decision,
# reported rather than assumed: an unbounded body is an unauthenticated-adjacent memory and storage
# vector (`build-contract.md` control 4, "size and list limits").
MAX_NOTE_BODY_LENGTH: Final[int] = 100_000

# The server-side bound on one page of the patient timeline, and the default. The design's
# performance target is "the last 50 entries before a review" (`20` §4).
DEFAULT_TIMELINE_PAGE_SIZE: Final[int] = 50
MAX_TIMELINE_PAGE_SIZE: Final[int] = 100

# The design's amendment-reason bound. `reason` is free text the clinician types; the column is
# TEXT, and this keeps one request from carrying a novel.
MAX_AMENDMENT_REASON_LENGTH: Final[int] = 2_000


def _check_record_type(value: str) -> str:
    """Validate against the model's vocabulary so the two cannot drift apart."""
    if value not in RECORD_TYPE_VOCABULARY:
        raise ValueError(
            f"record_type must be one of: {', '.join(RECORD_TYPE_VOCABULARY)}"
        )
    return value


def _check_body_format(value: str) -> str:
    if value not in BODY_FORMAT_VOCABULARY:
        raise ValueError(
            f"body_format must be one of: {', '.join(BODY_FORMAT_VOCABULARY)}"
        )
    return value


RecordType = Annotated[str, AfterValidator(_check_record_type)]
BodyFormat = Annotated[str, AfterValidator(_check_body_format)]


class SoapNote(SQLModel):
    """The `subjective` / `objective` / `assessment` / `plan` authoring surface.

    This is a **serialisation** of the single narrative column, never a storage shape: the service
    renders it into `clinical_record_versions.body` and no SOAP column exists anywhere (R3).
    """

    model_config = SQLModelConfig(extra="forbid", str_strip_whitespace=True)

    subjective: str | None = Field(default=None, max_length=MAX_NOTE_BODY_LENGTH)
    objective: str | None = Field(default=None, max_length=MAX_NOTE_BODY_LENGTH)
    assessment: str | None = Field(default=None, max_length=MAX_NOTE_BODY_LENGTH)
    plan: str | None = Field(default=None, max_length=MAX_NOTE_BODY_LENGTH)


def _exactly_one_narrative(body: str | None, soap: SoapNote | None) -> None:
    """Refuse a request that carries both narratives, or neither, or an empty SOAP surface.

    Sending `body` *and* `soap` would make the stored narrative depend on an unstated precedence
    rule; sending neither would insert an empty clinical note. Both are `422`, before any query.

    A SOAP surface counts as empty unless at least one section has non-blank text. Sections are
    whitespace-stripped first, so `{"subjective": "  "}` arrives as `""`; a presence check alone
    would let it render a heading-only narrative into the permanent record. A blank section beside
    a written one is still rendered (`docs2/sdlc/03-consult-notes/api.md`). The message is a
    constant: the refusal names the rule and never repeats the submitted text (INV-5).
    """
    if body is not None and soap is not None:
        raise ValueError("send either body or soap, not both")
    if body is None and soap is None:
        raise ValueError("one of body or soap is required")
    if soap is not None and not any(
        field for field in (soap.subjective, soap.objective, soap.assessment, soap.plan)
    ):
        raise ValueError("soap must carry at least one non-blank section")


class ClinicalRecordCreate(SQLModel):
    """The body of `POST /api/v1/clinical-records` (R1, R2).

    There is no `tenant_id`, `author_id`, `signed_at`, `version` or `current_version` field and
    there never will be: `extra="forbid"` turns one into a `422` (R2).
    """

    model_config = SQLModelConfig(extra="forbid", str_strip_whitespace=True)

    patient_id: uuid.UUID
    record_type: RecordType = "NOTE"
    body: str | None = Field(
        default=None, min_length=1, max_length=MAX_NOTE_BODY_LENGTH
    )
    body_format: BodyFormat | None = None
    soap: SoapNote | None = None

    @model_validator(mode="after")
    def _require_one_narrative(self) -> Self:
        _exactly_one_narrative(self.body, self.soap)
        return self


class ClinicalRecordAppend(SQLModel):
    """The body of `PATCH /api/v1/clinical-records/{id}` and of `POST .../amendments`.

    Both routes append: the design says they are *"the same code path"*, so they share this schema.
    A version is a complete document, not a patch to be merged, so the narrative is required in
    full — an append that omitted it would have to copy the previous narrative forward, which would
    silently attribute old text to a new author and time.

    `amendment_reason` is the design's API field for the `reason` column. Requirement R7 makes it
    mandatory whenever the new version number is above 1; that check needs the record's current
    version, so it runs in the service with the record loaded, and answers
    `422 AMENDMENT_REASON_REQUIRED`.
    """

    model_config = SQLModelConfig(extra="forbid", str_strip_whitespace=True)

    body: str | None = Field(
        default=None, min_length=1, max_length=MAX_NOTE_BODY_LENGTH
    )
    body_format: BodyFormat | None = None
    soap: SoapNote | None = None
    amendment_reason: str | None = Field(
        default=None, min_length=1, max_length=MAX_AMENDMENT_REASON_LENGTH
    )

    @model_validator(mode="after")
    def _require_one_narrative(self) -> Self:
        _exactly_one_narrative(self.body, self.soap)
        return self


class ClinicalRecordVersionRead(SQLModel):
    """One version as the API returns it.

    No `tenant_id` is declared: the caller already knows its own tenant, and nothing that is not
    needed is exposed. `body` is `HIGHLY_SENSITIVE` and this model is the **only** place it is
    serialised — never into a log line, an error envelope or an audit payload (INV-5, R15).
    """

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    id: uuid.UUID
    clinical_record_id: uuid.UUID
    version: int
    body: str
    body_format: str
    author_id: uuid.UUID
    signed_at: datetime | None = None
    supersedes_version: int | None = None
    # The design's API name for the `reason` column (`03-design.md`, schema table).
    amendment_reason: str | None = None
    created_at: datetime


class ClinicalRecordRead(SQLModel):
    """A clinical record as the API returns it, without its versions."""

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    record_type: str
    author_id: uuid.UUID
    current_version: int
    signed_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime


class ClinicalRecordDetail(ClinicalRecordRead):
    """A record plus every version, ascending (R9). The shape `GET .../{id}` returns."""

    versions: list[ClinicalRecordVersionRead]


class ClinicalRecordSummary(ClinicalRecordRead):
    """One timeline entry: the record's metadata and its current version's narrative."""

    latest_version: ClinicalRecordVersionRead


class ClinicalRecordsPublic(SQLModel):
    """A keyset page of the patient timeline plus the cursor for the next page."""

    data: list[ClinicalRecordSummary]
    count: int
    next_cursor: str | None = None
