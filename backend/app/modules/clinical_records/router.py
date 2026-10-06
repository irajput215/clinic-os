"""The clinical-records HTTP API — the routes `docs/features/06-clinical-records/03-design.md` names.

Order of the request path, exactly as the design fixes it: authenticate the session → resolve the
tenant from the session → check the permission through the central policy layer → resolve the
resource inside the forced-RLS transaction → audit the decision, including refusals, before
responding → validate the body against a strict Pydantic model → execute and write the audit event on
the same transaction.

**The tenant is resolved, never supplied (INV-1).** The actor is built by `app.api.deps.get_actor`
from `current_user.tenant_id` and nothing else; no body, path, query or header can carry a tenant
identifier, and a `tenant_id` in a create body is an unknown field, so it is a `422` before any query
runs.

**Cross-tenant is `404`, never `403`** (R10) — a `403` confirms the record exists. The service
answers `NOT_FOUND` for "absent" and "another tenant's" alike, and the attempt is audited as a
denial.

**There is no `DELETE` route** (R12). A record is never hard-deleted by the application; the database
grant removes the capability as well.

The treating-relationship rule (R11) is the one authorisation step this slice does not implement: the
`care_relationships` module it reads does not exist on this branch, and the feature's own documents
record it as `OPEN — blocked` (`01-requirements.md` OPEN-3). The service docstring records the
deferral; it is reported as a gap in the PR, and it is not a fail-open — `can()` allows only after
the explicit permission check, so the missing resource rule can only ever remove access.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

#### `POST /api/v1/clinical-records`
- Authentication: Yes
- Permission: `clinical_record:write`
- Tenant scope: session — the new row's `tenant_id` and `author_id` are the session's
- Ownership rule: the referenced patient must resolve inside the same tenant, or `404`
- Input schema: `ClinicalRecordCreate` — unknown fields rejected, one narrative of `body`/`soap`
- Output schema: `ClinicalRecordDetail` (`201`)
- Audit: `clinical_record.write` SUCCESS, written in the same transaction as the insert (INV-4)
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401`, `403`, `404` (patient absent or another tenant's), `422`; fails closed = yes
- Step-up: no

#### `GET /api/v1/clinical-records/{id}`
- Authentication: Yes
- Permission: `clinical_record:read`
- Tenant scope: both — the session resolves the tenant, the record is matched against it
- Ownership rule: another tenant's record is `404` with no body fields
- Input schema: none — `id` is a UUID path parameter
- Output schema: `ClinicalRecordDetail`, versions ascending (R9)
- Audit: `clinical_record.read` on every call, including the `404` denial
- Rate limit: deferred, as above
- Errors: `401`, `403`, `404`, `422`; fails closed = yes
- Step-up: no

#### `GET /api/v1/clinical-records/{id}/versions/{version}`
- Authentication: Yes
- Permission: `clinical_record:read`
- Tenant scope: both
- Ownership rule: the version must belong to a record of the caller's tenant
- Input schema: none — `version` is a positive integer path parameter
- Output schema: `ClinicalRecordVersionRead`
- Audit: `clinical_record.read` on every call, including the `404`
- Rate limit: deferred, as above
- Errors: `401`, `403`, `404`, `422`; fails closed = yes
- Step-up: no

#### `GET /api/v1/patients/{patient_id}/clinical-records`
- Authentication: Yes
- Permission: `clinical_record:read`
- Tenant scope: session, plus the patient must resolve inside the tenant
- Ownership rule: every returned record's `patient_id` is the path patient, in the caller's tenant
- Input schema: `limit` bounded `1..100` (default 50), an opaque signed `cursor`
- Output schema: `ClinicalRecordsPublic` — each entry carries its current version
- Audit: `clinical_record.read` on every call, including the `404`
- Rate limit: deferred, as above
- Errors: `401`, `403`, `404`, `422` (including a forged cursor); fails closed = yes
- Step-up: no

#### `PATCH /api/v1/clinical-records/{id}`
- Authentication: Yes
- Permission: `clinical_record:write`
- Tenant scope: both
- Ownership rule: refused once the record is signed — `403 NOTE_ALREADY_SIGNED`, no version written
- Input schema: `ClinicalRecordAppend` — unknown fields rejected; `amendment_reason` required (R7)
- Output schema: `ClinicalRecordDetail` (`200`)
- Audit: `clinical_record.write` — SUCCESS, or DENIED with the refusal code, same transaction
- Rate limit: deferred, as above
- Errors: `401`, `403` (`NOTE_ALREADY_SIGNED`), `404`, `409` (`VERSION_CONFLICT`),
  `422` (`AMENDMENT_REASON_REQUIRED`); fails closed = yes
- Step-up: no

#### `POST /api/v1/clinical-records/{id}/amendments`
- Authentication: Yes
- Permission: `clinical_record:write`
- Tenant scope: both
- Ownership rule: allowed on a signed record; the new version names the one it supersedes
- Input schema: `ClinicalRecordAppend` — `amendment_reason` required (R7)
- Output schema: `ClinicalRecordDetail` (`201`)
- Audit: `clinical_record.write` with the controlled reason code `AMENDMENT` — never the free text
- Rate limit: deferred, as above
- Errors: `401`, `403`, `404`, `409`, `422`; fails closed = yes
- Step-up: no

#### `POST /api/v1/clinical-records/{id}/sign`
- Authentication: Yes
- Permission: `clinical_record:write`, **and** the actor must be the current version's author
- Tenant scope: both
- Ownership rule: identity-bound; another clinician's signature attempt is `403`
- Input schema: none — the body must be empty; anything else is `422`
- Output schema: `ClinicalRecordDetail` (`200`)
- Audit: `clinical_record.write` SUCCESS or DENIED, same transaction
- Rate limit: deferred, as above
- Errors: `401`, `403` (`NOTE_ALREADY_SIGNED`, `SIGN_NOT_VERSION_AUTHOR`), `404`; fails closed = yes
- Step-up: no
"""

