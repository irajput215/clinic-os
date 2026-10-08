"""The TGA approvals HTTP API.

Design: `docs/features/08-tga-approvals/03-design.md`, "Endpoints" and "Deny-by-default path for each
request". Requirements: `docs/features/08-tga-approvals/01-requirements.md` R1, R5, R6, R8, R9, R12.

The request path is the design's, in its order: authenticate → resolve the tenant from the session →
authorise through the central policy layer → audit the decision, **including refusals** → validate the
body against a strict schema → execute inside the RLS-scoped transaction. `app.api.deps.get_actor`
does the first two (INV-1), `authorize()` in `users_roles.service` does the third, `_authorize` below
adds the fourth, FastAPI's `extra="forbid"` schemas do the fifth, and the service does the sixth.

Two things this router deliberately does **not** do:

* **No `DELETE` route.** An approval is never hard-deleted by the application (R13); there is no
  endpoint, and the database grant withholds the privilege.
* **No `state`, `tenant_id`, `created_by` or `verified_by` from the client.** They are not in any
  request model, and `extra="forbid"` makes sending one a `422` rather than a silently ignored field
  (S5, R2).

`POST /api/v1/tga-approvals/match` is a `POST` on purpose: `patient_id`, the category, the dosage form
and the service date are all PHI-adjacent, and a query string reaches access logs, proxy logs and
browser history (T2-29; `app.core.errors` says the same about `instance`).

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

| Method and path | Authentication | Permission | Tenant scope | Input schema | Output schema | Audit | Step-up |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /api/v1/tga-approvals` | yes | `tga_approval:create` | session | `TgaApprovalCreate` | `TgaApprovalRead` | `tga_approval.create` (same transaction) | deferred — see below |
| `GET /api/v1/tga-approvals` | yes | `tga_approval:read` | session (a client `tenant_id` is ignored and audited) | `state`, `expiring_within_days`, `limit`, `cursor` | `TgaApprovalRegister` | `tga_approval.read` (same transaction) | no |
| `GET /api/v1/patients/{patient_id}/tga-approvals` | yes | `tga_approval:read` | session + patient match | `limit`, `cursor` | `TgaApprovalsPublic` | `tga_approval.read` (same transaction) | no |
| `GET /api/v1/tga-approvals/{id}` | yes | `tga_approval:read` | session + resource match | path UUID | `TgaApprovalDetail` | `tga_approval.read` (same transaction) | no |
| `POST /api/v1/tga-approvals/{id}/verify` | yes | `tga_approval:verify` | session + resource match | `TgaApprovalVerify` | `TgaApprovalRead` | `tga_approval.verify` (same transaction) | deferred — see below |
| `POST /api/v1/tga-approvals/{id}/revoke` | yes | `tga_approval:revoke` | session + resource match | `TgaApprovalRevoke` | `TgaApprovalRead` | `tga_approval.state_change` (same transaction) | deferred — see below |
| `POST /api/v1/tga-approvals/{id}/supersede` | yes | `tga_approval:create` | session + resource match | `TgaApprovalSupersede` | `TgaApprovalRead` (201) | `tga_approval.create` (same transaction) | deferred — see below |
| `POST /api/v1/tga-approvals/match` | yes | `tga_approval:read` | session | `TgaMatchRequest` | `TgaMatchResponse` | `tga_approval.match` (same transaction) | no |

**Reads are audited as `tga_approval.read`.** `05-data-and-audit.md` names `approval.read` for a
patient-level read; the platform's closed catalogue had no TGA read action until it was registered
there as `tga_approval.read` on 2026-10-07 (owner decision, M2 phase 2A, recorded in
`docs/features/04-audit-log/05-data-and-audit.md`). Every read writes one event, a permission or
tenant refusal included. Error responses
are `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, `VERIFIER_CANNOT_BE_CREATOR`, no
organisation), `404` (absent or another tenant's — never `403`), `409` (`ILLEGAL_STATE_TRANSITION`,
`DUPLICATE_APPROVAL_GRAIN`, `TGA_OVERLAPPING_ACTIVE_APPROVAL`), `422` (strict-schema and
window/application-number refusals), all through the single `application/problem+json` envelope in
`app.core.errors`.

**Step-up is deferred, and it is a real gap.** R9, T2-13 and T2-14 require a re-authentication within
15 minutes for `verify` and `revoke`; the mechanism is feature 02's, which is blocked by D-003 (the
identity model is open) and does not exist anywhere in this codebase — `auth.step_up` is a name in
the audit catalogue with no producer. What is enforced here is everything that does exist:
authentication, the permission, the four-eyes separation, the application-number re-entry and the
tenant boundary. Recorded in the PR body rather than approximated with a header check that would look
like a control and be none.
"""

