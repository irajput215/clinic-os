"""SOP routes (docs3 feature 02, manual §13). Tenant from the session (INV-1); `404` across tenants
and for an SOP that does not apply to the caller."""

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import ActorDep
from app.core.rate_limit import admin_rate_limit, read_rate_limit
from app.modules.sops import service
from app.modules.sops.schemas import AcknowledgementMatrix, SopCard, SopDetail, SopWrite
from app.modules.users_roles.service import authorize

router = APIRouter(prefix="/sops", tags=["sops"])


def _raise(refused: service.SopRefused) -> NoReturn:
    raise HTTPException(
        status_code=refused.status_code,
        detail={"code": refused.code, "message": refused.message},
    )


@router.get("", response_model=list[SopCard], dependencies=[Depends(read_rate_limit)])
def list_sops(*, actor: ActorDep) -> list[SopCard]:
    """The SOPs that apply to the caller (every SOP for `tenant:configure`)."""
    return service.list_sops(actor=actor)


@router.get(
    "/matrix",
    response_model=AcknowledgementMatrix,
    dependencies=[Depends(read_rate_limit)],
)
def acknowledgement_matrix(*, actor: ActorDep) -> AcknowledgementMatrix:
    """Staff x SOP x acknowledged version: `tenant:configure` or `audit:read` (R8)."""
    if service.CONFIGURE not in actor.permissions:
        authorize(actor, service.AUDIT_READ)
    return service.matrix(actor=actor)


@router.get(
    "/{sop_id}", response_model=SopDetail, dependencies=[Depends(read_rate_limit)]
)
def read_sop(*, actor: ActorDep, sop_id: uuid.UUID) -> SopDetail:
    try:
        return service.read_sop(actor=actor, sop_id=sop_id)
    except service.SopRefused as refused:
        _raise(refused)


@router.post(
    "",
    response_model=SopDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(admin_rate_limit)],
)
def create_sop(*, actor: ActorDep, body: SopWrite) -> SopDetail:
    """Publish a new SOP as version 1 (`tenant:configure`)."""
    authorize(actor, service.CONFIGURE)
    return service.create_sop(actor=actor, body=body)


@router.post(
    "/{sop_id}/versions",
    response_model=SopDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(admin_rate_limit)],
)
def publish_version(*, actor: ActorDep, sop_id: uuid.UUID, body: SopWrite) -> SopDetail:
    """Publish the next version; everyone it applies to must acknowledge again."""
    authorize(actor, service.CONFIGURE)
    try:
        return service.publish_version(actor=actor, sop_id=sop_id, body=body)
    except service.SopRefused as refused:
        _raise(refused)


@router.post(
    "/{sop_id}/versions/{version}/acknowledge",
    response_model=SopCard,
    dependencies=[Depends(admin_rate_limit)],
)
def acknowledge(*, actor: ActorDep, sop_id: uuid.UUID, version: int) -> SopCard:
    """Acknowledge the current version. Idempotent; `409 NOT_CURRENT_VERSION` for an older one."""
    try:
        return service.acknowledge(actor=actor, sop_id=sop_id, version=version)
    except service.SopRefused as refused:
        _raise(refused)
