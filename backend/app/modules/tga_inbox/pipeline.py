"""Ingestion: a received email becomes inbox rows, in the design's stage order (FEAT-09 R1).

```
mailbox identity -> tenant | dedupe | sender authentication | attachment bounds | type agreement
  -> malware scan -> private storage (hash) -> text layer -> field extraction -> one transaction
```

The stages that call a vendor (scan, store, text) run **before** the database transaction opens, so no
transaction is held open across a vendor call. Everything the stages decided is then written in one
tenant transaction with its audit events (INV-4). A stored object whose transaction then fails is
harmless: keys are content-addressed, so a retry writes the same object again.

The stand-in pipeline runs synchronously inside the ingest request, which comfortably meets the
2-minute target (R22). When a real worker exists (D-011, "Consequences"), the request will record
`RECEIVED` and the worker will run the same `_process_attachment` stages; the function boundaries are
already the stage boundaries.

What never happens here: no approval is written, no patient is chosen, nothing is dispatched (R14,
R21). The pipeline only prepares a queue item for a person.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import text
from sqlmodel import Session, select

from app.core import field_crypto
from app.core.config import settings
from app.core.db import engine, tenant_transaction
from app.modules.audit import service as audit
from app.modules.identity_tenancy import service as tenancy
from app.modules.tga_inbox import adapters, extraction, pdf_text
from app.modules.tga_inbox.models import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    TgaExtractionResult,
    TgaInboxAttachment,
    TgaInboxMessage,
)

INGEST: Final[str] = "tga_document.ingest"

# FEAT-09 R14: the pipeline writes as `clinos_extractor`, which holds `SELECT, INSERT` on the three
# inbox tables and the audit log and **nothing** on `tga_approvals` or `patients` (migration
# `9c4e2b7d1a05`). `SET LOCAL` ends with the transaction, so the pooled connection is back to its own
# role at commit or rollback, and no other request inherits it.
EXTRACTOR_ROLE: Final[str] = "clinos_extractor"
_AS_EXTRACTOR: Final = text(f"SET LOCAL ROLE {EXTRACTOR_ROLE}")


def as_extractor(session: Session) -> None:
    """Run the rest of this transaction with the extractor's privileges only.

    The database, not this code, then refuses any write outside ingestion: an approval, a patient, a
    review decision. It holds even when the application connects as a superuser (local runs, CI),
    because a superuser that sets a role takes that role's privileges.
    """
    session.execute(_AS_EXTRACTOR)


EXTRACT: Final[str] = "tga_document.extract"

ALLOWED_CONTENT_TYPES: Final[frozenset[str]] = frozenset({"application/pdf"})
ALLOWED_EXTENSIONS: Final[frozenset[str]] = frozenset({"pdf"})
# Extensions that make a "double extension" dangerous when they appear before the last one.
_KNOWN_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "pdf", "exe", "scr", "com", "bat", "cmd", "js", "vbs", "ps1", "jar", "msi", "dll",
        "html", "htm", "svg", "zip", "rar", "7z", "doc", "docx", "docm", "xls", "xlsm", "lnk",
    }
)  # fmt: skip
_LOCAL_PART: Final = re.compile(
    r"^tga\+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def subject_kind() -> str:
    return "tga_inbox.subject"


def value_kind(field_name: str) -> str:
    """The encryption binding of one extracted field: a value cannot be moved to another field."""
    return f"tga_inbox.{field_name.lower()}"


def inbox_address(tenant_id: uuid.UUID) -> str:
    """The address a clinic gives the TGA. The tenant is in it, so it is the mailbox identity."""
    return f"tga+{tenant_id}@{settings.TGA_INBOX_DOMAIN}"


def tenant_for_address(address: str) -> uuid.UUID | None:
    local, _, domain = address.strip().lower().rpartition("@")
    if domain != settings.TGA_INBOX_DOMAIN.lower():
        return None
    match = _LOCAL_PART.match(local)
    return uuid.UUID(match.group(1)) if match else None


class UnknownMailbox(Exception):
    """The message was addressed to no active clinic inbox. Nothing is recorded: there is no tenant
    to record it under, and a platform-level quarantine is FEAT-13's open item."""


@dataclass(frozen=True)
class InboundAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class InboundMessage:
    provider_message_id: str
    from_address: str
    to_address: str
    subject: str
    received_at: datetime
    spf_result: str | None
    dkim_result: str | None
    dmarc_result: str | None
    attachments: list[InboundAttachment] = field(default_factory=list)


@dataclass(frozen=True)
class IngestOutcome:
    message_id: uuid.UUID
    processing_state: str
    duplicate: bool


