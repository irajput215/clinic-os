"""Clinical-records service facade — the only place the clinical tables are queried.

Design: `docs/features/06-clinical-records/03-design.md` §"Deny-by-default request path",
§"Immutability mechanism at two layers", §"Failure behaviour". Requirements: R1-R17.

Rules this module holds to:

- **Every query runs inside `app.core.db.tenant_transaction(...)`**, which sets `app.tenant_id` with
  `SET LOCAL` for the life of the transaction and refuses to open without a tenant. Every query also
  carries an explicit `tenant_id` predicate as a second line of defence behind the forced row-level
  security policy (INV-1; the deployment credential is still the table owner, recorded in
  `docs/progress.md` §4).
- **No statement updates or deletes a version row.** `create_record` inserts version 1;
  `append_version` inserts version `current_version + 1` with `supersedes_version` pointing at the
  version it replaces. There is no `UPDATE clinical_record_versions` and no `DELETE` anywhere in this
  module, which is what the database's revoked grant and immutability trigger exist to enforce even
  if somebody later writes one (R5, R12, R13).
- **Audit is written on the caller's transaction (INV-4).** `audit.record(...)` runs before the block
  commits, so a clinical write that cannot be audited does not happen: a refusal inside `record`
  propagates out of the `with` block and rolls the clinical row back with the audit row (A3).
- **Refusals are audited with the same fidelity as successes.** A denial that has a tenant context —
  a missing permission, a record the caller cannot resolve, a signature attempt by somebody who did
  not author the version — writes a `DENIED` event with a controlled reason code. Nothing in that
  payload is clinical text: the keys are the record, patient and version identifiers, a count and a
  code.
- **The narrative never leaves this process except through a declared response model.** This module
  imports no logger, so there is no line to leak it into (INV-5, R15). Error envelopes are built by
  `app.core.errors`, which drops the `input` member of a validation error precisely because it can
  carry a whole clinical body.
- **Nothing returns a raw ORM entity.** Rows are converted to declared schemas *inside* the
  transaction, before the session closes and expires its attributes.

## The treating-relationship rule (R11) — deferred, and why

Reads and writes require an active care relationship in the design
(`03-design.md` §"Treating-relationship check"; `01-requirements.md` R11). The rule reads the
`care_relationships` table through a module that **does not exist on this branch**: it is marked
`OPEN — blocked` in the feature's own documents (`01-requirements.md` OPEN-3, `07-definition-of-done.md`
open items), and `app/modules/users_roles/policy.py` records the same deferral for `can()`'s resource
rules. This module therefore calls the central policy layer with the tenant-scoped `ResourceRef` that
exists, and the relationship rule is reported as the remaining gap in the PR rather than half-applied
by reaching into another module's tables. The deferral is not a fail-open: `can()` allows only after
an explicit permission check, so a resource rule can only ever *remove* access.
"""

import base64
import binascii
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.core.db import tenant_transaction

# The audit module is reached through its service facade (`docs/reference/build-contract.md` §7).
# The import is one-way — `audit` knows nothing about `clinical_records` — so there is no cycle.
from app.modules.audit import service as audit
from app.modules.clinical_records.models import (
    ClinicalRecord,
    ClinicalRecordVersion,
)
from app.modules.clinical_records.schemas import (
    ClinicalRecordAppend,
    ClinicalRecordCreate,
    ClinicalRecordDetail,
    ClinicalRecordRead,
    ClinicalRecordsPublic,
    ClinicalRecordSummary,
    ClinicalRecordVersionRead,
    SoapNote,
)
from app.modules.users_roles.policy import DecisionCode

# The two actions this module emits. Both are already in the closed catalogue of
# `docs/features/04-audit-log/05-data-and-audit.md` §"The action catalogue (doc 07 §1)" — the doc 07
# label *families* (`CLINICAL_RECORD_VIEWED`, `CLINICAL_NOTE_CREATED`, `CLINICAL_NOTE_SIGNED`,
# `CLINICAL_NOTE_AMENDED`) are the story labels of `05-data-and-audit.md`, which maps them onto these
# two action names itself. The catalogue is closed — *"No new action name may be invented"* — so the
# module emits the mapped names and distinguishes the four events by payload. No seed migration is
# needed: `clinical_record:read` and `clinical_record:write` are already in the permission catalogue
# and seeded by `4d092676eafa`.
RECORD_READ_ACTION: Final[str] = "clinical_record.read"
RECORD_WRITE_ACTION: Final[str] = "clinical_record.write"

