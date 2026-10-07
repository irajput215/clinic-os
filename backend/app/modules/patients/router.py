"""The patients HTTP API - five routes, and no more.

Design: `docs/features/05-patients/03-design.md`, "Endpoints" and "Deny-by-default request
path". Requirements: `docs/features/05-patients/01-requirements.md`.

Order of the request path, as the design fixes it: authenticate the session → resolve the
tenant from the session → authorise through the central policy layer → load the resource
under the tenant-scoped transaction → serialise through a declared response model. The
permission check is the one `docs/features/03-users-and-roles/03-design.md` specifies:
`can(actor, permission, resource)`, called through `app.modules.users_roles.service`, which
is the single place an authorisation decision is made.

**The tenant is resolved, never supplied (INV-1).** The actor is built by
`app.api.deps.get_actor` from `current_user.tenant_id` and nothing else: no body, path, query
or header can carry a tenant identifier, and a caller whose `tenant_id` is `None` is denied
rather than defaulted.

**Cross-tenant is `404`, never `403`** — a `403` confirms the record exists. The service
answers `None` for both "absent" and "another tenant's record", so the two are
indistinguishable to the caller.

**There is no `DELETE` route.** A patient is never hard-deleted by the application
(requirement R11); the database grant removes the capability as well.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

#### `POST /api/v1/patients`
- Authentication: Yes
- Permission: `patient:create`
- Tenant scope: session
- Ownership rule: none — creation has no prior resource; the new row's `tenant_id` is the session's tenant
- Input schema: `PatientCreate`
- Output schema: `PatientRead`
- Audit: `patient.create` — written in the same transaction as the insert (INV-4), with `field_set`
  (field names only)
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD` or no organisation on the account), `422`; fails closed = yes
- Step-up: no

#### `GET /api/v1/patients`
- Authentication: Yes
- Permission: `patient:read`
- Tenant scope: session
- Ownership rule: every returned row's `tenant_id` equals the session's tenant; another tenant's rows are absent, not denied
- Input schema: `limit` bounded `1..25`, an opaque signed `cursor`; **any other query parameter is
  refused** `422 UNSUPPORTED_QUERY_PARAMETER`, so a search term put in the URL (`?q=`) is never
  silently ignored and answered with the unfiltered list (R12)
- Output schema: `PatientsPublic` - one keyset page, the tenant's live total, `next_cursor`
- Audit: `patient.read` on the same transaction, with `result_count`; a permission refusal, an
  unsupported parameter and a cursor that does not verify are each audited `DENIED`
- Rate limit: deferred - the list is a plain tenant-scoped read, as before this change
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD` or no organisation on the account), `422` (`INVALID_CURSOR`, `UNSUPPORTED_QUERY_PARAMETER`, a bad `limit`); fails closed = yes
- Step-up: no

#### `POST /api/v1/patients/search`
- Authentication: Yes
- Permission: `patient:read`
- Tenant scope: session
- Ownership rule: as the list; another tenant's rows are absent from every result (S2)
- Input schema: `PatientSearch` - `q` (1..100 characters, at most 6 words), `cursor`, `limit` `1..25`;
  unknown fields rejected. The term is in the body because a search term never goes in a URL (R12)
- Output schema: `PatientsPublic`
- Audit: `patient.read` on the same transaction, with `result_count` and `query_filters` (the kinds
  of term used - `name_prefix`, `date_of_birth`, `reference` - never the term); refusals audited `DENIED`
- Rate limit: 120/min per session (`app/core/rate_limit.py`), an interim value - the threat model
  leaves the search limit open (T-05.13, "Rate-limit values for the search ... routes")
- Errors: `401`, `403` (`PERMISSION_NOT_HELD` or no organisation), `422` (`INVALID_CURSOR`, body
  validation), `429`; fails closed = yes
- Step-up: no

#### `GET /api/v1/patients/{patient_id}`
- Authentication: Yes
- Permission: `patient:read`
- Tenant scope: both — the session resolves the tenant, the resource is matched against it
- Ownership rule: the record is returned only when its `tenant_id` equals the session's tenant; otherwise `404` with no body fields
- Input schema: none — `patient_id` is a UUID path parameter
- Output schema: `PatientRead`
- Audit: deferred — `patient.read`, for the reason the list route gives (T1-34)
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD` or no organisation on the account), `404` (absent or another tenant's), `422`; fails closed = yes
- Step-up: no

#### `PATCH /api/v1/patients/{patient_id}`
- Authentication: Yes
- Permission: `patient:update`
- Tenant scope: both — the session resolves the tenant, the resource is matched against it
- Ownership rule: the record is updated only when its `tenant_id` equals the session's tenant; otherwise `404` and the row is untouched
- Input schema: `PatientUpdate` — unknown fields rejected
- Output schema: `PatientRead`
- Audit: `patient.update` — written in the same transaction as the change (INV-4), with
  `changed_fields` (names only)
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD` or no organisation on the account), `404` (absent or another tenant's), `422`; fails closed = yes
- Step-up: no

Out of scope for this slice - merge, identifier search, duplicates, export, the treating-relationship
rule, the single-record `patient.read` event, identifier validation, and encryption/blind-index key
handling - is listed
with a reason in the `service` module docstring. The treating-relationship resource rule (task T1-34) is a
blocked dependency with no `care_relationships` table; `can()` therefore has no resource rule to run
yet, which can only remove access, never grant it.
"""

import uuid
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import ActorDep
from app.core.rate_limit import patient_search_rate_limit
from app.modules.patients import service
from app.modules.patients.schemas import (
    MAX_CURSOR_LENGTH,
    MAX_PATIENTS_PAGE_SIZE,
    PatientCreate,
    PatientRead,
    PatientSearch,
    PatientsPublic,
    PatientUpdate,
)
from app.modules.users_roles.catalog import PATIENT_PERMISSIONS
from app.modules.users_roles.policy import Actor, ResourceRef, can, enforce
from app.modules.users_roles.service import authorize