@dataclass
class _Processed:
    """What the stages decided about one attachment, before anything is written."""

    filename: str
    declared_content_type: str
    content_type: str | None
    size_bytes: int
    sha256: bytes
    scan_state: str = "NOT_SCANNED"
    text_state: str = "NOT_ATTEMPTED"
    page_count: int | None = None
    refusal_reason: str | None = None
    object_key: str | None = None
    scanned_at: datetime | None = None
    candidates: list[extraction.Candidate] = field(default_factory=list)


def sanitise_filename(name: str) -> str:
    """For display only: no path, no control characters, bounded. Never used as a key or a path."""
    base = re.split(r"[\\/]", name)[-1]
    cleaned = (
        re.sub(r"[^\w .()-]", "_", base, flags=re.ASCII).strip(" .") or "attachment"
    )
    return cleaned[:255]


def _extension_refusal(name: str) -> str | None:
    parts = name.lower().split(".")
    if len(parts) < 2 or parts[-1] not in ALLOWED_EXTENSIONS:
        return "TYPE_NOT_ALLOWED"
    if any(part in _KNOWN_EXTENSIONS for part in parts[1:-1]):
        return "DOUBLE_EXTENSION"
    return None


def sender_is_trusted(message: InboundMessage) -> bool:
    """R2: an allow-listed sender domain **and** authentication that passed. DMARC `PASS` is enough;
    otherwise both SPF and DKIM must pass. An empty allow-list trusts nobody (fail closed)."""
    domain = message.from_address.rpartition("@")[2].lower()
    allowed = settings.TGA_INBOX_ALLOWED_SENDER_DOMAINS
    if not any(domain == item or domain.endswith(f".{item}") for item in allowed):
        return False
    if message.dmarc_result == "PASS":
        return True
    return message.spf_result == "PASS" and message.dkim_result == "PASS"


def _process_attachment(
    attachment: InboundAttachment,
    *,
    tenant_id: uuid.UUID,
    store: adapters.ObjectStore,
    scanner: adapters.MalwareScanner,
) -> _Processed:
    data = attachment.data
    item = _Processed(
        filename=sanitise_filename(attachment.filename),
        declared_content_type=attachment.content_type.split(";")[0]
        .strip()
        .lower()[:127],
        content_type="application/pdf" if data.startswith(b"%PDF-") else None,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).digest(),
    )
    # Stage 2 and 4: bounds and the type allow-list, before any byte is parsed or stored.
    if item.size_bytes > MAX_ATTACHMENT_BYTES:
        item.refusal_reason = "TOO_LARGE"
        return item
    if item.size_bytes == 0:
        item.refusal_reason = "EMPTY_FILE"
        return item
    extension_refusal = _extension_refusal(item.filename)
    if extension_refusal is not None:
        item.refusal_reason = extension_refusal
        return item
    # Stage 3: the declared type, the extension and the magic bytes must agree; never parsed if not.
    if (
        item.declared_content_type not in ALLOWED_CONTENT_TYPES
        or item.content_type not in ALLOWED_CONTENT_TYPES
    ):
        item.refusal_reason = "TYPE_MISMATCH"
        return item
    # Stage 5: the scan, before the file is reachable from anything.
    verdict = scanner.scan(data)
    item.scan_state = verdict
    item.scanned_at = datetime.now(UTC)
    if verdict == "INFECTED":
        item.refusal_reason = "MALWARE_DETECTED"
        return item
    if verdict != "CLEAN":
        item.refusal_reason = "SCAN_ERROR"
        return item
    # Stage 6: private storage under a server-generated, content-addressed key.
    item.object_key = adapters.object_key(tenant_id=tenant_id, sha256=item.sha256)
    store.put(item.object_key, data)
    # Stage 7: the text layer first; OCR only where there is none, and there is no OCR yet.
    text = pdf_text.read(data)
    item.text_state = text.state
    item.page_count = len(text.pages) or None
    pages = text.pages
    if text.state == "NO_TEXT":
        ocr = adapters.configured_ocr()
        ocr_pages = ocr.pages(data) if ocr is not None else None
        if ocr_pages:
            pages, item.text_state = ocr_pages, "EXTRACTED"
    # Stage 8: fields, only from a readable text layer.
    if item.text_state == "EXTRACTED":
        item.candidates = extraction.extract(pages)
    return item


def _message_outcome(
    items: list[_Processed], *, trusted: bool
) -> tuple[str, str | None]:
    if not trusted:
        return "FAILED", "UNTRUSTED_SENDER"
    if not items:
        return "FAILED", "NO_ATTACHMENT"
    stored = [item for item in items if item.object_key is not None]
    if not stored:
        return "FAILED", "NO_USABLE_ATTACHMENT"
    if any(item.candidates for item in stored):
        return "EXTRACTED", None
    if any(item.text_state == "ENCRYPTED" for item in stored):
        return "FAILED", "ENCRYPTED"
    return "FAILED", "NEEDS_MANUAL_READ"