# The permission codes the routes require. They are seeded already (`4d092676eafa`); naming them here
# keeps the route declaration, the policy call and the tests from drifting apart.
CLINICAL_RECORD_READ_PERMISSION: Final[str] = "clinical_record:read"
CLINICAL_RECORD_WRITE_PERMISSION: Final[str] = "clinical_record:write"

# Controlled reason codes. `05-data-and-audit.md` names the three authorisation codes; the two
# clinical-state codes and the signature code are named here because the source names the statuses
# (`NOTE_ALREADY_SIGNED`, R7) without giving them a machine-readable code. They are reported as
# repo-named values in the PR, not silently invented.
AUTHZ_DENIED: Final[str] = "AUTHZ_DENIED"
AUTHZ_DENIED_CROSS_TENANT: Final[str] = "AUTHZ_DENIED_CROSS_TENANT"
AUTHZ_CARE_RELATIONSHIP_DENIED: Final[str] = "AUTHZ_CARE_RELATIONSHIP_DENIED"
NOTE_ALREADY_SIGNED: Final[str] = "NOTE_ALREADY_SIGNED"
AMENDMENT_REASON_REQUIRED: Final[str] = "AMENDMENT_REASON_REQUIRED"
SIGN_NOT_VERSION_AUTHOR: Final[str] = "SIGN_NOT_VERSION_AUTHOR"
VERSION_CONFLICT: Final[str] = "VERSION_CONFLICT"

# The controlled code an amendment event carries in its envelope `reason`. The clinician's typed
# amendment reason is HEALTH_INFORMATION free text and never reaches the audit trail
# (`05-data-and-audit.md` §"The rule for audit metadata"); this constant is what stands in for it,
# and the source gives no vocabulary to pick from — reported as a repo-named code.
AMENDMENT_REASON_CODE: Final[str] = "AMENDMENT"

# The policy layer's denial classes, mapped onto the reason codes doc 05 names. `NO_IDENTITY` cannot
# occur here — the boundary refuses an unauthenticated request before this module runs — but it is
# mapped rather than left to a `KeyError`.
_DENIAL_REASON_CODES: Final[dict[DecisionCode, str]] = {
    DecisionCode.NO_IDENTITY: AUTHZ_DENIED,
    DecisionCode.IDENTITY_NOT_ACTIVE: AUTHZ_DENIED,
    DecisionCode.PERMISSION_NOT_HELD: AUTHZ_DENIED,
    DecisionCode.CROSS_TENANT: AUTHZ_DENIED_CROSS_TENANT,
}

# The SOAP rendering order and headings. The design fixes the four section names and their order;
# the serialisation itself is this module's (R3).
_SOAP_SECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("subjective", "Subjective"),
    ("objective", "Objective"),
    ("assessment", "Assessment"),
    ("plan", "Plan"),
)

# How many times an append retries after a unique-constraint collision before answering `409`. The
# design fixes exactly one retry ("retry once with the next version, then `409 VERSION_CONFLICT`").
_APPEND_ATTEMPTS: Final[int] = 2


class InvalidCursor(ValueError):
    """The `cursor` parameter is malformed or does not verify. The router answers `422`."""


class VersionConflict(RuntimeError):
    """Two appends raced and the retry also collided. The router answers `409 VERSION_CONFLICT`."""


@dataclass(frozen=True)
class AuditContext:
    """The request-scoped identifiers an audit event carries.

    Built once by the router from the verified actor, so the service cannot describe an event as
    coming from somebody else: the actor id and role are the ones the session resolved.
    """

    actor_id: uuid.UUID
    actor_role: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    source_ip: str | None = None


@dataclass(frozen=True)
class ReadOutcome:
    """A read's verdict: the found value, or `NOT_FOUND` (absent, or another tenant's)."""

    status: str
    record: ClinicalRecordDetail | None = None
    version: ClinicalRecordVersionRead | None = None