router = APIRouter(prefix="/patients", tags=["patients"])

# The only query parameters `GET /patients` honours. Anything else - `q` above all - is refused rather
# than ignored: an ignored `?q=` would answer a search with the unfiltered list, and the term would
# already be in the URL. Search is `POST /patients/search` (R12).
_LIST_QUERY_PARAMETERS: Final[frozenset[str]] = frozenset({"limit", "cursor"})
UNSUPPORTED_QUERY_PARAMETER: Final[str] = "UNSUPPORTED_QUERY_PARAMETER"
INVALID_CURSOR: Final[str] = "INVALID_CURSOR"
# The audit reason for a policy refusal, the code the clinical-records trail uses for the same case.
AUTHZ_DENIED: Final[str] = "AUTHZ_DENIED"


def _patient_not_found() -> HTTPException:
    """One answer for "absent" and "another tenant's", so the response leaks no existence."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
    )


def _unprocessable(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": code, "message": message},
    )


def _read_context(actor: Actor, request: Request) -> service.ReadContext:
    """The audit envelope's actor fields, from the verified session; the address from the socket."""
    return service.ReadContext(
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        source_ip=None if request.client is None else request.client.host,
    )


def _authorise_read(actor: Actor, context: service.ReadContext) -> None:
    """`patient:read`, with the refusal audited before it is raised (R13, equal fidelity)."""
    decision = can(actor, PATIENT_PERMISSIONS["read"])
    if not decision.allowed:
        service.record_read_denial(
            tenant_id=actor.tenant_id, context=context, reason=AUTHZ_DENIED
        )
    enforce(decision)


def _invalid_cursor() -> HTTPException:
    return _unprocessable(
        INVALID_CURSOR,
        "The cursor is not valid for this request. Start again from the first page.",
    )


@router.post("", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
def create_patient(*, actor: ActorDep, patient_in: PatientCreate) -> PatientRead:
    """Create a patient in the caller's organisation. `tenant_id` comes from the session."""
    authorize(actor, PATIENT_PERMISSIONS["create"])
    return service.create_patient(
        tenant_id=actor.tenant_id,
        patient_in=patient_in,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
    )


@router.get("", response_model=PatientsPublic)
def list_patients(
    *,
    actor: ActorDep,
    request: Request,
    limit: int = Query(default=MAX_PATIENTS_PAGE_SIZE, ge=1, le=MAX_PATIENTS_PAGE_SIZE),
    cursor: str | None = Query(default=None, max_length=MAX_CURSOR_LENGTH),
) -> PatientsPublic:
    """One keyset page of the caller's patients. Follow `next_cursor` for the next page."""
    context = _read_context(actor, request)
    _authorise_read(actor, context)
    if set(request.query_params) - _LIST_QUERY_PARAMETERS:
        service.record_read_denial(
            tenant_id=actor.tenant_id,
            context=context,
            reason=UNSUPPORTED_QUERY_PARAMETER,
        )
        raise _unprocessable(
            UNSUPPORTED_QUERY_PARAMETER,
            "This list takes only limit and cursor. Search with POST /api/v1/patients/search,"
            " which keeps the search term out of the URL.",
        )
    try:
        return service.list_patients(
            tenant_id=actor.tenant_id, context=context, limit=limit, cursor=cursor
        )
    except service.InvalidCursor as error:
        raise _invalid_cursor() from error


@router.post(
    "/search",
    response_model=PatientsPublic,
    dependencies=[Depends(patient_search_rate_limit)],
)
def search_patients(
    *, actor: ActorDep, request: Request, search_in: PatientSearch
) -> PatientsPublic:
    """Find the caller's patients by name prefix, date of birth or reference. Keyset-paged."""
    context = _read_context(actor, request)
    _authorise_read(actor, context)
    try:
        return service.search_patients(
            tenant_id=actor.tenant_id,
            context=context,
            q=search_in.q,
            limit=search_in.limit,
            cursor=search_in.cursor,
        )
    except service.InvalidCursor as error:
        raise _invalid_cursor() from error


@router.get("/{patient_id}", response_model=PatientRead)
def read_patient(*, actor: ActorDep, patient_id: uuid.UUID) -> PatientRead:
    """Read one patient. Another tenant's record is `404`, never `403`."""
    patient = service.get_patient(tenant_id=actor.tenant_id, patient_id=patient_id)
    if patient is None:
        raise _patient_not_found()
    # The row was loaded under the session's tenant, so its `tenant_id` equals the actor's; the
    # policy call states that explicitly and refuses any mismatch with `404 CROSS_TENANT` (R6).
    authorize(
        actor, PATIENT_PERMISSIONS["read"], ResourceRef(tenant_id=actor.tenant_id)
    )
    return patient


@router.patch("/{patient_id}", response_model=PatientRead)
def update_patient(
    *,
    actor: ActorDep,
    patient_id: uuid.UUID,
    patient_in: PatientUpdate,
) -> PatientRead:
    """Update one patient. Unknown fields are `422`; another tenant's record is `404`."""
    patient = service.get_patient(tenant_id=actor.tenant_id, patient_id=patient_id)
    if patient is None:
        raise _patient_not_found()
    authorize(
        actor, PATIENT_PERMISSIONS["update"], ResourceRef(tenant_id=actor.tenant_id)
    )
    updated = service.update_patient(
        tenant_id=actor.tenant_id,
        patient_id=patient_id,
        patient_in=patient_in,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
    )
    if updated is None:
        raise _patient_not_found()
    return updated
