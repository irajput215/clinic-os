"""The patients HTTP API — four routes, and no more.

Design: `docs/features/05-patients/03-design.md`, "Endpoints" and "Deny-by-default request
path". Requirements: `docs/features/05-patients/01-requirements.md`.

Order of the request path, as the design fixes it: authenticate the session → resolve the
tenant from the session → validate the body → execute inside the tenant-scoped
transaction → serialise through a declared response model. The steps this slice cannot
perform (permission check, treating-relationship rule, audit) are declared `deferred`
below rather than skipped silently.

**The tenant is resolved, never supplied (INV-1).** `require_tenant` reads
`current_user.tenant_id` and nothing else: no body, path, query or header can carry a
tenant identifier, and a caller whose `tenant_id` is `None` is denied rather than
defaulted (`TenantContextRequired` would otherwise refuse to open the transaction).

**Cross-tenant is `404`, never `403`** — a `403` confirms the record exists. The service
answers `None` for both "absent" and "another tenant's record", so the two are
indistinguishable to the caller.

**There is no `DELETE` route.** A patient is never hard-deleted by the application
(requirement R11); the database grant removes the capability as well.

Out of scope for this slice — merge, search, duplicates, export, the treating-relationship
rule, the permission layer, audit events, identifier validation, and encryption/blind-index
key handling — is listed with a reason in the `service` module docstring.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

#### `POST /api/v1/patients`
- Authentication: Yes
- Permission: deferred — feature 03 (authentication and RBAC) is not started, so there is no central policy layer and no permission to name
- Tenant scope: session
- Ownership rule: none — creation has no prior resource; the new row's `tenant_id` is the session's tenant
- Input schema: `PatientCreate`
- Output schema: `PatientRead`
- Audit: deferred — feature 04 (audit log) is not built and the required action names are not registered
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401` (unauthenticated), `403` (no organisation on the account), `422`; fails closed = yes
- Step-up: no

#### `GET /api/v1/patients`
- Authentication: Yes
- Permission: deferred — feature 03 (authentication and RBAC) is not started, so there is no central policy layer and no permission to name
- Tenant scope: session
- Ownership rule: every returned row's `tenant_id` equals the session's tenant; another tenant's rows are absent, not denied
- Input schema: none — `limit` is bounded `1..25`
- Output schema: `PatientsPublic`
- Audit: deferred — every read is an audited clinical action (`01-requirements.md`, clinical invariant 3) but feature 04 is not built
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401` (unauthenticated), `403` (no organisation on the account), `422`; fails closed = yes
- Step-up: no

#### `GET /api/v1/patients/{patient_id}`
- Authentication: Yes
- Permission: deferred — feature 03 (authentication and RBAC) is not started, so there is no central policy layer and no permission to name
- Tenant scope: both — the session resolves the tenant, the resource is matched against it
- Ownership rule: the record is returned only when its `tenant_id` equals the session's tenant; otherwise `404` with no body fields
- Input schema: none — `patient_id` is a UUID path parameter
- Output schema: `PatientRead`
- Audit: deferred — the read and every refusal are audited by requirement R13, but feature 04 is not built
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401` (unauthenticated), `403` (no organisation on the account), `404` (absent or another tenant's), `422`; fails closed = yes
- Step-up: no

#### `PATCH /api/v1/patients/{patient_id}`
- Authentication: Yes
- Permission: deferred — feature 03 (authentication and RBAC) is not started, so there is no central policy layer and no permission to name
- Tenant scope: both — the session resolves the tenant, the resource is matched against it
- Ownership rule: the record is updated only when its `tenant_id` equals the session's tenant; otherwise `404` and the row is untouched
- Input schema: `PatientUpdate` — unknown fields rejected
- Output schema: `PatientRead`
- Audit: deferred — feature 04 (audit log) is not built and the required action names are not registered
- Rate limit: deferred — no rate-limit layer is applied to authenticated routes yet
- Errors: `401` (unauthenticated), `403` (no organisation on the account), `404` (absent or another tenant's), `422`; fails closed = yes
- Step-up: no
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser
from app.modules.patients import service
from app.modules.patients.schemas import (
    PatientCreate,
    PatientRead,
    PatientsPublic,
    PatientUpdate,
)

router = APIRouter(prefix="/patients", tags=["patients"])

# The server-side maximum for one page of patients. A client may ask for fewer; asking for
# more is a `422` rather than a silently truncated result.
MAX_PATIENTS_PAGE_SIZE = 25


def require_tenant(current_user: CurrentUser) -> uuid.UUID:
    """Resolve the tenant from the authenticated session, or deny.

    Fail closed: an account with no organisation is refused, never defaulted to some
    tenant and never given an unscoped query. The value comes from the session row only —
    nothing in the request can supply it (INV-1).
    """
    tenant_id = current_user.tenant_id
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has no organisation",
        )
    return tenant_id


TenantId = Annotated[uuid.UUID, Depends(require_tenant)]


def _patient_not_found() -> HTTPException:
    """One answer for "absent" and "another tenant's", so the response leaks no existence."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
    )


@router.post("", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
def create_patient(
    *, tenant_id: TenantId, current_user: CurrentUser, patient_in: PatientCreate
) -> PatientRead:
    """Create a patient in the caller's tenant. `tenant_id` comes from the session."""
    return service.create_patient(
        tenant_id=tenant_id, patient_in=patient_in, actor_id=current_user.id
    )


@router.get("", response_model=PatientsPublic)
def list_patients(
    *,
    tenant_id: TenantId,
    limit: int = Query(default=MAX_PATIENTS_PAGE_SIZE, ge=1, le=MAX_PATIENTS_PAGE_SIZE),
) -> PatientsPublic:
    """List the caller's patients, bounded by the server maximum."""
    return service.list_patients(tenant_id=tenant_id, limit=limit)


@router.get("/{patient_id}", response_model=PatientRead)
def read_patient(*, tenant_id: TenantId, patient_id: uuid.UUID) -> PatientRead:
    """Read one patient. Another tenant's record is `404`, never `403`."""
    patient = service.get_patient(tenant_id=tenant_id, patient_id=patient_id)
    if patient is None:
        raise _patient_not_found()
    return patient


@router.patch("/{patient_id}", response_model=PatientRead)
def update_patient(
    *,
    tenant_id: TenantId,
    current_user: CurrentUser,
    patient_id: uuid.UUID,
    patient_in: PatientUpdate,
) -> PatientRead:
    """Update one patient. Unknown fields are `422`; another tenant's record is `404`."""
    patient = service.update_patient(
        tenant_id=tenant_id,
        patient_id=patient_id,
        patient_in=patient_in,
        actor_id=current_user.id,
    )
    if patient is None:
        raise _patient_not_found()
    return patient