@dataclass(frozen=True)
class TimelineOutcome:
    """A timeline page, or `NOT_FOUND` for a patient the caller cannot resolve."""

    status: str
    page: ClinicalRecordsPublic | None = None


@dataclass(frozen=True)
class AppendOutcome:
    """An append's verdict. Every status except `OK` has already been audited as a denial."""

    status: str
    record: ClinicalRecordDetail | None = None


@dataclass(frozen=True)
class SignOutcome:
    """A signature's verdict. Every status except `OK` has already been audited as a denial."""

    status: str
    record: ClinicalRecordDetail | None = None


STATUS_OK: Final[str] = "OK"
STATUS_NOT_FOUND: Final[str] = "NOT_FOUND"
STATUS_ALREADY_SIGNED: Final[str] = "ALREADY_SIGNED"
STATUS_REASON_REQUIRED: Final[str] = "REASON_REQUIRED"
STATUS_NOT_AUTHOR: Final[str] = "NOT_AUTHOR"


def denial_reason_code(code: DecisionCode) -> str:
    """Map a policy denial onto the reason code the audit catalogue names."""
    return _DENIAL_REASON_CODES.get(code, AUTHZ_DENIED)


def _narrative(
    record_in: ClinicalRecordCreate | ClinicalRecordAppend,
) -> tuple[str, str]:
    """The `(body, body_format)` pair to store for this request.

    A `soap` surface is rendered into the single narrative column (R3); an explicit `body` is stored
    as sent. The schema validator has already refused a request that carried both or neither, so the
    `ValueError` below is unreachable from HTTP — it exists so the invariant is stated in code rather
    than assumed.
    """
    if record_in.soap is not None:
        return _render_soap(record_in.soap), "MARKDOWN"
    if record_in.body is None:  # pragma: no cover - the schema refuses this shape
        raise ValueError("a narrative is required")
    return record_in.body, record_in.body_format or "PLAIN"


def _render_soap(soap: SoapNote) -> str:
    """Render the SOAP authoring surface into one Markdown narrative.

    Only the sections the clinician supplied are rendered: inventing an empty heading for a section
    that was not recorded would put words in the record that nobody wrote. The `##` headings and the
    section order are stable, so the same input always serialises to the same bytes.
    """
    parts: list[str] = []
    for field_name, heading in _SOAP_SECTIONS:
        value = getattr(soap, field_name)
        if value is not None:
            parts.append(f"## {heading}\n\n{value}")
    return "\n\n".join(parts)


