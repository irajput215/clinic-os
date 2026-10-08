"""The dashboard HTTP API: `GET /api/v1/dashboard/today`.

Contract: `docs2/sdlc/08-today/api.md` (built 2026-10-08, Milestone 2 phase 2E). The request path
every module follows: authenticate -> resolve the tenant from the session (`get_actor`, INV-1) ->
authorise each section through the central policy layer -> execute in one tenant transaction
(`service.today`).

## Endpoint declaration (`docs/reference/definition-of-done.md` section 4)

| Method and path | Auth | Permission | Tenant scope | Input | Output | Audit | Rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `GET /dashboard/today` | yes | per section: `patient:read`, `prescription:read`, `tga_approval:read` | session | none | `TodaySummary` | `tga_approval.read` when the approvals section is read | 300/min |

A section whose permission the caller does not hold is withheld (`null`, and named in `withheld`),
not refused: the page is everyone's landing screen, and a receptionist without `prescription:read`
still needs today's schedule. An inactive account is refused outright (`403`), like every route.
A `tenant_id` query parameter is ignored; when the approvals section is read it is written down on
that section's audit event as `CLIENT_TENANT_ID_IGNORED`.
"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import ActorDep
from app.core.rate_limit import read_rate_limit
from app.modules.dashboard import service
from app.modules.dashboard.schemas import DashboardSection, TodaySummary
from app.modules.users_roles.catalog import DASHBOARD_SECTION_PERMISSIONS
from app.modules.users_roles.policy import DecisionCode, can, enforce

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/today", response_model=TodaySummary, dependencies=[Depends(read_rate_limit)]
)
def read_today(*, actor: ActorDep, request: Request) -> TodaySummary:
    """Today's schedule, the script queue and the approvals needing action, in one read."""
    readable: list[DashboardSection] = []
    for section in service.SECTIONS:
        decision = can(actor, DASHBOARD_SECTION_PERMISSIONS[section])
        if decision.allowed:
            readable.append(section)
        elif decision.code is not DecisionCode.PERMISSION_NOT_HELD:
            # Not a missing permission but a refused identity: the whole request is refused.
            enforce(decision)
    return service.today(
        actor=actor,
        readable=readable,
        client_tenant_id_supplied="tenant_id" in request.query_params,
    )
