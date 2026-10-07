"""The tenancy HTTP API — `GET` and `PATCH /api/v1/tenants/current`.

Design: `docs/features/01-tenancy-and-clinics/03-design.md`, "Endpoints" (the two rows this module owns)
and "Deny-by-default request path". Requirements: `01-requirements.md` R1, R9, R12, R15;
user stories US-1 and US-2 in `02-user-stories.md`.

The path is the design's: `GET /api/v1/tenants/current` and `PATCH /api/v1/tenants/current`, under the
`/api/v1` prefix D-005 fixes (`01-requirements.md` OPEN-3 records the PRD's `/admin/clinics` shape as
the alternative; the design's shape is the one implemented here).

**The tenant is resolved, never supplied (INV-1).** The actor is built by `app.api.deps.get_actor` from
the session row and nothing else. Nothing in this module reads a tenant identifier from a path, body,
query string or header: the path is literally `/current`, and `TenantSettingsUpdate` forbids unknown
fields, so a body `tenant_id` is a `422` decided by the validation layer. A query parameter or header
naming another tenant is simply never read — US-5's stated acceptance is that such a request returns the
caller's own data or `404`, never another tenant's.

**Cross-tenant access is `404`, never `403`** throughout the platform; these two routes expose no
resource identifier at all, so the boundary cannot be probed through them.

**Audit is deferred.** `05-data-and-audit.md` names `tenant.viewed` for a tenant read,
`tenant.config_changed` for a security-setting change, and `TENANT_CROSS_ACCESS_ATTEMPT` for a dropped
client-supplied tenant value. Feature 04 (the append-only audit writer, same transaction, fail-closed) is
being built in parallel and is not on this branch, so no event is written and INVENTING A SECOND WRITER
was not an option: a second writer would be a second audit path, which is exactly what INV-4 forbids.
The names above are the ones the writer must use when it lands.

**No `tenant_settings` table is created.** `05-data-and-audit.md` mentions `tenant_settings` once, in a
retention sentence; no document gives it a column set, a key, a classification or an owner, and the
retention position for it is **REQUIRES LEGAL/REGULATORY VALIDATION**. Inventing the table would put an
unclassified store under a route whose write path is already blocked (below).

## Deny-by-default request path, as implemented

1. Authenticate the session — `401` if missing or expired (`app.api.deps.get_current_user`).
2. Resolve the tenant from the session — an authenticated account with no organisation is refused `403
   NO_ORGANISATION` before any query (`app.api.deps.get_actor`).
3. Authorise through the central policy layer: `tenant:read` for the read, `tenant:configure` for the
   change. A caller without it is refused `403 PERMISSION_NOT_HELD`.
4. Validate the body against the strict schema: an unknown field — including `tenant_id` — is `422`.
5. Execute inside a tenant-scoped transaction (`app.core.db.tenant_transaction`), which sets
   `app.tenant_id` with `SET LOCAL` and refuses to open without a tenant.
6. Audit the decision, including the refusal — **deferred** to feature 04, see above.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

#### `GET /api/v1/tenants/current`
- Authentication: Yes
- Permission: `tenant:read` — the code `03-design.md` "Endpoints" names, added to the catalogue under
  OPEN-2 and granted to `PRACTICE_OWNER` (US-1) and `COMPLIANCE_AUDITOR` (US-7)
- Tenant scope: session only — no tenant in the path, and no tenant identifier is read from anywhere else
- Ownership rule: the response is the caller's own tenant row; there is no other row this route can reach
- Input schema: none — no path parameter, no query parameter, no body
- Output schema: `TenantCurrentRead` — `id`, `slug`, `status`, `data_region`, `created_at`, `updated_at`;
  `retention_profile` and `legal_name` are never returned (US-1; the application role holds no `SELECT`
  on either column)
- Audit: deferred — feature 04 is not built; `05-data-and-audit.md` names `tenant.viewed`
- Rate limit: 300/min per session - the single-resource read class R15 sets ("single-resource reads to
  300/min"). Until 2026-10-07 this read was in the administrative class (20/min); the app shell reads
  it on every page load, so it spent the administrative budget before an administrator opened the
  administration screen. The read is still limited; only its class changed. A request without a
  verified session is counted per client address (`app/core/rate_limit.py`)
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, or no organisation on the account),
  `404` (the session's tenant row is absent — unreachable while the account's foreign key holds), `429`;
  fails closed = yes
- Step-up: no

#### `PATCH /api/v1/tenants/current`
- Authentication: Yes
- Permission: `tenant:configure` — one of the fixed 19, held by `PRACTICE_OWNER` only
- Tenant scope: session only, as above
- Ownership rule: the change could only ever apply to the caller's own tenant; there is no identifier to forge
- Input schema: `TenantSettingsUpdate` — an **empty** strict model, so every field is unknown and a body
  `tenant_id` (or any setting) is `422` before the route decides anything
- Output schema: none — see the refusal below
- Audit: deferred — feature 04 is not built; `05-data-and-audit.md` names `tenant.config_changed` with
  `result = DENIED` for the refusal that is the only outcome today
- Rate limit: 20/min per session, administrative class (R15)
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, `STEP_UP_REQUIRED`, or no organisation),
  `422` (unknown body field); fails closed = yes
- Step-up: **required by the design and unimplemented — blocked by D-003.** The design requires a fresh,
  5-minute, single-use step-up for this route (R12), and feature 02's step-up mechanism is not built. The
  route therefore refuses every caller who holds the permission with `403 STEP_UP_REQUIRED` and writes
  nothing. R12's first half — *"`PATCH` without a fresh factor is refused `403`"* — is enforced; its
  second half (*"after step-up the change is versioned with actor and timestamp"*) cannot be built until
  the factor exists, and no security setting is named anywhere for it to change. This is a deliberate,
  reported gap: a success path invented here would be a tenant-configuration write with no step-up, no
  named setting and no audit writer.

`PATCH` is also refused for a caller without `tenant:configure` — the permission check runs first, so an
`ADMINISTRATOR` (who holds `users:manage` but not `tenant:configure`) receives `PERMISSION_NOT_HELD`
rather than the step-up refusal, exactly as the `users:manage` boundary is documented in feature 03.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import ActorDep
from app.core.db import tenant_transaction
from app.core.rate_limit import admin_rate_limit, read_rate_limit
from app.modules.identity_tenancy.models import Tenant
from app.modules.identity_tenancy.schemas import (
    TenantCurrentRead,
    TenantSettingsUpdate,
)
from app.modules.users_roles.catalog import TENANCY_PERMISSIONS
from app.modules.users_roles.service import authorize

# R15: a change under `/api/v1/tenants/*` is the administrative class (20/min); a single-resource
# read is the read class (300/min). Each route declares its class as a route dependency, which runs
# before the endpoint's own authentication and authorisation, so an unauthenticated flood is bounded
# on both.
router = APIRouter(prefix="/tenants", tags=["tenants"])

# R12's refusal reason. `01-tenancy-and-clinics/03-design.md` requires the step-up and does not name a
# code; `03-users-and-roles/05-data-and-audit.md` lists `STEP_UP_REQUIRED` among the denial reason codes,
# so that is the spelling used here rather than a new one. (`05-patients/01-requirements.md` writes
# `AUTH_STEP_UP_REQUIRED` for a *missing* step-up answered `401`; feature 01 answers `403`, and the
# conflict between the two statuses is recorded rather than resolved by picking a code that fits one.)
STEP_UP_REQUIRED = "STEP_UP_REQUIRED"

_NOT_FOUND = "NOT_FOUND"


def _tenant_not_found() -> HTTPException:
    """One answer for an absent tenant row, with a stable code and no internal detail."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": _NOT_FOUND, "message": "Tenant not found"},
    )