def _audit(
    session: Session,
    *,
    action: str,
    result: str,
    resource_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    """Write one event on the caller's transaction, through the merged Feature 04 writer.

    `metadata` is allow-listed by key in `app.modules.audit.actions`, so a key that is not registered
    for the action raises `AuditWriteRefused` and the caller's transaction rolls back — the failure
    mode INV-4 requires. Identifiers are stringified because the payload column is JSON.
    """
    audit.record(
        session,
        audit.AuditEvent(
            action=action,
            result=result,
            resource_id=resource_id,
            reason=reason,
            payload=payload,
        ),
    )


def _live_record(
    session: Session, *, tenant_id: uuid.UUID, record_id: uuid.UUID
) -> ClinicalRecord | None:
    """One live record for this tenant, or `None` for absent **and** for another tenant's.

    `None` is the only not-found answer: the caller cannot tell the two apart, so the router answers
    `404` for both and existence is never disclosed across a tenant boundary (R10).
    """
    statement = select(ClinicalRecord).where(
        ClinicalRecord.id == record_id,
        ClinicalRecord.tenant_id == tenant_id,
        col(ClinicalRecord.deleted_at).is_(None),
    )
    return session.exec(statement).first()


def _version_row(
    session: Session, *, tenant_id: uuid.UUID, record_id: uuid.UUID, version: int
) -> ClinicalRecordVersion | None:
    """One version of this tenant's record, or `None`."""
    statement = select(ClinicalRecordVersion).where(
        ClinicalRecordVersion.tenant_id == tenant_id,
        ClinicalRecordVersion.clinical_record_id == record_id,
        ClinicalRecordVersion.version == version,
    )
    return session.exec(statement).first()


def _version_rows(
    session: Session, *, tenant_id: uuid.UUID, record_id: uuid.UUID
) -> list[ClinicalRecordVersion]:
    """Every version of one record, `ORDER BY version ASC` (R9).

    The unique constraint `(tenant_id, clinical_record_id, version)` makes this order total, so no
    tie-breaker is needed and no page of the history can repeat or skip a version.
    """
    statement = (
        select(ClinicalRecordVersion)
        .where(
            ClinicalRecordVersion.tenant_id == tenant_id,
            ClinicalRecordVersion.clinical_record_id == record_id,
        )
        .order_by(col(ClinicalRecordVersion.version))
    )
    return list(session.exec(statement).all())


def _version_read(row: ClinicalRecordVersion) -> ClinicalRecordVersionRead:
    """Serialise one version through the declared response model.

    Built by hand rather than by `model_validate` because the API field name for the `reason` column
    is `amendment_reason` (`03-design.md`, schema table) and an alias would make the mapping implicit.
    """
    return ClinicalRecordVersionRead(
        id=row.id,
        clinical_record_id=row.clinical_record_id,
        version=row.version,
        body=row.body,
        body_format=row.body_format,
        author_id=row.author_id,
        signed_at=row.signed_at,
        supersedes_version=row.supersedes_version,
        amendment_reason=row.reason,
        created_at=row.created_at,
    )


def _record_read(row: ClinicalRecord) -> ClinicalRecordRead:
    return ClinicalRecordRead.model_validate(row)


def _detail(session: Session, record: ClinicalRecord) -> ClinicalRecordDetail:
    """The record plus its versions, ascending, serialised inside the transaction."""
    base = _record_read(record)
    versions = _version_rows(session, tenant_id=record.tenant_id, record_id=record.id)
    return ClinicalRecordDetail(
        id=base.id,
        patient_id=base.patient_id,
        record_type=base.record_type,
        author_id=base.author_id,
        current_version=base.current_version,
        signed_at=base.signed_at,
        deleted_at=base.deleted_at,
        created_at=base.created_at,
        versions=[_version_read(row) for row in versions],
    )


def _summary(
    record: ClinicalRecord, current: ClinicalRecordVersion
) -> ClinicalRecordSummary:
    base = _record_read(record)
    return ClinicalRecordSummary(
        id=base.id,
        patient_id=base.patient_id,
        record_type=base.record_type,
        author_id=base.author_id,
        current_version=base.current_version,
        signed_at=base.signed_at,
        deleted_at=base.deleted_at,
        created_at=base.created_at,
        latest_version=_version_read(current),
    )


def record_denial(
    *,
    tenant_id: uuid.UUID,
    context: AuditContext,
    action: str,
    reason: str,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
) -> None:
    """Audit a refusal that the router decided before any clinical row was touched.

    A denied request is evidence, not noise: `05-data-and-audit.md` requires refusals to be recorded
    with the same fidelity as successes, and the *only* member of the payload is an identifier. The
    event is written on its own short transaction because there is no clinical change to share one
    with — a permission denial happens before any resource is loaded.
    """
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        source_ip=context.source_ip,
    ) as session:
        payload = None if patient_id is None else {"patient_id": str(patient_id)}
        _audit(
            session,
            action=action,
            result="DENIED",
            resource_id=resource_id,
            payload=payload,
            reason=reason,
        )