def _audit(
    session: Session,
    *,
    action: str,
    resource_id: uuid.UUID | None,
    result: str = "SUCCESS",
    reason: str | None = None,
) -> None:
    audit.record(
        session,
        audit.AuditEvent(
            action=action, result=result, resource_id=resource_id, reason=reason
        ),
    )


def ingest(
    message: InboundMessage,
    *,
    store: adapters.ObjectStore | None = None,
    scanner: adapters.MalwareScanner | None = None,
) -> IngestOutcome:
    """Run the pipeline for one received message. Idempotent on `provider_message_id` (R18)."""
    tenant_id = tenant_for_address(message.to_address)
    if tenant_id is None:
        raise UnknownMailbox
    with Session(engine) as session:
        if not tenancy.tenant_is_active(session, tenant_id=tenant_id):
            raise UnknownMailbox

    with tenant_transaction(tenant_id=tenant_id) as session:
        as_extractor(session)
        existing = session.exec(
            select(TgaInboxMessage).where(
                TgaInboxMessage.tenant_id == tenant_id,
                TgaInboxMessage.provider_message_id == message.provider_message_id,
            )
        ).first()
        if existing is not None:
            _audit(
                session,
                action=INGEST,
                resource_id=existing.id,
                reason="DUPLICATE_MESSAGE",
            )
            return IngestOutcome(existing.id, existing.processing_state, duplicate=True)

    trusted = sender_is_trusted(message)
    items: list[_Processed] = []
    if trusted:
        resolved_store = store or adapters.configured_store()
        resolved_scanner = scanner or adapters.configured_scanner()
        for index, attachment in enumerate(message.attachments):
            if index >= MAX_ATTACHMENTS:
                items.append(
                    _Processed(
                        filename=sanitise_filename(attachment.filename),
                        declared_content_type=attachment.content_type[:127],
                        content_type=None,
                        size_bytes=len(attachment.data),
                        sha256=hashlib.sha256(attachment.data).digest(),
                        refusal_reason="TOO_MANY_ATTACHMENTS",
                    )
                )
                continue
            items.append(
                _process_attachment(
                    attachment,
                    tenant_id=tenant_id,
                    store=resolved_store,
                    scanner=resolved_scanner,
                )
            )
    state, reason = _message_outcome(items, trusted=trusted)

    with tenant_transaction(tenant_id=tenant_id) as session:
        as_extractor(session)
        row = TgaInboxMessage(
            tenant_id=tenant_id,
            provider_message_id=message.provider_message_id,
            from_address=message.from_address.lower(),
            to_address=message.to_address.lower(),
            subject=field_crypto.encrypt(
                message.subject, tenant_id=tenant_id, kind=subject_kind()
            )
            if message.subject
            else None,
            received_at=message.received_at,
            spf_result=message.spf_result,
            dkim_result=message.dkim_result,
            dmarc_result=message.dmarc_result,
            processing_state=state,
            state_reason=reason,
        )
        session.add(row)
        session.flush()
        _audit(
            session,
            action=INGEST,
            resource_id=row.id,
            result="SUCCESS" if trusted else "DENIED",
            reason=reason if state == "FAILED" else None,
        )
        for item in items:
            attachment_row = TgaInboxAttachment(
                tenant_id=tenant_id,
                message_id=row.id,
                object_key=item.object_key,
                original_filename=item.filename,
                declared_content_type=item.declared_content_type,
                content_type=item.content_type,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                scan_state=item.scan_state,
                text_state=item.text_state,
                page_count=item.page_count,
                refusal_reason=item.refusal_reason,
                scanned_at=item.scanned_at,
            )
            session.add(attachment_row)
            session.flush()
            if item.refusal_reason is not None:
                _audit(
                    session,
                    action=INGEST,
                    resource_id=attachment_row.id,
                    result="DENIED",
                    reason=item.refusal_reason,
                )
                continue
            for candidate in item.candidates:
                session.add(
                    TgaExtractionResult(
                        tenant_id=tenant_id,
                        attachment_id=attachment_row.id,
                        extractor_version=extraction.EXTRACTOR_VERSION,
                        field_name=candidate.field_name,
                        raw_value=None
                        if candidate.value is None
                        else field_crypto.encrypt(
                            candidate.value,
                            tenant_id=tenant_id,
                            kind=value_kind(candidate.field_name),
                        ),
                        confidence=candidate.confidence,
                        method=candidate.method,
                        page_number=candidate.page_number,
                    )
                )
            _audit(
                session,
                action=EXTRACT,
                resource_id=attachment_row.id,
                result="SUCCESS" if item.candidates else "FAILED",
                reason=None if item.candidates else item.text_state,
            )
        session.flush()
        return IngestOutcome(row.id, state, duplicate=False)
