"""The prescriptions HTTP API - the routes agreed in `docs2/sdlc/07-script-queue/api.md`, the
prescriber list the staging form needs, and (Milestone 4, decision D-010) the single read, the history,
the draft edit, the cancellation and the addendum.

The request path is the designs' (`11-prescribing/03-design.md` "Deny-by-default request path"):
authenticate -> resolve the tenant from the session (`app.api.deps.get_actor`) -> authorise through the
central policy layer -> **audit the refusal** -> validate the strict body -> execute in the
tenant-scoped transaction, where the service audits every decision it takes.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

| Method and path | Permission | Step-up | Audit | Rate |
| --- | --- | --- | --- | --- |
| `GET /api/v1/prescriptions` | `prescription:read` | no | `prescription.read` once per page (T1-34) | 300/min |
| `GET /api/v1/prescriptions/{id}` | `prescription:read` + care relationship | no | `prescription.read` | 300/min |
| `GET /api/v1/prescriptions/{id}/history` | `prescription:read` + care relationship | no | `prescription.read` (`query_filters: ["history"]`) | 300/min |
| `PATCH /api/v1/prescriptions/{id}` | `prescription:modify` + drafter or prescriber + care relationship; `DRAFT` only | no | `prescription.modify` (`changed_fields`) | 30/min |
| `POST /api/v1/prescriptions/{id}/cancel` | `prescription:modify` + drafter or prescriber + care relationship; `DRAFT`, `SIGNED`, `BLOCKED`, `FAILED` | no | `prescription.reject` (`reason` = the code) | 30/min |
| `POST /api/v1/prescriptions/{id}/addendum` | `prescription:sign` + prescriber of record + care relationship; `SIGNED`, `BLOCKED`, `FAILED`; `Idempotency-Key` | no (the new version is signed with step-up) | `prescription.modify` on the new version (`supersedes_id`), `prescription.reject` on the original | 30/min |
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

`PATCH` edits a `DRAFT` only (`409` otherwise); a signed script is corrected by an addendum, which
creates a new `DRAFT` version and retires the original (`CANCELLED`, `SUPERSEDED_BY_ADDENDUM`) in one
transaction, so one live version exists. No `DELETE`, and no `state` anywhere in a request (FEAT-11
R7, R14).
"""

import uuid
from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.api.deps import ActorDep
from app.core.rate_limit import prescription_write_rate_limit, read_rate_limit
from app.modules.prescriptions import service
from app.modules.prescriptions.schemas import (
    PrescribersPublic,
    PrescriptionAddendum,
    PrescriptionCancel,
    PrescriptionCreate,
    PrescriptionDispatch,
    PrescriptionHistory,
    PrescriptionRead,
    PrescriptionSign,
    PrescriptionsPublic,
    PrescriptionUpdate,
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


def _intent_key(idempotency_key: str | None) -> str:
    """The client's intent key, printable and bounded, or `422 IDEMPOTENCY_KEY_REQUIRED`."""
    key = (idempotency_key or "").strip()
    if not key or len(key) > _KEY_MAX or not key.isprintable():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": service.IDEMPOTENCY_KEY_REQUIRED,
                "message": "Send a printable Idempotency-Key header of at most 255 characters",
            },
        )
    return key


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
    _authorize(actor, PRESCRIPTION_PERMISSIONS["read"], action=service.READ)
    try:
        result = service.list_prescriptions(
            actor=actor,
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
    if result.decision is not None:
        # The treating-relationship refusal for a patient's scripts, already audited (T1-34).
        enforce(result.decision)
    assert result.page is not None, "a page is returned whenever nothing refused it"
    return result.page


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
    result = service.stage(actor=actor, body=body)
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
    key = _intent_key(idempotency_key)
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


@router.get(
    "/{prescription_id}",
    response_model=PrescriptionRead,
    dependencies=[Depends(read_rate_limit)],
)
def read_prescription(
    *, actor: ActorDep, prescription_id: uuid.UUID
) -> PrescriptionRead:
    """One prescription. Another tenant's is `404`; one whose patient you are not treating, `403`."""
    _authorize(actor, PRESCRIPTION_PERMISSIONS["read"], action=service.READ)
    result = service.read_one(actor=actor, prescription_id=prescription_id)
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.get(
    "/{prescription_id}/history",
    response_model=PrescriptionHistory,
    dependencies=[Depends(read_rate_limit)],
)
def read_prescription_history(
    *, actor: ActorDep, prescription_id: uuid.UUID
) -> PrescriptionHistory:
    """Every transition of one prescription, oldest first, with who made it and the reason code."""
    _authorize(actor, PRESCRIPTION_PERMISSIONS["read"], action=service.READ)
    result = service.history(actor=actor, prescription_id=prescription_id)
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.patch(
    "/{prescription_id}",
    response_model=PrescriptionRead,
    dependencies=[Depends(prescription_write_rate_limit)],
)
def update_prescription(
    *, actor: ActorDep, prescription_id: uuid.UUID, body: PrescriptionUpdate
) -> PrescriptionRead:
    """Correct a `DRAFT`. Signed and later scripts are `409`: correct those by addendum."""
    _authorize(actor, PRESCRIPTION_PERMISSIONS["modify"], action=service.MODIFY)
    result = service.modify(actor=actor, prescription_id=prescription_id, body=body)
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.post(
    "/{prescription_id}/cancel",
    response_model=PrescriptionRead,
    dependencies=[Depends(prescription_write_rate_limit)],
)
def cancel_prescription(
    *, actor: ActorDep, prescription_id: uuid.UUID, body: PrescriptionCancel
) -> PrescriptionRead:
    """Cancel before dispatch, with a reason code. Queued, sent or terminal scripts are `409`."""
    _authorize(actor, PRESCRIPTION_PERMISSIONS["modify"], action=service.REJECT)
    result = service.cancel(
        actor=actor, prescription_id=prescription_id, reason_code=body.reason_code
    )
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.post(
    "/{prescription_id}/addendum",
    response_model=PrescriptionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(prescription_write_rate_limit)],
    responses={
        status.HTTP_200_OK: {
            "model": PrescriptionRead,
            "description": "A replay of an earlier `Idempotency-Key`: the same addendum, unchanged.",
        }
    },
)
def amend_prescription(
    *,
    actor: ActorDep,
    prescription_id: uuid.UUID,
    body: PrescriptionAddendum,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PrescriptionRead:
    """Correct a signed, unsent script by a new `DRAFT` version; the original is retired, unchanged."""
    _authorize(actor, PRESCRIPTION_PERMISSIONS["amend"], action=service.MODIFY)
    key = _intent_key(idempotency_key)
    result = service.addendum(
        actor=actor, prescription_id=prescription_id, body=body, client_key=key
    )
    if isinstance(result, Refusal):
        _raise(result)
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return result.prescription