def create_record(
    *,
    tenant_id: uuid.UUID,
    context: AuditContext,
    record_in: ClinicalRecordCreate,
) -> ClinicalRecordDetail:
    """Create a record and its version 1, unsigned, and audit the create on the same transaction.

    The tenant and the author are bound from the arguments — the router resolved both from the
    session — never from the request body, so a caller cannot place a record in another tenant or
    attribute one to somebody else even if a future schema error let such a field through (R1, R2).
    The RLS `WITH CHECK` clause refuses a foreign-tenant insert independently.
    """
    body, body_format = _narrative(record_in)
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        source_ip=context.source_ip,
    ) as session:
        record = ClinicalRecord(
            tenant_id=tenant_id,
            patient_id=record_in.patient_id,
            record_type=record_in.record_type,
            author_id=context.actor_id,
            current_version=1,
        )
        session.add(record)
        session.flush()
        version = ClinicalRecordVersion(
            tenant_id=tenant_id,
            clinical_record_id=record.id,
            version=1,
            body=body,
            body_format=body_format,
            author_id=context.actor_id,
            supersedes_version=None,
            reason=None,
        )
        session.add(version)
        session.flush()
        _audit(
            session,
            action=RECORD_WRITE_ACTION,
            result="SUCCESS",
            resource_id=record.id,
            # The event records *that* a record was created: the patient identifier and the version
            # number. Never the narrative, and never `record_type` — `05-data-and-audit.md` classifies
            # that field "action only" in audit, because it becomes clinical context once joined to a
            # person.
            payload={"patient_id": str(record.patient_id), "version": 1},
        )
        session.refresh(record)
        return _detail(session, record)


def get_record(
    *, tenant_id: uuid.UUID, context: AuditContext, record_id: uuid.UUID
) -> ReadOutcome:
    """Read one record and its versions, ascending, auditing the access (US-4, US-5).

    One `clinical_record.read` event per record access — not one per version — as US-4 fixes it.
    """
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        source_ip=context.source_ip,
    ) as session:
        record = _live_record(session, tenant_id=tenant_id, record_id=record_id)
        if record is None:
            # Absent and another tenant's are the same answer, and both are audited: a substituted
            # identifier is exactly the attempt the trail exists to hold (S13).
            _audit(
                session,
                action=RECORD_READ_ACTION,
                result="DENIED",
                resource_id=record_id,
                reason=AUTHZ_DENIED_CROSS_TENANT,
            )
            return ReadOutcome(status=STATUS_NOT_FOUND)
        detail = _detail(session, record)
        _audit(
            session,
            action=RECORD_READ_ACTION,
            result="SUCCESS",
            resource_id=record.id,
            payload={
                "patient_id": str(record.patient_id),
                "result_count": len(detail.versions),
            },
        )
        return ReadOutcome(status=STATUS_OK, record=detail)


def get_version(
    *,
    tenant_id: uuid.UUID,
    context: AuditContext,
    record_id: uuid.UUID,
    version: int,
) -> ReadOutcome:
    """Read one version of one record, auditing the access (F14)."""
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        source_ip=context.source_ip,
    ) as session:
        record = _live_record(session, tenant_id=tenant_id, record_id=record_id)
        if record is None:
            _audit(
                session,
                action=RECORD_READ_ACTION,
                result="DENIED",
                resource_id=record_id,
                reason=AUTHZ_DENIED_CROSS_TENANT,
            )
            return ReadOutcome(status=STATUS_NOT_FOUND)
        row = _version_row(
            session, tenant_id=tenant_id, record_id=record_id, version=version
        )
        if row is None:
            _audit(
                session,
                action=RECORD_READ_ACTION,
                result="DENIED",
                resource_id=record.id,
                reason=AUTHZ_DENIED,
                payload={"patient_id": str(record.patient_id)},
            )
            return ReadOutcome(status=STATUS_NOT_FOUND)
        _audit(
            session,
            action=RECORD_READ_ACTION,
            result="SUCCESS",
            resource_id=record.id,
            payload={"patient_id": str(record.patient_id), "result_count": 1},
        )
        return ReadOutcome(status=STATUS_OK, version=_version_read(row))