import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.deps import ActorDep
from app.modules.patients import service as patients_service
from app.modules.tga_approvals import service
from app.modules.tga_approvals.schemas import (
    ApprovalStateCode,
    TgaApprovalCreate,
    TgaApprovalDetail,
    TgaApprovalRead,
    TgaApprovalRegister,
    TgaApprovalRevoke,
    TgaApprovalsPublic,
    TgaApprovalSupersede,
    TgaApprovalVerify,
    TgaMatchRequest,
    TgaMatchResponse,
)
from app.modules.tga_approvals.service import Refusal
from app.modules.users_roles.catalog import TGA_APPROVAL_PERMISSIONS, TGA_APPROVAL_READ
from app.modules.users_roles.policy import Actor, Decision, ResourceRef, can, enforce

# The module's own routes, under one prefix.
router = APIRouter(prefix="/tga-approvals", tags=["tga-approvals"])

# The patient-scoped list route the design names — `GET /api/v1/patients/{patient_id}/tga-approvals`.
# It is declared here rather than in the patients router because a module owns its routes and the
# patients module is another owner's; the path is the design's, so this is a second router with an
# absolute path rather than a second prefix (`app/api/main.py` includes both).
patient_router = APIRouter(tags=["tga-approvals"])


def _not_found() -> HTTPException:
    """One answer for "absent" and "another tenant's", so no response confirms existence."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="TGA approval not found"
    )


def _raise_refusal(refusal: Refusal) -> NoReturn:
    """Turn a service refusal into the API's refusal.

    The `{code, message}` shape is the one the policy layer already returns, so a client reads one
    envelope for every refusal regardless of which layer decided it. The message never carries a
    value from the request.
    """
    raise HTTPException(
        status_code=refusal.status_code,
        detail={"code": refusal.code, "message": refusal.message},
    )


def _authorize(
    actor: Actor, permission: str, *, action: str, resource: ResourceRef | None = None
) -> None:
    """Decide, **audit the decision including the refusal**, then raise the denial.

    `authorize()` in the users-and-roles service raises on denial, which would make the refusal
    unauditable: the design's deny-by-default path step 4 is *"audit the decision, including
    refusals"*, so the decision is taken here, written down, and only then enforced. A failure to
    write that event propagates — a refusal that cannot be audited fails closed.
    """
    decision: Decision = can(actor, permission, resource)
    if not decision.allowed:
        service.audit_denial(
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            actor_role=actor.actor_role,
            action=action,
            reason=decision.code.value,
        )
    enforce(decision)


def _patient_exists(actor: Actor, patient_id: uuid.UUID) -> None:
    """`404` unless the patient is one of the caller's own, resolved through the patients service.

    This module never reads the `patients` table - it reaches the patient through the other module's
    facade (`docs/reference/build-contract.md` §7), and `None` is that facade's answer for "absent"
    and "another tenant's" alike, so the refusal discloses nothing (R8). A patient's approval list
    resolves its patient inside its own transaction instead (`service.list_approvals`).
    """
    if (
        patients_service.get_patient(tenant_id=actor.tenant_id, patient_id=patient_id)
        is None
    ):
        raise _not_found()


def _invalid_cursor(error: service.InvalidCursor) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": "INVALID_CURSOR", "message": str(error)},
    )


@router.post("", response_model=TgaApprovalRead, status_code=status.HTTP_201_CREATED)
def create_tga_approval(
    *, actor: ActorDep, approval_in: TgaApprovalCreate
) -> TgaApprovalRead:
    """Record a manual entry. It starts `PENDING`; a second clinician activates it (R1, R5, US-1)."""
    _authorize(
        actor, TGA_APPROVAL_PERMISSIONS["create"], action=service.APPROVAL_CREATE
    )
    _patient_exists(actor, approval_in.patient_id)
    result = service.create_approval(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        approval_in=approval_in,
    )
    if isinstance(result, Refusal):
        _raise_refusal(result)
    return result


@patient_router.get(
    "/patients/{patient_id}/tga-approvals", response_model=TgaApprovalsPublic
)
def list_patient_tga_approvals(
    *,
    actor: ActorDep,
    patient_id: uuid.UUID,
    limit: Annotated[
        int, Query(ge=1, le=service.MAX_PAGE_SIZE)
    ] = service.DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> TgaApprovalsPublic:
    """A patient's approvals, keyset-paginated, tenant-scoped by RLS (F15, US-2)."""
    _authorize(actor, TGA_APPROVAL_READ, action=service.APPROVAL_READ)
    try:
        page = service.list_approvals(
            tenant_id=actor.tenant_id,
            patient_id=patient_id,
            limit=limit,
            cursor=cursor,
            actor_id=actor.user_id,
            actor_role=actor.actor_role,
        )
    except service.InvalidCursor as error:
        raise _invalid_cursor(error) from error
    if page is None:
        # Not one of the caller's patients; the refusal was audited `CROSS_TENANT` (R8).
        raise _not_found()
    return page


