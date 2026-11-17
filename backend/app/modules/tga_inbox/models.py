"""The TGA inbox tables: a received message, its attachments, and what was read from them.

Design: `docs/features/09-tga-inbox/03-design.md` ("Inbox tables", "Queue and reprocess state
machine"). Architecture: `docs/reference/decisions/D-011-tga-inbox-pipeline-architecture.md`.

Three tables, all tenant tables with the forced RLS pair (the migration creates the policies):

* `tga_inbox_messages` — one received email, its sender-authentication results, where it is in the
  pipeline and, once a person decides, the decision. The review fields (`claimed_by`, the lease,
  `decided_by`, `approval_id`) are the design's OPEN-4 proposal, held on the message rather than in a
  separate queue table because a message is the unit a reviewer claims.
* `tga_inbox_attachments` — one file. Append-only: the app role holds `SELECT, INSERT`. A refused
  file is still recorded (with `refusal_reason` and no `object_key`), so every attachment ends in a
  state a person can find (R1, R19).
* `tga_extraction_results` — one candidate value per field per extractor version. The value as read
  is immutable; only `accepted_value`, `accepted_by` and `accepted_at` may change, by grant.

## What is encrypted

The subject line and every extracted value are `HIGHLY_SENSITIVE` (a patient's name, IHI, Medicare
number, date of birth). They are stored as AES-GCM ciphertext through `app.core.field_crypto`, bound
to the tenant and the field, so the database never holds them in plaintext and a value copied to
another tenant's row fails to decrypt. The sender address is kept in plaintext: it is the TGA's
address, not a patient's, and the sender check reads it.

## Deviations from the design table, recorded

* `raw_object_key` is not kept: the mailbox adapter delivers a parsed message, and the originals that
  matter (the attachments) each have their own key. A raw `.eml` store is a later step with the real
  mailbox (D-011 step 6).
* `field_name` is wider than the design's five values. A TGA approval letter carries the approval
  reference, the patient's identifiers and the prescriber's, and the matcher needs them (FEAT-09 R10).
* `scan_state` adds `NOT_SCANNED` for a file refused before the scan (wrong type, too big), which
  would otherwise have to claim a scan that never ran.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


# The message lifecycle (design, "Queue and reprocess state machine"). `EXTRACTING` is reserved for
# the worker that will run the stages asynchronously; the stand-in pipeline runs them in one request.
MESSAGE_STATES: Final[tuple[str, ...]] = (
    "RECEIVED",
    "EXTRACTING",
    "EXTRACTED",
    "FAILED",
    "VERIFIED",
    "REJECTED",
)
# A message a reviewer may still act on.
OPEN_STATES: Final[tuple[str, ...]] = ("EXTRACTED", "FAILED")

# SPF, DKIM and DMARC results as the receiving mail server reports them (RFC 8601 result names).
AUTH_RESULTS: Final[tuple[str, ...]] = (
    "PASS",
    "FAIL",
    "SOFTFAIL",
    "NEUTRAL",
    "NONE",
    "TEMPERROR",
    "PERMERROR",
)

SCAN_STATES: Final[tuple[str, ...]] = (
    "PENDING",
    "CLEAN",
    "INFECTED",
    "ERROR",
    "NOT_SCANNED",
)

# What the text-layer reader made of a clean file (R7). `ENCRYPTED` is never cracked; it goes to a
# person. `NO_TEXT` is a scanned image: OCR is the next step, and until a real OCR adapter is
# configured it goes to a person too.
TEXT_STATES: Final[tuple[str, ...]] = (
    "NOT_ATTEMPTED",
    "EXTRACTED",
    "NO_TEXT",
    "ENCRYPTED",
    "FAILED",
)

FIELD_NAMES: Final[tuple[str, ...]] = (
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
)

# How a value was found. Two independent methods agreeing is what earns a high confidence (design
# stage 8: "never a single method").
EXTRACTION_METHODS: Final[tuple[str, ...]] = ("LABEL_AND_PATTERN", "LABEL", "PATTERN")

# A reason or refusal **code**, never free text: these reach the review screen and the audit trail.
CODE_PATTERN: Final[str] = r"^[A-Z][A-Z0-9_]{0,63}$"

MAX_ATTACHMENT_BYTES: Final[int] = 25 * 1024 * 1024
MAX_ATTACHMENTS: Final[int] = 10

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _id() -> Any:
    return Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )


def _tenant() -> Any:
    return Field(foreign_key="tenants.id", ondelete="RESTRICT", nullable=False)


class TgaInboxMessage(SQLModel, table=True):
    """One email received at a clinic's TGA inbox address."""

    __tablename__ = "tga_inbox_messages"
    __table_args__ = (
        sa.CheckConstraint(
            f"processing_state IN ({_sql_list(MESSAGE_STATES)})",
            name="processing_state",
        ),
        sa.CheckConstraint(
            f"spf_result IS NULL OR spf_result IN ({_sql_list(AUTH_RESULTS)})",
            name="spf_result",
        ),
        sa.CheckConstraint(
            f"dkim_result IS NULL OR dkim_result IN ({_sql_list(AUTH_RESULTS)})",
            name="dkim_result",
        ),
        sa.CheckConstraint(
            f"dmarc_result IS NULL OR dmarc_result IN ({_sql_list(AUTH_RESULTS)})",
            name="dmarc_result",
        ),
        sa.CheckConstraint(
            f"state_reason IS NULL OR state_reason ~ '{CODE_PATTERN}'",
            name="state_reason",
        ),
        sa.CheckConstraint(
            f"decision_reason IS NULL OR decision_reason ~ '{CODE_PATTERN}'",
            name="decision_reason",
        ),
        # A failed message says why; a decided message says who and when.
        sa.CheckConstraint(
            "processing_state <> 'FAILED' OR state_reason IS NOT NULL",
            name="failed_reason",
        ),
        sa.CheckConstraint(
            "processing_state NOT IN ('VERIFIED', 'REJECTED')"
            " OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="decided",
        ),
        sa.CheckConstraint(
            "processing_state <> 'REJECTED' OR decision_reason IS NOT NULL",
            name="rejected_reason",
        ),
        # Verified means an approval exists for it (FEAT-09 stage 12).
        sa.CheckConstraint(
            "processing_state <> 'VERIFIED' OR approval_id IS NOT NULL",
            name="verified_approval",
        ),
        # A claim is the claimant, the moment and the lease, together or not at all.
        sa.CheckConstraint(
            "(claimed_by IS NULL) = (claimed_at IS NULL)"
            " AND (claimed_by IS NULL) = (lease_expires_at IS NULL)",
            name="claim",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tga_inbox_messages_tenant_id_id"
        ),
        # A redelivered message is the same message (R18).
        sa.UniqueConstraint(
            "tenant_id",
            "provider_message_id",
            name="uq_tga_inbox_messages_tenant_provider_message",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["tga_approvals.tenant_id", "tga_approvals.id"],
            name="fk_tga_inbox_messages_tenant_approval",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_tga_inbox_messages_tenant_patient",
            ondelete="RESTRICT",
        ),
        # The queue: oldest first, per state.
        sa.Index(
            "ix_tga_inbox_messages_tenant_state_received",
            "tenant_id",
            "processing_state",
            "received_at",
        ),
    )

    id: uuid.UUID = _id()
    tenant_id: uuid.UUID = _tenant()
    provider_message_id: str = Field(max_length=255)
    from_address: str = Field(max_length=320)
    to_address: str = Field(max_length=320)
    # HIGHLY_SENSITIVE: ciphertext (see the module docstring), never logged.
    subject: bytes | None = None
    received_at: datetime = Field(sa_type=_TIMESTAMPTZ)
    spf_result: str | None = Field(default=None, max_length=16)
    dkim_result: str | None = Field(default=None, max_length=16)
    dmarc_result: str | None = Field(default=None, max_length=16)
    processing_state: str = Field(default="RECEIVED", max_length=16)
    state_reason: str | None = Field(default=None, max_length=64)
    claimed_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="RESTRICT"
    )
    claimed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    lease_expires_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    decided_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="RESTRICT"
    )
    decided_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    decision_reason: str | None = Field(default=None, max_length=64)
    patient_id: uuid.UUID | None = None
    approval_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class TgaInboxAttachment(SQLModel, table=True):
    """One file attached to an inbox message. Append-only."""

    __tablename__ = "tga_inbox_attachments"
    __table_args__ = (
        # The 25 MB cap (R3). A file over it is still recorded, as refused, so nothing is dropped
        # silently (R19); it is never stored.
        sa.CheckConstraint(
            f"size_bytes >= 0 AND (size_bytes <= {MAX_ATTACHMENT_BYTES}"
            " OR refusal_reason IN ('TOO_LARGE', 'TOO_MANY_ATTACHMENTS'))",
            name="size_bytes",
        ),
        sa.CheckConstraint(
            f"scan_state IN ({_sql_list(SCAN_STATES)})", name="scan_state"
        ),
        sa.CheckConstraint(
            f"text_state IN ({_sql_list(TEXT_STATES)})", name="text_state"
        ),
        sa.CheckConstraint(
            f"refusal_reason IS NULL OR refusal_reason ~ '{CODE_PATTERN}'",
            name="refusal_reason",
        ),
        sa.CheckConstraint("octet_length(sha256) = 32", name="sha256"),
        # Only a clean file is ever stored where the clinic can reach it (R5).
        sa.CheckConstraint(
            "object_key IS NULL OR scan_state = 'CLEAN'", name="stored_clean"
        ),
        # A file is either refused (with a reason) or stored, never neither.
        sa.CheckConstraint(
            "(refusal_reason IS NULL) = (object_key IS NOT NULL)",
            name="refused_or_stored",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tga_inbox_attachments_tenant_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["tga_inbox_messages.tenant_id", "tga_inbox_messages.id"],
            name="fk_tga_inbox_attachments_tenant_message",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_tga_inbox_attachments_tenant_message", "tenant_id", "message_id"),
        sa.Index("ix_tga_inbox_attachments_tenant_sha256", "tenant_id", "sha256"),
    )

    id: uuid.UUID = _id()
    tenant_id: uuid.UUID = _tenant()
    message_id: uuid.UUID = Field(nullable=False)
    # Server-generated; the filename is never part of it.
    object_key: str | None = Field(default=None, max_length=255)
    # HIGHLY_SENSITIVE as sent; sanitised before it is stored, shown for display only.
    original_filename: str = Field(max_length=255)
    declared_content_type: str = Field(max_length=127)
    # From the magic bytes, never from the header.
    content_type: str | None = Field(default=None, max_length=127)
    size_bytes: int = Field(sa_type=sa.BigInteger)
    sha256: bytes
    scan_state: str = Field(default="PENDING", max_length=16)
    text_state: str = Field(default="NOT_ATTEMPTED", max_length=16)
    page_count: int | None = None
    refusal_reason: str | None = Field(default=None, max_length=64)
    scanned_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class TgaExtractionResult(SQLModel, table=True):
    """One field read from one attachment by one extractor version."""

    __tablename__ = "tga_extraction_results"
    __table_args__ = (
        sa.CheckConstraint(
            f"field_name IN ({_sql_list(FIELD_NAMES)})", name="field_name"
        ),
        sa.CheckConstraint(
            f"method IS NULL OR method IN ({_sql_list(EXTRACTION_METHODS)})",
            name="method",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence",
        ),
        # `NOT_FOUND` is an empty value with no confidence and no method: never a guess (R8).
        sa.CheckConstraint(
            "(raw_value IS NULL) = (confidence IS NULL)"
            " AND (raw_value IS NULL) = (method IS NULL)",
            name="found",
        ),
        sa.CheckConstraint(
            "(accepted_by IS NULL) = (accepted_at IS NULL)", name="accepted"
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tga_extraction_results_tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "attachment_id",
            "field_name",
            "extractor_version",
            name="uq_tga_extraction_results_field_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "attachment_id"],
            ["tga_inbox_attachments.tenant_id", "tga_inbox_attachments.id"],
            name="fk_tga_extraction_results_tenant_attachment",
            ondelete="RESTRICT",
        ),
    )

    id: uuid.UUID = _id()
    tenant_id: uuid.UUID = _tenant()
    attachment_id: uuid.UUID = Field(nullable=False)
    extractor_version: str = Field(max_length=32)
    field_name: str = Field(max_length=32)
    # HIGHLY_SENSITIVE ciphertext. Immutable once written: the app role cannot update it.
    raw_value: bytes | None = None
    confidence: Decimal | None = Field(
        default=None,
        sa_type=sa.Numeric(4, 3),
    )
    method: str | None = Field(default=None, max_length=32)
    page_number: int | None = None
    region: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    # HIGHLY_SENSITIVE ciphertext: what the reviewer accepted, which may be a correction.
    accepted_value: bytes | None = None
    accepted_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="RESTRICT"
    )
    accepted_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
