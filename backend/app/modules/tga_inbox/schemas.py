"""Request and response models for the TGA inbox API. Strict: unknown fields are refused.

No request model carries a `tenant_id`, a `state`, a `score` or an `accepted_by` (design,
"Endpoints"): the tenant comes from the mailbox address or the session, and every state is the
server's.
"""

import base64
import binascii
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.modules.tga_inbox.models import FIELD_NAMES, MAX_ATTACHMENTS

AuthResult = Literal[
    "PASS", "FAIL", "SOFTFAIL", "NEUTRAL", "NONE", "TEMPERROR", "PERMERROR"
]
FieldName = Literal[
    "APPROVAL_REFERENCE",
    "PATIENT_NAME",
    "PATIENT_DOB",
    "PATIENT_IHI",
    "PATIENT_MEDICARE",
    "TGA_CATEGORY",
    "DOSAGE_FORM",
    "VALID_FROM",
    "VALID_TO",
    "PRESCRIBER_NAME",
    "PRESCRIBER_HPI_I",
]
assert set(FieldName.__args__) == set(FIELD_NAMES)  # type: ignore[attr-defined]

ReasonCode = Annotated[
    str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$", max_length=64)
]
# Base64 of at most 25 MB of bytes, decoded before the pipeline sees it.
_MAX_BASE64 = (25 * 1024 * 1024 * 4) // 3 + 4


def _decode(value: object) -> bytes:
    if not isinstance(value, str) or len(value) > _MAX_BASE64 + 1024:
        raise ValueError("content must be base64 of at most about 25 MB")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("content must be base64") from error


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- ingest (the mailbox adapter) -------------------------------------------------------------


class InboundAttachmentIn(_Strict):
    filename: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    content_type: Annotated[str, StringConstraints(min_length=1, max_length=127)]
    # Bounded at the schema so an oversized body is refused before it is decoded. A file over the
    # 25 MB cap that still fits here is recorded as refused (`TOO_LARGE`), not silently dropped.
    content_base64: Annotated[bytes, BeforeValidator(_decode)]


class InboundMessageIn(_Strict):
    """What the mailbox adapter delivers: the parsed envelope and the authentication results the
    receiving server recorded (FEAT-09 R2)."""

    provider_message_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    from_address: EmailStr
    # Not `EmailStr`: the inbox domain may be an internal one (`.local`) the validator refuses, and
    # the address is matched exactly against the clinic inbox form anyway (`tenant_for_address`).
    to_address: Annotated[
        str,
        StringConstraints(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$"),
    ]
    subject: Annotated[str, StringConstraints(max_length=998)] = ""
    received_at: datetime
    spf_result: AuthResult | None = None
    dkim_result: AuthResult | None = None
    dmarc_result: AuthResult | None = None
    # More than the cap is accepted here so the extra files can be recorded as refused (R3, R19).
    attachments: Annotated[
        list[InboundAttachmentIn], Field(max_length=MAX_ATTACHMENTS * 2)
    ] = []


class IngestResult(_Strict):
    message_id: uuid.UUID
    processing_state: str
    duplicate: bool


# -- the review queue ---------------------------------------------------------------------------


class InboxMessageSummary(_Strict):
    id: uuid.UUID
    received_at: datetime
    from_address: str
    subject: str | None
    processing_state: str
    state_reason: str | None
    attachment_count: int
    clean_attachment_count: int
    composite_score: Decimal | None
    claimed_by: uuid.UUID | None
    lease_expires_at: datetime | None


class InboxQueue(_Strict):
    data: list[InboxMessageSummary]
    count: int


class AttachmentRead(_Strict):
    id: uuid.UUID
    filename: str
    content_type: str | None
    size_bytes: int
    scan_state: str
    text_state: str
    page_count: int | None
    refusal_reason: str | None
    viewable: bool


class ExtractedFieldRead(_Strict):
    attachment_id: uuid.UUID
    field_name: FieldName
    value: str | None
    confidence: Decimal | None
    method: str | None
    page_number: int | None
    below_floor: bool
    mandatory: bool


class MatchCandidateRead(_Strict):
    patient_id: uuid.UUID
    display_name: str
    date_of_birth: date
    agreed: list[str]


class InboxMessageDetail(InboxMessageSummary):
    spf_result: str | None
    dkim_result: str | None
    dmarc_result: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    patient_id: uuid.UUID | None
    approval_id: uuid.UUID | None
    extractor_version: str | None
    attachments: list[AttachmentRead]
    fields: list[ExtractedFieldRead]
    candidates: list[MatchCandidateRead]


# -- decisions ------------------------------------------------------------------------------------


class AcceptRequest(_Strict):
    """Accept or correct (FEAT-09 R16). `values` overrides what was extracted, field by field; any
    override makes this a correction, which needs a `correction_reason`. The patient is chosen by the
    reviewer from the candidates (or by search): nothing is pre-selected (R15)."""

    patient_id: uuid.UUID
    attachment_id: uuid.UUID
    values: dict[FieldName, Annotated[str, StringConstraints(max_length=120)]] = {}
    correction_reason: ReasonCode | None = None


class RejectRequest(_Strict):
    reason_code: ReasonCode


class DecisionResult(_Strict):
    message_id: uuid.UUID
    processing_state: str
    approval_id: uuid.UUID | None = None
