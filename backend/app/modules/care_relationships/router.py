"""The care team of a patient: the interim upkeep of `care_relationships` (decision D-007).

The source of truth for care relationships is OPEN (open-questions.md C13). Until it is decided, a
relationship exists only because a person recorded it, and these three routes are how: list the active
relationships, record one, end one. Contract: `docs2/sdlc/02-patients/api.md`, "Care team".

Who may call them: an actor holding `patient:update` **unconditionally** - through a grant the matrix
does not mark `cr` (practice owner, authorised prescriber, administrator). A doctor or nurse whose
access to the patient is itself relationship-bound is refused `403 PERMISSION_NOT_HELD`, so nobody can
record a relationship that grants themselves access. The refusal is audited.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

#### `GET /api/v1/patients/{patient_id}/care-relationships`
- Authentication: Yes · Permission: `patient:update`, unconditional · Tenant scope: both
- Ownership rule: the patient must be the caller's own, else `404`
- Output schema: `CareTeamPublic` (active relationships, oldest first)
- Audit: `patient.read` with `query_filters: ["care_team"]`, `result_count`, `purpose`; refusals `DENIED`
- Rate limit: 300/min (the single-resource read class) · Errors: `401`, `403`, `404`, `422` · Step-up: no

#### `POST /api/v1/patients/{patient_id}/care-relationships`
- Authentication: Yes · Permission: `patient:update`, unconditional · Tenant scope: both
- Input schema: `CareRelationshipCreate` (`practitioner_id`; unknown fields `422`)
- Output schema: `CareTeamPublic` (`201`)
- Audit: `care_relationship.create` on the same transaction (`care_relationship_id`, `target_user_id`,
  `source`); refusals `DENIED` with the reason code
- Rate limit: 20/min per session (the administrative class: this grants access, T-03.11)
- Errors: `401`, `403`, `404` (patient), `409 ALREADY_IN_CARE_TEAM`, `422 PRACTITIONER_NOT_FOUND`
- Step-up: no (D-007 records it as a candidate for the step-up list)

#### `POST /api/v1/patients/{patient_id}/care-relationships/{care_relationship_id}/end`
- As above; sets `active_to = now()` (the row is never deleted); audit `care_relationship.end`
- Errors: `401`, `403`, `404 RELATIONSHIP_NOT_FOUND` (absent, ended, or another tenant's)
"""

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import ActorDep
from app.core.rate_limit import admin_rate_limit, read_rate_limit
from app.modules.care_relationships import service
from app.modules.care_relationships.schemas import (
    CareRelationshipCreate,
    CareTeamPublic,
)
from app.modules.users_roles.catalog import PATIENT_PERMISSIONS
from app.modules.users_roles.policy import Actor, DecisionCode, can

router = APIRouter(prefix="/patients", tags=["care-relationships"])

_MANAGE = PATIENT_PERMISSIONS["update"]


def _client(request: Request) -> str | None:
    return None if request.client is None else request.client.host


def _raise(refusal: service.Refusal) -> NoReturn:
    raise HTTPException(
        status_code=refusal.status_code,
        detail={"code": refusal.code, "message": refusal.message},
    )


def _authorise(
    actor: Actor, *, action: str, patient_id: uuid.UUID, source_ip: str | None
) -> None:
    """`patient:update`, held through a grant that is not itself relationship-bound; audited."""
    decision = can(actor, _MANAGE)
    if decision.allowed and actor.relationship_bound(_MANAGE):
        refusal = service.Refusal(
            403,
            DecisionCode.PERMISSION_NOT_HELD.value,
            "Your role cannot change a patient's care team",
        )
    elif not decision.allowed:
        refusal = service.Refusal(
            decision.status_code, decision.code.value, decision.message
        )
    else:
        return
    service.record_denial(
        actor=actor,
        action=action,
        patient_id=patient_id,
        reason=refusal.code,
        source_ip=source_ip,
    )
    _raise(refusal)


@router.get(
    "/{patient_id}/care-relationships",
    response_model=CareTeamPublic,
    dependencies=[Depends(read_rate_limit)],
)
def list_care_team(
    *, actor: ActorDep, request: Request, patient_id: uuid.UUID
) -> CareTeamPublic:
    """The patient's active care relationships, oldest first."""
    source_ip = _client(request)
    _authorise(
        actor, action=service.PATIENT_READ, patient_id=patient_id, source_ip=source_ip
    )
    result = service.list_care_team(
        actor=actor, patient_id=patient_id, source_ip=source_ip
    )
    if isinstance(result, service.Refusal):
        _raise(result)
    return result


@router.post(
    "/{patient_id}/care-relationships",
    response_model=CareTeamPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(admin_rate_limit)],
)
def record_care_relationship(
    *,
    actor: ActorDep,
    request: Request,
    patient_id: uuid.UUID,
    body: CareRelationshipCreate,
) -> CareTeamPublic:
    """Add a practitioner to the patient's care team: an active relationship from now."""
    source_ip = _client(request)
    _authorise(
        actor,
        action=service.CARE_RELATIONSHIP_CREATE,
        patient_id=patient_id,
        source_ip=source_ip,
    )
    result = service.record_relationship(
        actor=actor,
        patient_id=patient_id,
        practitioner_id=body.practitioner_id,
        source_ip=source_ip,
    )
    if isinstance(result, service.Refusal):
        _raise(result)
    return result


@router.post(
    "/{patient_id}/care-relationships/{care_relationship_id}/end",
    response_model=CareTeamPublic,
    dependencies=[Depends(admin_rate_limit)],
)
def end_care_relationship(
    *,
    actor: ActorDep,
    request: Request,
    patient_id: uuid.UUID,
    care_relationship_id: uuid.UUID,
) -> CareTeamPublic:
    """End an active relationship now. The record stays, ended."""
    source_ip = _client(request)
    _authorise(
        actor,
        action=service.CARE_RELATIONSHIP_END,
        patient_id=patient_id,
        source_ip=source_ip,
    )
    result = service.end_relationship(
        actor=actor,
        patient_id=patient_id,
        care_relationship_id=care_relationship_id,
        source_ip=source_ip,
    )
    if isinstance(result, service.Refusal):
        _raise(result)
    return result