def list_timeline(
    *,
    tenant_id: uuid.UUID,
    context: AuditContext,
    patient_id: uuid.UUID,
    limit: int,
    cursor: str | None,
) -> TimelineOutcome:
    """One keyset page of a patient's records, newest first, with each record's current version.

    The keyset is `(created_at, id)` — both NOT NULL, so the order is total and a page cannot repeat
    or skip a record even while rows are being appended. `created_at` rather than the design's
    `signed_at`: `03-design.md` records that choice as an open item, and `signed_at` is NULL for every
    unsigned record, so it cannot order a timeline that includes drafts. The page asks for one row
    more than the caller wanted; that extra row is what proves whether a next page exists, without a
    second count query.
    """
    boundary = None if cursor is None else decode_cursor(cursor)
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        source_ip=context.source_ip,
    ) as session:
        scope = (
            ClinicalRecord.tenant_id == tenant_id,
            ClinicalRecord.patient_id == patient_id,
            col(ClinicalRecord.deleted_at).is_(None),
        )
        count = session.exec(
            select(func.count()).select_from(ClinicalRecord).where(*scope)
        ).one()
        statement = (
            select(ClinicalRecord)
            .where(*scope)
            .order_by(
                col(ClinicalRecord.created_at).desc(), col(ClinicalRecord.id).desc()
            )
            .limit(limit + 1)
        )
        if boundary is not None:
            statement = statement.where(_before(boundary))
        rows = list(session.exec(statement).all())

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        # One second query for the current versions of the page, rather than a join per record: the
        # timeline is bounded by `limit`, so this is a single index lookup on the unique constraint.
        current_versions = {
            (row.clinical_record_id, row.version): row
            for row in session.exec(
                select(ClinicalRecordVersion).where(
                    ClinicalRecordVersion.tenant_id == tenant_id,
                    col(ClinicalRecordVersion.clinical_record_id).in_(
                        [record.id for record in page_rows]
                    ),
                )
            ).all()
        }
        _audit(
            session,
            action=RECORD_READ_ACTION,
            result="SUCCESS",
            resource_id=patient_id,
            payload={"patient_id": str(patient_id), "result_count": len(page_rows)},
        )
        page: list[ClinicalRecordSummary] = []
        for record in page_rows:
            current = current_versions.get((record.id, record.current_version))
            if (
                current is None
            ):  # pragma: no cover - the pointer and the row are written together
                continue
            page.append(_summary(record, current))
        return TimelineOutcome(
            status=STATUS_OK,
            page=ClinicalRecordsPublic(
                data=page,
                count=count,
                next_cursor=(
                    encode_cursor(page_rows[-1]) if has_more and page_rows else None
                ),
            ),
        )


def append_version(
    *,
    tenant_id: uuid.UUID,
    context: AuditContext,
    record_id: uuid.UUID,
    append_in: ClinicalRecordAppend,
    amendment: bool,
) -> AppendOutcome:
    """Append a new version to a record — the code path `PATCH` and `POST .../amendments` share.

    `amendment=True` is the `POST .../amendments` route: it is allowed on a signed record, because a
    correction to a signed note is the whole point of an amendment (US-3). `PATCH` is refused once
    the record is signed, with `403 NOTE_ALREADY_SIGNED`, **before** any version is inserted (R5).

    Requirement R7 is enforced here rather than in the schema because it needs the record's current
    version: from version 2 onward an amendment reason is mandatory. The stricter reading that
    `01-requirements.md` OPEN-2 records is the one applied — the reason is required whenever the new
    version number is above 1, not only when superseding a signed version.

    A version is appended, never mutated: the new row names the version it supersedes, and the
    parent's `current_version` moves to it. If two appends race, the unique constraint collides, the
    append retries once against the version the winner committed, and a second collision is
    `409 VERSION_CONFLICT` (R8) — a lost update is impossible because no statement ever rewrites an
    existing version.
    """
    body, body_format = _narrative(append_in)
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        source_ip=context.source_ip,
    ) as session:
        record = _live_record(session, tenant_id=tenant_id, record_id=record_id)
        if record is None:
            _audit(
                session,
                action=RECORD_WRITE_ACTION,
                result="DENIED",
                resource_id=record_id,
                reason=AUTHZ_DENIED_CROSS_TENANT,
            )
            return AppendOutcome(status=STATUS_NOT_FOUND)
        if not amendment and record.signed_at is not None:
            _audit(
                session,
                action=RECORD_WRITE_ACTION,
                result="DENIED",
                resource_id=record.id,
                reason=NOTE_ALREADY_SIGNED,
                payload={"patient_id": str(record.patient_id)},
            )
            return AppendOutcome(status=STATUS_ALREADY_SIGNED)
        if append_in.amendment_reason is None:
            _audit(
                session,
                action=RECORD_WRITE_ACTION,
                result="DENIED",
                resource_id=record.id,
                reason=AMENDMENT_REASON_REQUIRED,
                payload={"patient_id": str(record.patient_id)},
            )
            return AppendOutcome(status=STATUS_REASON_REQUIRED)

        new_version = _insert_version(
            session,
            tenant_id=tenant_id,
            record_id=record_id,
            author_id=context.actor_id,
            body=body,
            body_format=body_format,
            reason=append_in.amendment_reason,
        )
        superseded = new_version - 1
        refreshed = _live_record(session, tenant_id=tenant_id, record_id=record_id)
        assert refreshed is not None  # the row we just appended to
        _audit(
            session,
            action=RECORD_WRITE_ACTION,
            result="SUCCESS",
            resource_id=record_id,
            # The amendment's free-text reason never enters the trail: the envelope carries the
            # controlled code, and the payload carries the two version numbers (doc 05, "The rule for
            # audit metadata").
            reason=AMENDMENT_REASON_CODE if amendment else None,
            payload={
                "patient_id": str(refreshed.patient_id),
                "version": new_version,
                "supersedes_version": superseded,
            },
        )
        return AppendOutcome(status=STATUS_OK, record=_detail(session, refreshed))


