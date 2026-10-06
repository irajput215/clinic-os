"""The audit read API: `GET /api/v1/audit/events`, keyset-paginated and itself audited.

Design: `docs/features/04-audit-log/03-design.md` §"Endpoints" and §"Deny-by-default request path".
Requirements: R12 (tenant-scoped, filtered, keyset-paginated read; the read is itself audited), S1,
S2, S5, S6, S7, S8.

Order of the request path, exactly as the design fixes it: authenticate the session → resolve the
tenant from the session → check `audit:read` through the central policy layer → validate the filters
strictly → read inside the RLS transaction and write `audit.read` on the same one.

**The tenant is resolved, never supplied (INV-1).** The actor is built by `app.api.deps.get_actor`
from the session row and nothing else. No query parameter can carry a tenant identifier: the filters
are declared explicitly, a `tenant_id` query value is simply never read, and the read runs under the
forced RLS policy for the tenant the session resolved.

**Cross-tenant is `404`, never `403`** — a `403` confirms the record exists (S2). The service answers
`None` for "absent" and "another tenant's" alike, so the two are indistinguishable to the caller. The
refusal is audited as `audit.read` with `result = DENIED`, because an attempt to read another tenant's
trail is exactly the event the trail exists to hold (US-6).

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

#### `GET /api/v1/audit/events`
- Authentication: Yes
- Permission: `audit:read`
- Tenant scope: session
- Ownership rule: every returned event's `tenant_id` equals the session's tenant; another tenant's
  events are absent, not denied
- Input schema: the query parameters below — `limit` bounded `1..200` (default 50), an opaque
  `cursor`, and at least one of `action`, `actor_id`, `resource_type`, `resource_id`, `result`,
  `from`, `to`; an unfiltered scan is `422`
- Output schema: `AuditEventsPublic`
- Audit: `audit.read` on every call, including an empty result, with `query_filters` and
  `result_count` — written in the same transaction as the read
- Rate limit: deferred — the design names 60/min per actor (OPEN-6), and the in-process limiter keys
  on the client address, which is not the actor; reported rather than half-implemented
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, or no organisation on the account),
  `422` (an unfiltered scan, a range wider than 90 days, an unknown `result`, a malformed cursor);
  fails closed = yes
- Step-up: no

#### `GET /api/v1/audit/events/{event_id}`
- Authentication: Yes
- Permission: `audit:read`
- Tenant scope: both — the session resolves the tenant, the event is matched against it
- Ownership rule: the event is returned only when its `tenant_id` equals the session's tenant;
  otherwise `404` with no body fields, and the refusal is audited
- Input schema: none — `event_id` is a UUID path parameter
- Output schema: `AuditEventRead`
- Audit: `audit.read` on every call, including the `404`
- Rate limit: deferred, as above
- Errors: `401`, `403`, `404` (absent or another tenant's), `422` (malformed UUID); fails closed = yes
- Step-up: no

Out of scope for this slice, and why:

- **`POST /api/v1/audit/export`.** The export function and its manifest are implemented and tested;
  the S3 Object Lock delivery is not wired (no bucket, no credentials, and `boto3` is a new
  dependency), and a route returning a presigned URL would be claiming a control that does not exist.
  Recorded as a gap in the PR.
- **Rate limiting (OPEN-6).** The constant is not agreed, and the existing limiter keys on the client
  address rather than the actor.
- **`GET /api/v1/audit`** — the design's own path — is served as an alias on the same handler, so both
  the feature document's path and the `/events` name the delivery contract uses are live and cannot
  drift apart.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import ActorDep
from app.core.db import tenant_transaction
from app.modules.audit import service
from app.modules.audit.schemas import (
    DEFAULT_PAGE_SIZE,
    MAX_CURSOR_LENGTH,
    MAX_PAGE_SIZE,
    RESULT_VALUES,
    AuditEventRead,
    AuditEventsPublic,
)
from app.modules.users_roles.catalog import AUDIT_READ_PERMISSION
from app.modules.users_roles.service import authorize

router = APIRouter(prefix="/audit", tags=["audit"])


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail
    )


def audit_filters(
    action: str | None = Query(default=None, max_length=128),
    actor_id: uuid.UUID | None = Query(default=None),
    resource_type: str | None = Query(default=None, max_length=32),
    resource_id: uuid.UUID | None = Query(default=None),
    result: str | None = Query(default=None),
    from_timestamp: datetime | None = Query(default=None, alias="from"),
    to_timestamp: datetime | None = Query(default=None, alias="to"),
) -> service.AuditFilters:
    """Build and validate the filter set, refusing an unbounded scan.

    Declared as explicit query parameters so the OpenAPI document lists each filter by name (which is
    what the generated SDK is built from), and so an unknown query parameter is simply never read —
    there is no path by which a client could supply a `tenant_id` (INV-1).

    A half-supplied window is closed at 90 days by `service.bounded_window` rather than left open: a
    single `from` with no `to` is unbounded in the one direction that matters.
    """
    supplied = (
        action,
        actor_id,
        resource_type,
        resource_id,
        result,
        from_timestamp,
        to_timestamp,
    )
    if all(value is None for value in supplied):
        raise _unprocessable(
            "at least one filter is required; an unfiltered audit scan is refused (R12)"
        )
    if result is not None and result not in RESULT_VALUES:
        raise _unprocessable(f"result must be one of: {', '.join(RESULT_VALUES)}")
    try:
        service.validate_window(
            from_timestamp=from_timestamp, to_timestamp=to_timestamp
        )
    except service.InvalidRange as error:
        raise _unprocessable(str(error)) from error
    window_start, window_end = service.bounded_window(
        from_timestamp=from_timestamp, to_timestamp=to_timestamp
    )
    return service.AuditFilters(
        action=action,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        from_timestamp=window_start,
        to_timestamp=window_end,
    )


def _client_ip(request: Request) -> str | None:
    """The caller's address, for the `source_ip` envelope field.

    `request.client` is what the ASGI server accepted the connection from; a proxy that rewrites it is
    a deployment concern (`app/core/rate_limit.py` records the same caveat). The export stream
    truncates it to `/24` and `/48` per `03-design.md`.
    """
    return None if request.client is None else request.client.host


def _context(actor: ActorDep, request: Request) -> dict[str, str | None]:
    """The request-scoped identifiers the audit envelope carries.

    `None` is a valid value for all of them: a test client has no meaningful address, and the writer
    records a missing request id as `-` rather than inventing one.
    """
    return {
        "actor_role": actor.actor_role,
        "source_ip": _client_ip(request),
        "request_id": request.headers.get("x-request-id"),
        "correlation_id": request.headers.get("x-correlation-id"),
    }


@router.get("/events", response_model=AuditEventsPublic)
def list_audit_events(
    *,
    actor: ActorDep,
    request: Request,
    filters: service.AuditFilters = Depends(audit_filters),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(default=None, max_length=MAX_CURSOR_LENGTH),
) -> AuditEventsPublic:
    """One keyset page of the caller's audit trail, newest first, and the read is itself audited."""
    authorize(actor, AUDIT_READ_PERMISSION)
    try:
        with tenant_transaction(
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            **_context(actor, request),
        ) as session:
            page = service.read_events(
                session, filters=filters, limit=limit, cursor=cursor
            )
            # Serialised **inside** the transaction, exactly as `app/modules/patients/service.py`
            # does it: the session expires its instances when it closes, so a later attribute access
            # would raise `DetachedInstanceError` — or worse, lazily re-query outside the
            # tenant-scoped transaction that authorised the read.
            return AuditEventsPublic(
                data=[AuditEventRead.model_validate(entry) for entry in page.entries],
                count=len(page.entries),
                next_cursor=page.next_cursor,
            )
    except service.InvalidCursor as error:
        raise _unprocessable(str(error)) from error


