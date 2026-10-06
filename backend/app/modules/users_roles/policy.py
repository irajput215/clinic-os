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

## The grantability rule (R3)

`can()` answers "may this actor exercise this permission?". Granting is a second question, and it lives
here too so there is still exactly one decision authority: `can_grant(actor, permission_codes)` refuses
a bundle that contains a permission the actor does not hold, with the design's reason code
`GRANT_EXCEEDS_ACTOR` (`03-design.md`, "The grantability rule (R3)"; `01-requirements.md` R3). Without
it, `users:manage` would be a vertical-escalation primitive: an Administrator holds `users:manage` but
not `tenant:configure`, and the `PRACTICE_OWNER` bundle contains `tenant:configure`.
"""

import uuid
from collections.abc import Iterable
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
    GRANT_EXCEEDS_ACTOR = "GRANT_EXCEEDS_ACTOR"


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

    `role_codes` is the account's own role codes, resolved from the same rows as `permissions`. It
    exists so an audit event can record `actor_role` — *"the role held **at decision time**, not the
    role held later"* (`docs/features/04-audit-log/03-design.md`, envelope table). It is a record for
    the trail, never an input to a decision: `can()` reads `permissions` and nothing else, so a role
    name can never become a second, weaker authorisation path.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    is_active: bool
    permissions: frozenset[str]
    role_codes: frozenset[str] = frozenset()

    @property
    def actor_role(self) -> str | None:
        """The role codes as one stable string for the audit envelope.

        Sorted and comma-joined so two requests with the same role set produce the same value, and the
        column's 64-character limit is respected by truncation rather than by an insert failure.
        `None` (rather than an empty string) when the account holds no role, because the envelope's
        `actor_role` is nullable and "no role" is not "the empty role".
        """
        if not self.role_codes:
            return None
        return ",".join(sorted(self.role_codes))[:64]


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


def can_grant(actor: Actor | None, *, permission_codes: Iterable[str]) -> Decision:
    """Decide whether `actor` may grant every permission in `permission_codes` (R3).

    `permission_codes` is the incoming bundle — the permission set of a role about to be assigned, or
    of a role_permissions change. Deny-by-default, and the same first two checks as `can()`: no
    identity is `401`, a non-`ACTIVE` actor is `403`. A single permission the actor does not hold
    refuses the whole bundle with `403 GRANT_EXCEEDS_ACTOR` (`03-design.md`, "The grantability rule
    (R3)"). An empty bundle carries nothing to escalate and is allowed for an active actor.
    """
    if actor is None:
        return _deny(401, DecisionCode.NO_IDENTITY, "Authentication is required")

    if not actor.is_active:
        return _deny(
            403, DecisionCode.IDENTITY_NOT_ACTIVE, "This account is not active"
        )

    missing = frozenset(permission_codes) - actor.permissions
    if missing:
        return _deny(
            403,
            DecisionCode.GRANT_EXCEEDS_ACTOR,
            "The grant would confer a permission the actor does not hold",
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