def _insert_version(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    record_id: uuid.UUID,
    author_id: uuid.UUID,
    body: str,
    body_format: str,
    reason: str,
) -> int:
    """Insert the next version, retrying once on a unique-constraint collision (R8).

    Each attempt runs inside a savepoint: a collision rolls back only that attempt, so the retry can
    re-read the version the competing writer committed and the caller's transaction survives to
    write its audit event. Without the savepoint the whole transaction would be aborted and the
    retry would have nothing to retry.
    """
    for attempt in range(_APPEND_ATTEMPTS):
        try:
            with session.begin_nested():
                current = session.exec(
                    select(ClinicalRecord).where(
                        ClinicalRecord.id == record_id,
                        ClinicalRecord.tenant_id == tenant_id,
                    )
                ).one()
                new_version = current.current_version + 1
                session.add(
                    ClinicalRecordVersion(
                        tenant_id=tenant_id,
                        clinical_record_id=record_id,
                        version=new_version,
                        body=body,
                        body_format=body_format,
                        author_id=author_id,
                        supersedes_version=current.current_version,
                        reason=reason,
                    )
                )
                # Moves the authoritative pointer. `clinical_records` is the only table this module
                # updates, and only through the columns the migration grants.
                current.current_version = new_version
                session.flush()
                return new_version
        except IntegrityError as error:
            if attempt == _APPEND_ATTEMPTS - 1:
                raise VersionConflict(
                    "another amendment won the version race; retry once more"
                ) from error
    raise AssertionError("unreachable")  # pragma: no cover


def sign_record(
    *, tenant_id: uuid.UUID, context: AuditContext, record_id: uuid.UUID
) -> SignOutcome:
    """Sign the current version of a record, identity-bound to its author (US-2, R4).

    Only the version's own author may sign it: any other actor is refused `403`, audited with
    `SIGN_NOT_VERSION_AUTHOR`. Signing an already-signed record is refused `403
    NOTE_ALREADY_SIGNED`. The signature sets `clinical_records.signed_at` — the column the design's
    privilege block grants for exactly this purpose — and nothing else; no version row is touched.
    """
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        source_ip=context.source_ip,
    ) as session:
        record = _live_record(session, tenant_id=tenant_id, record_id=record_id)
        if record is None:
            _audit(
                session,
                action=RECORD_WRITE_ACTION,
                result="DENIED",
                resource_id=record_id,
                reason=AUTHZ_DENIED_CROSS_TENANT,
            )
            return SignOutcome(status=STATUS_NOT_FOUND)
        if record.signed_at is not None:
            _audit(
                session,
                action=RECORD_WRITE_ACTION,
                result="DENIED",
                resource_id=record.id,
                reason=NOTE_ALREADY_SIGNED,
                payload={"patient_id": str(record.patient_id)},
            )
            return SignOutcome(status=STATUS_ALREADY_SIGNED)
        current = _version_row(
            session,
            tenant_id=tenant_id,
            record_id=record_id,
            version=record.current_version,
        )
        if current is None or current.author_id != context.actor_id:
            _audit(
                session,
                action=RECORD_WRITE_ACTION,
                result="DENIED",
                resource_id=record.id,
                reason=SIGN_NOT_VERSION_AUTHOR,
                payload={"patient_id": str(record.patient_id)},
            )
            return SignOutcome(status=STATUS_NOT_AUTHOR)

        record.signed_at = datetime.now(UTC)
        session.add(record)
        session.flush()
        _audit(
            session,
            action=RECORD_WRITE_ACTION,
            result="SUCCESS",
            resource_id=record.id,
            payload={
                "patient_id": str(record.patient_id),
                "version": record.current_version,
            },
        )
        return SignOutcome(status=STATUS_OK, record=_detail(session, record))