@router.get("", response_model=AuditEventsPublic, include_in_schema=False)
def list_audit_events_alias(
    *,
    actor: ActorDep,
    request: Request,
    filters: service.AuditFilters = Depends(audit_filters),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(default=None, max_length=MAX_CURSOR_LENGTH),
) -> AuditEventsPublic:
    """The design's own path (`GET /api/v1/audit`), served by the same handler as `/events`."""
    return list_audit_events(
        actor=actor, request=request, filters=filters, limit=limit, cursor=cursor
    )


@router.get("/events/{event_id}", response_model=AuditEventRead)
def read_audit_event(
    *, actor: ActorDep, request: Request, event_id: uuid.UUID
) -> AuditEventRead:
    """One event of the caller's trail. Another tenant's event is `404`, and the attempt is audited."""
    authorize(actor, AUDIT_READ_PERMISSION)
    with tenant_transaction(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        **_context(actor, request),
    ) as session:
        outcome = service.read_event(session, event_id=event_id)
        # Both halves are built before the session closes: the token for a found event, and nothing at
        # all for a refused one. The `404` is raised **after** the transaction commits, because the
        # refusal's `audit.read` event is written on it — an exception inside the block would roll
        # that evidence back, and a cross-tenant attempt is the one read that must leave a record.
        token = (
            None
            if outcome.entry is None
            else AuditEventRead.model_validate(outcome.entry)
        )
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Audit event not found"
        )
    return token


__all__ = ["router"]
