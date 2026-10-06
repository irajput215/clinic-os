"""The patients HTTP API — four routes, and no more.

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
- Input schema: none — `limit` is bounded `1..25`
- Output schema: `PatientsPublic`
- Audit: deferred — `patient.read` needs `care_relationship_id` and `purpose`, and the
  treating-relationship rule that supplies them is blocked on the `care_relationships` table (T1-34)
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD` or no organisation on the account), `422`; fails closed = yes
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

Out of scope for this slice — merge, search, duplicates, export, the treating-relationship rule,
`patient.read` events, identifier validation, and encryption/blind-index key handling — is listed
with a reason in the `service` module docstring. The treating-relationship resource rule (task T1-34) is a
blocked dependency with no `care_relationships` table; `can()` therefore has no resource rule to run
yet, which can only remove access, never grant it.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import ActorDep
from app.modules.patients import service
from app.modules.patients.schemas import (
    PatientCreate,
    PatientRead,
    PatientsPublic,
    PatientUpdate,
)
from app.modules.users_roles.catalog import PATIENT_PERMISSIONS
from app.modules.users_roles.policy import ResourceRef
from app.modules.users_roles.service import authorize

router = APIRouter(prefix="/patients", tags=["patients"])

# The server-side maximum for one page of patients. A client may ask for fewer; asking for
# more is a `422` rather than a silently truncated result.
MAX_PATIENTS_PAGE_SIZE = 25


def _patient_not_found() -> HTTPException:
    """One answer for "absent" and "another tenant's", so the response leaks no existence."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
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
    limit: int = Query(default=MAX_PATIENTS_PAGE_SIZE, ge=1, le=MAX_PATIENTS_PAGE_SIZE),
) -> PatientsPublic:
    """List the caller's patients, bounded by the server maximum."""
    authorize(actor, PATIENT_PERMISSIONS["read"])
    return service.list_patients(tenant_id=actor.tenant_id, limit=limit)


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