# --- Keyset cursor -----------------------------------------------------------------------------
#
# The cursor is opaque to the client and signed, so a caller cannot forge a boundary that skips or
# replays rows. Signing it with the application secret is the same construction the audit read API
# uses; the payload carries no clinical content, only a timestamp and an identifier.


def _cursor_signature(payload: bytes) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()


def encode_cursor(record: ClinicalRecord) -> str:
    """Encode a page boundary from the last row of the page."""
    payload = json.dumps(
        {
            "created_at": record.created_at.astimezone(UTC).isoformat(),
            "id": str(record.id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    token = _cursor_signature(payload).encode("ascii") + b"." + payload
    return base64.urlsafe_b64encode(token).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode and verify a cursor, or raise `InvalidCursor` (the router answers `422`)."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        signature, separator, payload = raw.partition(b".")
        if not separator or not hmac.compare_digest(
            signature.decode("ascii"), _cursor_signature(payload)
        ):
            raise InvalidCursor("the cursor could not be verified")
        data = json.loads(payload)
        return datetime.fromisoformat(str(data["created_at"])), uuid.UUID(
            str(data["id"])
        )
    except InvalidCursor:
        raise
    except (ValueError, KeyError, UnicodeDecodeError, binascii.Error) as error:
        raise InvalidCursor("the cursor is malformed") from error


def _before(boundary: tuple[datetime, uuid.UUID]) -> ColumnElement[bool]:
    """The keyset predicate: every row strictly after `boundary` in `(created_at DESC, id DESC)`."""
    created_at, record_id = boundary
    return or_(
        col(ClinicalRecord.created_at) < created_at,
        and_(
            col(ClinicalRecord.created_at) == created_at,
            col(ClinicalRecord.id) < record_id,
        ),
    )


# The patient facade is imported for its *existence check* only, and the router calls it: a clinical
# record must reference a patient of the caller's tenant, and the composite foreign key enforces the
# same thing in the database. The import is one-way and stays at the facade (`build-contract.md` §7).
__all__ = [
    "AUTHZ_CARE_RELATIONSHIP_DENIED",
    "AUTHZ_DENIED",
    "AUTHZ_DENIED_CROSS_TENANT",
    "AMENDMENT_REASON_CODE",
    "AMENDMENT_REASON_REQUIRED",
    "CLINICAL_RECORD_READ_PERMISSION",
    "CLINICAL_RECORD_WRITE_PERMISSION",
    "NOTE_ALREADY_SIGNED",
    "RECORD_READ_ACTION",
    "RECORD_WRITE_ACTION",
    "SIGN_NOT_VERSION_AUTHOR",
    "STATUS_ALREADY_SIGNED",
    "STATUS_NOT_AUTHOR",
    "STATUS_NOT_FOUND",
    "STATUS_OK",
    "STATUS_REASON_REQUIRED",
    "VERSION_CONFLICT",
    "AppendOutcome",
    "AuditContext",
    "InvalidCursor",
    "ReadOutcome",
    "SignOutcome",
    "TimelineOutcome",
    "VersionConflict",
    "append_version",
    "create_record",
    "decode_cursor",
    "denial_reason_code",
    "encode_cursor",
    "get_record",
    "get_version",
    "list_timeline",
    "record_denial",
    "sign_record",
]
