"""Practice settings and the setup checklist (docs3 feature 01), under `/tenants/current`.

Tenant from the session (INV-1); nothing here takes a tenant id.
"""

from fastapi import APIRouter, Depends

from app.api.deps import ActorDep
from app.core.rate_limit import admin_rate_limit, read_rate_limit
from app.modules.practice import service
from app.modules.practice.schemas import (
    PracticeSettingsRead,
    PracticeSettingsUpdate,
    SetupRead,
)
from app.modules.users_roles.service import authorize

router = APIRouter(prefix="/tenants/current", tags=["tenants"])

CONFIGURE = "tenant:configure"
READ = "tenant:read"


@router.get("/setup", response_model=SetupRead, dependencies=[Depends(read_rate_limit)])
def read_setup(*, actor: ActorDep) -> SetupRead:
    """The clinic setup checklist for whoever configures the practice (`tenant:configure`)."""
    authorize(actor, CONFIGURE)
    return service.setup(actor=actor)


@router.get(
    "/settings",
    response_model=PracticeSettingsRead,
    dependencies=[Depends(read_rate_limit)],
)
def read_settings(*, actor: ActorDep) -> PracticeSettingsRead:
    """The practice settings (`tenant:read`); the defaults when none were saved."""
    authorize(actor, READ)
    return service.read_settings(actor=actor)


@router.patch(
    "/settings",
    response_model=PracticeSettingsRead,
    dependencies=[Depends(admin_rate_limit)],
)
def update_settings(
    *, actor: ActorDep, body: PracticeSettingsUpdate
) -> PracticeSettingsRead:
    """Save who may stage drafts and how long adult records are kept (`tenant:configure`).
    Audited `tenant.config_changed` with the names of the fields that changed."""
    authorize(actor, CONFIGURE)
    return service.update_settings(actor=actor, body=body)
