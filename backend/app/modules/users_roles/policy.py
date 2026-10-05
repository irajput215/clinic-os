"""The central policy layer: `can(actor, permission, resource)`.

Design: `docs/features/03-users-and-roles/03-design.md`, "The central policy layer" and "Deny-by-default
request path"; requirements R1-R3 and R6 in `../01-requirements.md`. Task T1-29.

One module owns every decision. This function is pure: it takes an `Actor` whose permission set was
already resolved from `user_roles -> role_permissions` under the request's tenant context and returns a
`Decision`. It never reads a request, never compares a role name, and never caches — the caller
re-resolves the actor on every request (T-03.5, R2).

Decision order, exactly as the design fixes it:

1. No verified actor (or no resolvable tenant, which the boundary refuses before this layer) -> deny
   `401 NO_IDENTITY`.
2. A non-`ACTIVE` actor -> deny `403 IDENTITY_NOT_ACTIVE` (design, "Failure behaviour": "A deactivated,
   suspended or locked actor is refused by the policy layer even while a still-valid access token
   exists.").
3. `resource.tenant_id != actor.tenant_id` -> deny `404 CROSS_TENANT`: existence is not disclosed
   across a tenant boundary, so the answer is `404`, never `403` (R6).
4. Permission not in the actor's resolved set -> deny `403 PERMISSION_NOT_HELD`.
5. Otherwise allow.

Step 4 of the design's list — resource rules (care relationship, prescriber of record, pharmacy
routing) — has no implementation here because none of the tables those rules read exist yet:
`care_relationships` has no schema definition and no owner (task T1-34, blocked by
`care-relationships`), and the prescribing tables are later phases. `can()` allows only after the four
checks above, so a resource rule can only ever remove access; its absence is a deferral, not a
fail-open.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from fastapi import HTTPException


class DecisionCode(StrEnum):
    """Machine-readable reason classes. A route returns the code, never a role name."""

    ALLOWED = "ALLOWED"
    NO_IDENTITY = "NO_IDENTITY"
    IDENTITY_NOT_ACTIVE = "IDENTITY_NOT_ACTIVE"
    CROSS_TENANT = "CROSS_TENANT"
    PERMISSION_NOT_HELD = "PERMISSION_NOT_HELD"


@dataclass(frozen=True)
class ResourceRef:
    """The tenant a resource belongs to, resolved server-side. Never built from a request value."""

    tenant_id: uuid.UUID


@dataclass(frozen=True)
class Actor:
    """A verified identity and its resolved permission set.

    `permissions` is resolved from `user_roles -> role_permissions` under the request's tenant
    context. A request with no verified identity or no resolvable tenant is represented as `None`,
    which denies: the boundary (`app.api.deps.get_actor`) refuses an authenticated account that has no
    organisation before this layer runs, so an `Actor` that exists always carries a tenant.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    is_active: bool
    permissions: frozenset[str]


@dataclass(frozen=True)
class Decision:
    """The verdict. `can()` returns it; `enforce()` turns a denial into an HTTP response."""

    allowed: bool
    status_code: int
    code: DecisionCode
    message: str


def _deny(status_code: int, code: DecisionCode, message: str) -> Decision:
    return Decision(allowed=False, status_code=status_code, code=code, message=message)


def can(
    actor: Actor | None,
    permission: str,
    resource: ResourceRef | None = None,
) -> Decision:
    """Decide whether `actor` may exercise `permission` on `resource`.

    Deny-by-default: every path that is not an explicit allow returns a denial. `actor` is `None`
    when the request had no verified identity or no resolvable tenant. `resource` is `None` for a
    collection route or a create, where there is no prior resource to match.
    """
    if actor is None:
        return _deny(401, DecisionCode.NO_IDENTITY, "Authentication is required")

    if not actor.is_active:
        return _deny(
            403,
            DecisionCode.IDENTITY_NOT_ACTIVE,
            "This account is not active",
        )

    if resource is not None and resource.tenant_id != actor.tenant_id:
        return _deny(404, DecisionCode.CROSS_TENANT, "Resource not found")

    if permission not in actor.permissions:
        return _deny(
            403,
            DecisionCode.PERMISSION_NOT_HELD,
            "The required permission is not held",
        )

    return Decision(
        allowed=True, status_code=200, code=DecisionCode.ALLOWED, message="Allowed"
    )


def enforce(decision: Decision) -> Decision:
    """Raise the decision's denial as an HTTP error, or return it unchanged when allowed."""
    if decision.allowed:
        return decision
    raise HTTPException(
        status_code=decision.status_code,
        detail={"code": decision.code.value, "message": decision.message},
    )