def _current_tenant(*, tenant_id: uuid.UUID) -> TenantCurrentRead | None:
    """The caller's own tenant row, selecting only the columns `clinos_app` may read.

    The query is column-limited on purpose. `03-design.md` "Database privileges" grants the application
    role `SELECT (id, slug, status, data_region)` on `tenants` and withholds `retention_profile` and
    `legal_name`; loading the ORM entity would select every column and would fail with `permission
    denied for column` the day the application connects as `clinos_app` instead of as the table owner.

    `tenants` is global (no RLS), so the explicit `id` predicate is the whole scope; the tenant-scoped
    transaction is still used, because the rule is "every query against tenant data goes through the
    helper" and because it fails closed with no context.
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        # The statement names its six columns explicitly, through the table rather than the model's
        # class attributes: SQLModel types a class attribute as its *declared* type (`uuid.UUID`), so
        # `select(Tenant.id, ...)` is not a typed column select, and `load_only` needs mapped
        # attributes rather than names. Naming the columns is the control, not a detail — the
        # application role holds `SELECT` on exactly these, and an ORM entity select would ask for
        # `retention_profile` and `legal_name` too and fail with `permission denied for column` the
        # day the application connects as `clinos_app` instead of as the table owner.
        # `Tenant.metadata.tables` rather than `Tenant.__table__`: SQLModel's base class does not
        # declare `__table__` in its type stubs, while `metadata` is declared, so this is the spelling
        # that type-checks and still yields the same `Table`.
        table = Tenant.metadata.tables["tenants"]
        statement = select(
            table.c.id,
            table.c.slug,
            table.c.status,
            table.c.data_region,
            table.c.created_at,
            table.c.updated_at,
        ).where(table.c.id == tenant_id)
        # `connection().execute`, not `session.exec`: `session.exec` is typed for a single-entity
        # scalar select (`Select[_TSelectParam]`), `session.execute` is the shim SQLModel deprecates,
        # and a Core select executed on the session's connection is the same transaction without
        # either caveat — `app/core/db.py` uses the connection the same way.
        row = session.connection().execute(statement).one_or_none()
        if row is None:
            return None
        return TenantCurrentRead(
            id=row[0],
            slug=row[1],
            status=row[2],
            data_region=row[3],
            created_at=row[4],
            updated_at=row[5],
        )


@router.get(
    "/current",
    response_model=TenantCurrentRead,
    dependencies=[Depends(read_rate_limit)],
)
def read_current_tenant(*, actor: ActorDep) -> TenantCurrentRead:
    """Return the caller's own tenant. `retention_profile` is never part of the answer (US-1)."""
    authorize(actor, TENANCY_PERMISSIONS["read"])
    tenant = _current_tenant(tenant_id=actor.tenant_id)
    if tenant is None:
        raise _tenant_not_found()
    return tenant


@router.patch(
    "/current",
    dependencies=[Depends(admin_rate_limit)],
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": (
                "Refused. `PERMISSION_NOT_HELD` when the caller does not hold `tenant:configure`; "
                "`STEP_UP_REQUIRED` for a caller who does, because the step-up control this route "
                "requires is not built (feature 02, blocked by D-003). Nothing is written."
            )
        }
    },
)
def update_current_tenant(
    *, actor: ActorDep, _settings_in: TenantSettingsUpdate
) -> None:
    """Refuse a tenant security-setting change: the required step-up control is not built (R12).

    The body has already been validated by the time this runs — `TenantSettingsUpdate` declares no
    field and forbids extras, so a body `tenant_id` or any other name is a `422` from the validation
    layer and never reaches this function. What remains is the authorisation decision and the refusal
    that the missing step-up forces; the declaration on this module records why no success path exists
    and what the writer must emit when it does.
    """
    authorize(actor, TENANCY_PERMISSIONS["configure"])
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": STEP_UP_REQUIRED,
            "message": (
                "Changing a tenant security setting requires a fresh step-up, which is not "
                "available yet; nothing was changed."
            ),
        },
    )
