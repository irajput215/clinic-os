"""Platform probes.

Thin HTTP layer only: the decision lives in `app.core.health`. This router is declared with no
authentication, no permission, no tenant scope and no audit event, because a probe is one of the two
surfaces the endpoint declaration standard permits to be unauthenticated
([`definition-of-done.md` §4](../../../../docs/reference/definition-of-done.md)) — it must be callable
by an orchestrator or a deploy pipeline that holds no session.

**The path is repo-chosen and OPEN**
([`16-operations-and-observability/03-design.md`](../../../../docs/features/16-operations-and-observability/03-design.md)
§"Deny-by-default request path"). It is versioned under `/api/v1` like every other route so a probe
can never outlive the API surface it reports on.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.health import database_is_ready

router = APIRouter(prefix="/health", tags=["health"])

# Declared explicitly so the generated client and the OpenAPI document both record the contract:
# a boolean, never an object. An object invites a later "helpful" field and a leak with it.
_BOOLEAN = {"application/json": {"schema": {"type": "boolean"}}}


@router.get(
    "/ready/",
    summary="Readiness probe",
    response_class=JSONResponse,
    responses={
        200: {"description": "The process can serve requests.", "content": _BOOLEAN},
        503: {
            "description": "The process cannot reach its database.",
            "content": _BOOLEAN,
        },
    },
)
def readiness() -> JSONResponse:
    """Report whether this process can reach its database.

    Unauthenticated by design and therefore returns **no more than a boolean** — no version, no
    dependency list, no error detail, no tenant data. A deploy pipeline polls this to decide whether
    a release actually works; a non-200 means the app is up but cannot serve, which is exactly the
    failure a liveness probe cannot see.
    """
    if not database_is_ready():
        return JSONResponse(status_code=503, content=False)
    return JSONResponse(status_code=200, content=True)