import uuid

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from app.api.deps import ActorDep
from app.modules.clinical_records import service
from app.modules.clinical_records.schemas import (
    DEFAULT_TIMELINE_PAGE_SIZE,
    MAX_TIMELINE_PAGE_SIZE,
    ClinicalRecordAppend,
    ClinicalRecordCreate,
    ClinicalRecordDetail,
    ClinicalRecordsPublic,
    ClinicalRecordVersionRead,
)
from app.modules.patients import service as patients_service
from app.modules.users_roles.policy import Actor, Decision, ResourceRef, can, enforce

router = APIRouter(tags=["clinical-records"])

# The longest cursor the routes accept. A cursor is a signed base64 token around a timestamp and a
# UUID; the bound keeps a hostile parameter from reaching the decoder.
MAX_CURSOR_LENGTH = 512

# The refusal message for a record or version the caller cannot resolve. One body for "absent" and
# "another tenant's", so the response discloses no existence (R10).
_NOT_FOUND = "Clinical record not found"


def _context(actor: Actor, request: Request) -> service.AuditContext:
    """The request-scoped identifiers the audit envelope carries.

    `request.client` is what the ASGI server accepted the connection from; a proxy that rewrites it
    is a deployment concern, exactly as `app/modules/audit/router.py` records.
    """
    return service.AuditContext(
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        request_id=request.headers.get("x-request-id"),
        correlation_id=request.headers.get("x-correlation-id"),
        source_ip=None if request.client is None else request.client.host,
    )


def _refuse(
    *,
    actor: Actor,
    context: service.AuditContext,
    decision: Decision,
    action: str,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
) -> None:
    """Audit a policy denial, then raise it.

    Deny-by-default means the refusal is the *first* thing that happens, and an attempt on a chart is
    exactly the event the trail exists to hold: it is recorded with the same fidelity as a success
    before the response is built (`05-data-and-audit.md`, "read / write refusal").
    """
    service.record_denial(
        tenant_id=actor.tenant_id,
        context=context,
        action=action,
        reason=service.denial_reason_code(decision.code),
        resource_id=resource_id,
        patient_id=patient_id,
    )
    enforce(decision)


def _authorise(
    *,
    actor: Actor,
    context: service.AuditContext,
    permission: str,
    action: str,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
) -> None:
    """Apply the central decision, resource-tenant check included, and audit a refusal."""
    decision = can(actor, permission, ResourceRef(tenant_id=actor.tenant_id))
    if decision.allowed:
        return
    _refuse(
        actor=actor,
        context=context,
        decision=decision,
        action=action,
        resource_id=resource_id,
        patient_id=patient_id,
    )


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _unprocessable(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": code, "message": message},
    )