@router.get("", response_model=TgaApprovalRegister)
def list_tga_approvals(
    *,
    actor: ActorDep,
    request: Request,
    state: Annotated[list[ApprovalStateCode] | None, Query()] = None,
    expiring_within_days: Annotated[
        int | None, Query(ge=0, le=service.MAX_EXPIRING_WITHIN_DAYS)
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=service.MAX_PAGE_SIZE)
    ] = service.DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> TgaApprovalRegister:
    """The practice-wide register: every approval in the caller's practice, newest first.

    `state` (repeatable) and `expiring_within_days` are two selectors, and a row matches when it
    matches either; neither lists everything. `counts` is the practice's totals whatever the
    filter, for the register's filter chips. Contract: `docs2/sdlc/05-approvals/api.md`.
    """
    _authorize(actor, TGA_APPROVAL_READ, action=service.APPROVAL_READ)
    try:
        return service.list_register(
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            actor_role=actor.actor_role,
            states=state or (),
            expiring_within_days=expiring_within_days,
            limit=limit,
            cursor=cursor,
            client_tenant_id_supplied="tenant_id" in request.query_params,
        )
    except service.InvalidCursor as error:
        raise _invalid_cursor(error) from error


@router.post("/match", response_model=TgaMatchResponse)
def match_tga_approval(
    *, actor: ActorDep, match_in: TgaMatchRequest
) -> TgaMatchResponse:
    """Evaluate the grain at `date_of_service`. A non-match is a `200` with `matched = false`."""
    _authorize(actor, TGA_APPROVAL_READ, action=service.APPROVAL_MATCH)
    return service.match_approval(
        tenant_id=actor.tenant_id,
        patient_id=match_in.patient_id,
        tga_category=match_in.tga_category,
        dosage_form=match_in.dosage_form,
        date_of_service=match_in.date_of_service,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
    )


@router.get("/{approval_id}", response_model=TgaApprovalDetail)
def read_tga_approval(*, actor: ActorDep, approval_id: uuid.UUID) -> TgaApprovalDetail:
    """One approval and its supersede chain. Another tenant's id is `404`, never `403` (R8, S1)."""
    _authorize(actor, TGA_APPROVAL_READ, action=service.APPROVAL_READ)
    detail = service.get_approval(
        tenant_id=actor.tenant_id,
        approval_id=approval_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
    )
    if detail is None:
        raise _not_found()
    return detail


@router.post("/{approval_id}/verify", response_model=TgaApprovalRead)
def verify_tga_approval(
    *,
    actor: ActorDep,
    approval_id: uuid.UUID,
    verify_in: TgaApprovalVerify,
) -> TgaApprovalRead:
    """Activate a pending approval. The creator cannot be the verifier (R5, T2-13, T2-15)."""
    _authorize(
        actor,
        TGA_APPROVAL_PERMISSIONS["verify"],
        action=service.APPROVAL_VERIFY,
        resource=ResourceRef(tenant_id=actor.tenant_id),
    )
    result = service.verify_approval(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        approval_id=approval_id,
        application_number=verify_in.tga_application_number,
    )
    if isinstance(result, Refusal):
        _raise_refusal(result)
    return result


@router.post("/{approval_id}/revoke", response_model=TgaApprovalRead)
def revoke_tga_approval(
    *,
    actor: ActorDep,
    approval_id: uuid.UUID,
    revoke_in: TgaApprovalRevoke,
) -> TgaApprovalRead:
    """Revoke with a mandatory reason code. A revoked approval authorises nothing (R6, US-6)."""
    _authorize(
        actor,
        TGA_APPROVAL_PERMISSIONS["revoke"],
        action=service.APPROVAL_STATE_CHANGE,
        resource=ResourceRef(tenant_id=actor.tenant_id),
    )
    result = service.revoke_approval(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        approval_id=approval_id,
        reason_code=revoke_in.reason_code,
    )
    if isinstance(result, Refusal):
        _raise_refusal(result)
    return result


@router.post(
    "/{approval_id}/supersede",
    response_model=TgaApprovalRead,
    status_code=status.HTTP_201_CREATED,
)
def supersede_tga_approval(
    *,
    actor: ActorDep,
    approval_id: uuid.UUID,
    supersede_in: TgaApprovalSupersede,
) -> TgaApprovalRead:
    """Create the replacement grant for an approval (T2-9).

    The replacement is `PENDING` like any manual entry: the predecessor becomes `SUPERSEDED` in the
    transaction that **verifies** the replacement, so a verified approval's grain and dates are never
    edited in place (R12) and no single actor can create and activate a grant (R5).
    """
    _authorize(
        actor,
        TGA_APPROVAL_PERMISSIONS["create"],
        action=service.APPROVAL_CREATE,
        resource=ResourceRef(tenant_id=actor.tenant_id),
    )
    result = service.supersede_approval(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        approval_id=approval_id,
        approval_in=supersede_in,
    )
    if isinstance(result, Refusal):
        _raise_refusal(result)
    return result
