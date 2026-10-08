"""The prescriptions HTTP API - the four routes agreed in `docs2/sdlc/07-script-queue/api.md`, plus the
prescriber list the staging form needs.

The request path is the designs' (`11-prescribing/03-design.md` "Deny-by-default request path"):
authenticate -> resolve the tenant from the session (`app.api.deps.get_actor`) -> authorise through the
central policy layer -> **audit the refusal** -> validate the strict body -> execute in the
tenant-scoped transaction, where the service audits every decision it takes.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

| Method and path | Permission | Step-up | Audit | Rate |
| --- | --- | --- | --- | --- |
| `GET /api/v1/prescriptions` | `prescription:read` | no | none - the catalogue has no prescription read action (gap, recorded) | 300/min |
| `GET /api/v1/prescriptions/prescribers` | `prescription:create` | no | none (staff names only) | 300/min |
| `POST /api/v1/prescriptions` | `prescription:create` | no | `prescription.create` | 30/min |
| `POST /api/v1/prescriptions/{id}/sign` | `prescription:sign` + prescriber of record | `prescription.sign` grant | `prescription.sign`, `auth.step_up_failed` | 30/min |
| `POST /api/v1/prescriptions/{id}/dispatch` | `prescription:dispatch` | `prescription.dispatch` grant | `prescription.dispatch`, `prescription.dispatch_blocked`, `auth.step_up_failed` | 30/min |

Errors: `401` (no session), `403` (`PERMISSION_NOT_HELD`, `NOT_PRESCRIBER_OF_RECORD`,
`STEP_UP_REQUIRED`), `404` (absent **or** another tenant's - never `403`), `409`
(`INVALID_STATE_TRANSITION`), `422` (strict schema; `IDEMPOTENCY_KEY_REQUIRED`;
`PRESCRIBER_NOT_AUTHORIZED`; a gate refusal, whose `detail.code` is the match reason and whose
message is *"Active TGA Approval Required"*). Gate refusals are `422` at sign **and** at dispatch:
`10-prescription-safety-gate/03-design.md` fixes `422` for steps 7-8, and docs2's proposed `409` for
the sign-time refusal is reconciled to it.

Dispatch answers **`202 Accepted`** with the prescription `QUEUED`: the intent is committed to the
outbox and nothing has been sent (no transport exists - `transport.py`). A replay of the same
`Idempotency-Key` answers `200` with the current state and changes nothing.

No `DELETE`, no `PATCH`, no `state` anywhere in a request (FEAT-11 R7, R14).
"""

import uuid
from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.api.deps import ActorDep
from app.core.rate_limit import prescription_write_rate_limit, read_rate_limit
from app.modules.prescriptions import service
from app.modules.prescriptions.schemas import (
    PrescribersPublic,
    PrescriptionCreate,
    PrescriptionDispatch,
    PrescriptionRead,
    PrescriptionSign,
    PrescriptionsPublic,
)
from app.modules.prescriptions.service import Refusal
from app.modules.users_roles.catalog import PRESCRIPTION_PERMISSIONS
from app.modules.users_roles.policy import Actor, can, enforce

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])

StateFilter = Literal[
    "DRAFT",
    "SIGNED",
    "BLOCKED",
    "QUEUED",
    "DISPATCHED",
    "FAILED",
    "REQUIRES_RECONCILIATION",
    "CANCELLED",
    "REVERSED",
]

# The client's intent key: printable, bounded. It is hashed with the tenant and the prescription
# before it is stored or compared (FEAT-10 R12), so its content never reaches the database.
_KEY_MAX = 255


def _raise(refusal: Refusal) -> NoReturn:
    raise HTTPException(
        status_code=refusal.status_code,
        detail={"code": refusal.code, "message": refusal.message},
    )


def _authorize(actor: Actor, permission: str, *, action: str) -> None:
    """Decide, audit a refusal on its own transaction, then enforce (deny-by-default step 4)."""
    decision = can(actor, permission)
    if not decision.allowed:
        service.audit_denial(
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            actor_role=actor.actor_role,
            action=action,
            reason=decision.code.value,
        )
    enforce(decision)


@router.get(
    "", response_model=PrescriptionsPublic, dependencies=[Depends(read_rate_limit)]
)
def list_prescriptions(
    *,
    actor: ActorDep,
    state: Annotated[list[StateFilter] | None, Query()] = None,
    prescriber_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    limit: Annotated[
        int, Query(ge=1, le=service.MAX_PAGE_SIZE)
    ] = service.DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PrescriptionsPublic:
    """The queue and its history, newest first; actionable rows carry the gate's answer **now**."""
    enforce(can(actor, PRESCRIPTION_PERMISSIONS["read"]))
    try:
        return service.list_prescriptions(
            tenant_id=actor.tenant_id,
            states=state or (),
            prescriber_id=prescriber_id,
            patient_id=patient_id,
            limit=limit,
            cursor=cursor,
        )
    except service.InvalidCursor as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_CURSOR", "message": str(error)},
        ) from error


@router.get(
    "/prescribers",
    response_model=PrescribersPublic,
    dependencies=[Depends(read_rate_limit)],
)
def list_prescribers(*, actor: ActorDep) -> PrescribersPublic:
    """Who a draft may be addressed to: active colleagues holding `prescription:sign`."""
    enforce(can(actor, PRESCRIPTION_PERMISSIONS["stage"]))
    return service.list_prescribers(tenant_id=actor.tenant_id)


@router.post(
    "",
    response_model=PrescriptionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(prescription_write_rate_limit)],
)
def stage_prescription(
    *, actor: ActorDep, body: PrescriptionCreate
) -> PrescriptionRead:
    """Stage a `DRAFT`. The response carries the gate's current answer so the UI can warn."""
    _authorize(actor, PRESCRIPTION_PERMISSIONS["stage"], action=service.CREATE)
    result = service.stage(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        body=body,
    )
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.post(
    "/{prescription_id}/sign",
    response_model=PrescriptionRead,
    dependencies=[Depends(prescription_write_rate_limit)],
)
def sign_prescription(
    *, actor: ActorDep, prescription_id: uuid.UUID, body: PrescriptionSign
) -> PrescriptionRead:
    """Sign as the prescriber of record, with a fresh step-up, through the safety gate."""
    _authorize(actor, PRESCRIPTION_PERMISSIONS["sign"], action=service.SIGN)
    result = service.sign(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        prescription_id=prescription_id,
        step_up_token=body.step_up_token,
    )
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.post(
    "/{prescription_id}/dispatch",
    response_model=PrescriptionRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(prescription_write_rate_limit)],
    responses={
        status.HTTP_200_OK: {
            "model": PrescriptionRead,
            "description": "A replay of an earlier `Idempotency-Key`: nothing changed.",
        }
    },
)
def dispatch_prescription(
    *,
    actor: ActorDep,
    prescription_id: uuid.UUID,
    body: PrescriptionDispatch,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PrescriptionRead:
    """Re-run the gate and queue the prescription in the outbox. **Nothing is sent from here.**"""
    _authorize(actor, PRESCRIPTION_PERMISSIONS["dispatch"], action=service.DISPATCH)
    key = (idempotency_key or "").strip()
    if not key or len(key) > _KEY_MAX or not key.isprintable():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": service.IDEMPOTENCY_KEY_REQUIRED,
                "message": "Send a printable Idempotency-Key header of at most 255 characters",
            },
        )
    result = service.dispatch(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        prescription_id=prescription_id,
        step_up_token=body.step_up_token,
        client_key=key,
    )
    if isinstance(result, Refusal):
        _raise(result)
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return result.prescription