def _refusal(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message},
    )


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


@router.post(
    "/clinical-records",
    response_model=ClinicalRecordDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_clinical_record(
    *, actor: ActorDep, request: Request, record_in: ClinicalRecordCreate
) -> ClinicalRecordDetail:
    """Create a record and its version 1. Tenant and author come from the session (R1)."""
    context = _context(actor, request)
    _authorise(
        actor=actor,
        context=context,
        permission=service.CLINICAL_RECORD_WRITE_PERMISSION,
        action=service.RECORD_WRITE_ACTION,
        patient_id=record_in.patient_id,
    )
    # The patient is reached through its module's service facade, never its tables
    # (`build-contract.md` §7). `None` is "absent" and "another tenant's" alike, so the answer is
    # `404` and the attempt is audited as a denial.
    if (
        patients_service.get_patient(
            tenant_id=actor.tenant_id, patient_id=record_in.patient_id
        )
        is None
    ):
        service.record_denial(
            tenant_id=actor.tenant_id,
            context=context,
            action=service.RECORD_WRITE_ACTION,
            reason=service.AUTHZ_DENIED_CROSS_TENANT,
            patient_id=record_in.patient_id,
        )
        raise _not_found("Patient not found")
    return service.create_record(
        tenant_id=actor.tenant_id, context=context, record_in=record_in
    )


@router.get("/clinical-records/{record_id}", response_model=ClinicalRecordDetail)
def read_clinical_record(
    *, actor: ActorDep, request: Request, record_id: uuid.UUID
) -> ClinicalRecordDetail:
    """One record plus its versions, ascending. Another tenant's record is `404`, never `403`."""
    context = _context(actor, request)
    _authorise(
        actor=actor,
        context=context,
        permission=service.CLINICAL_RECORD_READ_PERMISSION,
        action=service.RECORD_READ_ACTION,
        resource_id=record_id,
    )
    outcome = service.get_record(
        tenant_id=actor.tenant_id, context=context, record_id=record_id
    )
    if outcome.record is None:
        raise _not_found(_NOT_FOUND)
    return outcome.record


@router.get(
    "/clinical-records/{record_id}/versions/{version}",
    response_model=ClinicalRecordVersionRead,
)
def read_clinical_record_version(
    *,
    actor: ActorDep,
    request: Request,
    record_id: uuid.UUID,
    version: int = Path(ge=1),
) -> ClinicalRecordVersionRead:
    """One version of one record. A missing version is `404` with no partial record."""
    context = _context(actor, request)
    _authorise(
        actor=actor,
        context=context,
        permission=service.CLINICAL_RECORD_READ_PERMISSION,
        action=service.RECORD_READ_ACTION,
        resource_id=record_id,
    )
    outcome = service.get_version(
        tenant_id=actor.tenant_id,
        context=context,
        record_id=record_id,
        version=version,
    )
    if outcome.version is None:
        raise _not_found(_NOT_FOUND)
    return outcome.version


@router.get(
    "/patients/{patient_id}/clinical-records", response_model=ClinicalRecordsPublic
)
def list_patient_clinical_records(
    *,
    actor: ActorDep,
    request: Request,
    patient_id: uuid.UUID,
    limit: int = Query(
        default=DEFAULT_TIMELINE_PAGE_SIZE, ge=1, le=MAX_TIMELINE_PAGE_SIZE
    ),
    cursor: str | None = Query(default=None, max_length=MAX_CURSOR_LENGTH),
) -> ClinicalRecordsPublic:
    """One keyset page of a patient's timeline, newest first. The read is audited."""
    context = _context(actor, request)
    _authorise(
        actor=actor,
        context=context,
        permission=service.CLINICAL_RECORD_READ_PERMISSION,
        action=service.RECORD_READ_ACTION,
        patient_id=patient_id,
    )
    if (
        patients_service.get_patient(tenant_id=actor.tenant_id, patient_id=patient_id)
        is None
    ):
        service.record_denial(
            tenant_id=actor.tenant_id,
            context=context,
            action=service.RECORD_READ_ACTION,
            reason=service.AUTHZ_DENIED_CROSS_TENANT,
            patient_id=patient_id,
        )
        raise _not_found("Patient not found")
    try:
        outcome = service.list_timeline(
            tenant_id=actor.tenant_id,
            context=context,
            patient_id=patient_id,
            limit=limit,
            cursor=cursor,
        )
    except service.InvalidCursor as error:
        raise _unprocessable("INVALID_CURSOR", str(error)) from error
    if outcome.page is None:
        raise _not_found("Patient not found")
    return outcome.page


@router.patch("/clinical-records/{record_id}", response_model=ClinicalRecordDetail)
def append_clinical_record_version(
    *,
    actor: ActorDep,
    request: Request,
    record_id: uuid.UUID,
    append_in: ClinicalRecordAppend,
) -> ClinicalRecordDetail:
    """Append a version while the record is unsigned; once signed, `403 NOTE_ALREADY_SIGNED`."""
    return _append(
        actor=actor,
        request=request,
        record_id=record_id,
        append_in=append_in,
        amendment=False,
    )


@router.post(
    "/clinical-records/{record_id}/amendments",
    response_model=ClinicalRecordDetail,
    status_code=status.HTTP_201_CREATED,
)
def amend_clinical_record(
    *,
    actor: ActorDep,
    request: Request,
    record_id: uuid.UUID,
    append_in: ClinicalRecordAppend,
) -> ClinicalRecordDetail:
    """Append an amendment: a new version naming the version it supersedes, with a reason (R6)."""
    return _append(
        actor=actor,
        request=request,
        record_id=record_id,
        append_in=append_in,
        amendment=True,
    )


def _append(
    *,
    actor: Actor,
    request: Request,
    record_id: uuid.UUID,
    append_in: ClinicalRecordAppend,
    amendment: bool,
) -> ClinicalRecordDetail:
    """The shared body of `PATCH` and `POST .../amendments` — one code path, as the design says."""
    context = _context(actor, request)
    _authorise(
        actor=actor,
        context=context,
        permission=service.CLINICAL_RECORD_WRITE_PERMISSION,
        action=service.RECORD_WRITE_ACTION,
        resource_id=record_id,
    )
    try:
        outcome = service.append_version(
            tenant_id=actor.tenant_id,
            context=context,
            record_id=record_id,
            append_in=append_in,
            amendment=amendment,
        )
    except service.VersionConflict as error:
        raise _conflict(service.VERSION_CONFLICT, str(error)) from error
    if outcome.status == service.STATUS_ALREADY_SIGNED:
        raise _refusal(
            service.NOTE_ALREADY_SIGNED,
            "The record is signed; append an amendment instead",
        )
    if outcome.status == service.STATUS_REASON_REQUIRED:
        raise _unprocessable(
            service.AMENDMENT_REASON_REQUIRED,
            "amendment_reason is required from version 2 onwards",
        )
    if outcome.record is None:
        raise _not_found(_NOT_FOUND)
    return outcome.record


@router.post("/clinical-records/{record_id}/sign", response_model=ClinicalRecordDetail)
def sign_clinical_record(
    *, actor: ActorDep, request: Request, record_id: uuid.UUID
) -> ClinicalRecordDetail:
    """Sign the current version. Identity-bound: only its author may sign it (R4)."""
    context = _context(actor, request)
    _authorise(
        actor=actor,
        context=context,
        permission=service.CLINICAL_RECORD_WRITE_PERMISSION,
        action=service.RECORD_WRITE_ACTION,
        resource_id=record_id,
    )
    outcome = service.sign_record(
        tenant_id=actor.tenant_id, context=context, record_id=record_id
    )
    if outcome.status == service.STATUS_ALREADY_SIGNED:
        raise _refusal(service.NOTE_ALREADY_SIGNED, "The record is already signed")
    if outcome.status == service.STATUS_NOT_AUTHOR:
        raise _refusal(
            service.SIGN_NOT_VERSION_AUTHOR,
            "Only the author of the current version may sign it",
        )
    if outcome.record is None:
        raise _not_found(_NOT_FOUND)
    return outcome.record


__all__ = ["router"]
