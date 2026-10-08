"""Users and roles service facade — the only place the RBAC tables are queried.

Everything outside this module reaches `roles`, `permissions`, `role_permissions` and `user_roles`
through here (`docs/reference/build-contract.md` §7: a module owns its tables and is reached only
through its service facade).

The authorisation decision itself lives in [`policy.py`](policy.py) and is re-exported below so a route
has exactly one import: `authorize(actor, permission, resource)` resolves nothing, it only applies the
decision; `actor_for(...)` is what resolves the permission set from the database, under
`app.core.db.tenant_transaction`, so RLS scopes the query to the request's tenant. Nothing here reads a
tenant identifier from a request — the caller passes the tenant the session resolved (INV-1).

The permission set is recomputed from `user_roles -> role_permissions` on every call. There is no
cache, so a tightened grant cannot keep authorising a previous request (R2, T-03.5).

## Audit

A role grant and a role revoke emit `user.permission_change` on the **same transaction** as the write
(`app/modules/audit/service.py`, INV-4): a grant that cannot be audited does not happen, and a rollback
leaves neither the `user_roles` row nor the audit row. The action is doc 07 §1's name — see
`catalog.py` for why it is not `ROLE_ASSIGNED`/`ROLE_REVOKED` — and which of the two happened is in the
payload's `change` key (`GRANT`, `REVOKE`, `NONE`). `actor_role` is the role the actor held at the
moment of the decision.

## Provisioning a tenant

The seven system roles are **per tenant** (`roles.tenant_id NOT NULL`, unique `(tenant_id, code)`), so
they cannot be seeded once globally. They are created for a tenant when the tenant is created:
`provision_tenant_in_transaction(...)` does it — and assigns the bootstrap role — on a transaction the
caller owns, which is what signup uses so the tenant, the account and the grant commit together;
`provision_tenant(...)` is the same work with its own transaction, and `provision_tenant_roles(...)`
does it without an owner (the demo tenant). The seed migration does the same for tenants that already
existed when it ran.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.core.db import engine, tenant_transaction
from app.core.security import get_password_hash
from app.models import User

# The audit module is reached through its service facade, like every other module
# (`docs/reference/build-contract.md` §7). The import is one-way — `audit` knows nothing about
# `users_roles` — so there is no cycle.
from app.modules.audit import service as audit
from app.modules.identity_tenancy import service as identity_tenancy
from app.modules.users_roles import invitations
from app.modules.users_roles.catalog import (
    ADMINISTRATION_PERMISSION,
    BOOTSTRAP_ROLE_CODE,
    CLIENT_TENANT_ID_IGNORED,
    EMAIL_UNAVAILABLE,
    PERMISSION_CATALOGUE,
    SYSTEM_ROLE_CATALOGUE,
    USER_CREATE,
    USER_PERMISSION_CHANGE,
)
from app.modules.users_roles.models import Permission, Role, RolePermission, UserRole
from app.modules.users_roles.policy import (
    Actor,
    Decision,
    ResourceRef,
    can,
    can_grant,
    enforce,
)
from app.modules.users_roles.schemas import (
    InvitationAccepted,
    OwnPermissionsRead,
    PermissionRead,
    PermissionsPublic,
    RoleRead,
    RolesPublic,
    StaffInvite,
    StaffMemberRead,
    StaffPublic,
    StaffRoleRead,
    UserPermissionsRead,
    UserRoleRead,
    UserRolesPublic,
)

__all__ = [
    "Actor",
    "Decision",
    "ResourceRef",
    "InvitationOutcome",
    "InvitationResult",
    "RevokeOutcome",
    "accept_invitation",
    "actor_for",
    "assign_role",
    "authorize",
    "authorize_grant",
    "can",
    "can_grant",
    "effective_permissions",
    "enforce",
    "invite_staff",
    "list_permissions",
    "list_roles",
    "list_staff",
    "own_permissions",
    "provision_tenant",
    "provision_tenant_in_transaction",
    "provision_tenant_roles",
    "read_user_roles",
    "record_invitation_denial",
    "resolve_permissions",
    "revoke_role",
    "seed_tenant_roles",
]


class RevokeOutcome(StrEnum):
    """What one revoke attempt did, so the router maps it to a status without re-deciding.

    `NOT_FOUND` is the answer for an absent account, an absent role and an absent assignment alike:
    the router turns all three into `404`, because distinguishing them would disclose existence across
    a tenant boundary (R6). `LAST_ADMINISTRATOR` is R8's refusal, and it is the only outcome that
    explains itself — the router returns `409` with the design's reason code.
    """

    REVOKED = "REVOKED"
    NOT_FOUND = "NOT_FOUND"
    LAST_ADMINISTRATOR = "LAST_ADMINISTRATOR"


# The catalogue's declared order, so a listing is stable and matches
# `01-requirements.md`'s matrix rather than the database's physical order.
_CATALOGUE_ORDER: dict[str, int] = {
    code: index for index, (code, _description) in enumerate(PERMISSION_CATALOGUE)
}


def _roles_for_tenant(session: Session, tenant_id: uuid.UUID) -> dict[str, Role]:
    roles: Sequence[Role] = session.exec(
        select(Role).where(Role.tenant_id == tenant_id)
    ).all()
    return {role.code: role for role in roles}


def seed_tenant_roles(session: Session, *, tenant_id: uuid.UUID) -> None:
    """Ensure the seven system roles and their bundles exist for one tenant. Idempotent.

    The caller must already be inside `tenant_transaction` for this tenant: the inserts carry a
    `tenant_id` that RLS `WITH CHECK` verifies against `app.tenant_id`.
    """
    permissions: Sequence[Permission] = session.exec(select(Permission)).all()
    permission_id_by_code = {
        permission.code: permission.id for permission in permissions
    }
    missing = {
        code
        for _, _, bundle in SYSTEM_ROLE_CATALOGUE
        for code in bundle
        if code not in permission_id_by_code
    }
    if missing:
        raise RuntimeError(
            "the permission catalogue is not seeded; missing "
            + ", ".join(sorted(missing))
        )

    by_code = _roles_for_tenant(session, tenant_id)
    for code, name, _bundle in SYSTEM_ROLE_CATALOGUE:
        if code not in by_code:
            role = Role(tenant_id=tenant_id, code=code, name=name, is_system=True)
            session.add(role)
            session.flush()
            by_code[code] = role

    existing: set[tuple[uuid.UUID, uuid.UUID]] = {
        (grant.role_id, grant.permission_id)
        for grant in session.exec(
            select(RolePermission).where(RolePermission.tenant_id == tenant_id)
        ).all()
    }
    for code, _name, bundle in SYSTEM_ROLE_CATALOGUE:
        role = by_code[code]
        for permission_code in sorted(bundle):
            key = (role.id, permission_id_by_code[permission_code])
            if key not in existing:
                session.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission_id_by_code[permission_code],
                        tenant_id=tenant_id,
                    )
                )
                existing.add(key)


def provision_tenant_roles(*, tenant_id: uuid.UUID) -> None:
    """Seed the system roles for a tenant that has no members yet (the demo organisation)."""
    with tenant_transaction(tenant_id=tenant_id) as session:
        seed_tenant_roles(session, tenant_id=tenant_id)


def provision_tenant_in_transaction(
    session: Session, *, tenant_id: uuid.UUID, owner_user_id: uuid.UUID
) -> None:
    """Seed a tenant's system roles and grant the signer the bootstrap role, on the caller's session.

    The work of `provision_tenant`, minus the transaction: organisation signup creates the tenant,
    the account and this grant as **one** unit, so the grant cannot open a transaction of its own —
    a failure after the account exists would otherwise leave an organisation with no administrator,
    or an account whose roles were never written.

    The caller must already be inside `tenant_transaction` for this tenant (the `roles`, `user_roles`
    and `role_permissions` inserts carry a `tenant_id` that the forced RLS `WITH CHECK` verifies
    against `app.tenant_id`), and owns the commit.

    This is the organisation-signup bootstrap, not the grant endpoint: there is no prior actor whose
    permission set a grantability rule could check, so the *tenant's own* first account is made
    `PRACTICE_OWNER`. Every later grant goes through the policy layer and the R3 grantability rule:
    `assign_role` below calls `authorize_grant` on the incoming bundle before it writes anything.
    """
    seed_tenant_roles(session, tenant_id=tenant_id)
    owner_role = _roles_for_tenant(session, tenant_id)[BOOTSTRAP_ROLE_CODE]
    already = session.exec(
        select(UserRole).where(
            UserRole.user_id == owner_user_id,
            UserRole.role_id == owner_role.id,
        )
    ).first()
    if already is None:
        session.add(
            UserRole(
                user_id=owner_user_id,
                role_id=owner_role.id,
                tenant_id=tenant_id,
                granted_by=owner_user_id,
            )
        )


def provision_tenant(*, tenant_id: uuid.UUID, owner_user_id: uuid.UUID) -> None:
    """Create a tenant's system roles and grant the signer the bootstrap role, in one transaction.

    A standalone caller (a provisioning script, `initial_data.py`) gets the transaction here;
    signup, which must commit this work together with the tenant and the account, calls
    `provision_tenant_in_transaction` on the transaction it already owns.
    """
    with tenant_transaction(tenant_id=tenant_id, actor_id=owner_user_id) as session:
        provision_tenant_in_transaction(
            session, tenant_id=tenant_id, owner_user_id=owner_user_id
        )


def _held_role_ids(
    session: Session, *, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> set[uuid.UUID]:
    """The role ids this account holds in this tenant, under the caller's RLS context."""
    return {
        granted.role_id
        for granted in session.exec(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.tenant_id == tenant_id,
            )
        ).all()
    }


def resolve_permissions(
    session: Session, *, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> frozenset[str]:
    """The union of the permission codes of the roles this account holds in this tenant.

    The caller supplies the tenant the session resolved, never a request value; the query runs under
    forced RLS as well.
    """
    permissions: Sequence[Permission] = session.exec(select(Permission)).all()
    code_by_id = {permission.id: permission.code for permission in permissions}
    held_role_ids = _held_role_ids(session, user_id=user_id, tenant_id=tenant_id)
    if not held_role_ids:
        return frozenset()
    grants: Sequence[RolePermission] = session.exec(
        select(RolePermission).where(RolePermission.tenant_id == tenant_id)
    ).all()
    return frozenset(
        code_by_id[grant.permission_id]
        for grant in grants
        if grant.role_id in held_role_ids and grant.permission_id in code_by_id
    )


def resolve_role_codes(
    session: Session, *, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> frozenset[str]:
    """The codes of the roles this account holds — the audit envelope's `actor_role` at this moment.

    Separate from `resolve_permissions` because it answers a different question: permissions are what
    a decision reads, role codes are what the trail records. Reading both in one transaction is what
    makes `actor_role` "the role held at decision time" rather than the role held a moment later.
    """
    held = _held_role_ids(session, user_id=user_id, tenant_id=tenant_id)
    if not held:
        return frozenset()
    roles: Sequence[Role] = session.exec(
        select(Role).where(Role.tenant_id == tenant_id)
    ).all()
    return frozenset(role.code for role in roles if role.id in held)


def actor_for(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    is_active: bool,
) -> Actor:
    """Build the request's `Actor`, resolving its permissions under the tenant's RLS context.

    The tenant is the one the session resolved. A boundary that has no tenant refuses before calling
    here, so this always resolves under RLS rather than an unscoped query.

    The account's role codes are resolved in the same transaction as its permissions, so the
    `actor_role` an audit event will carry is the role held at the moment of the decision rather than
    a value re-read afterwards.
    """
    with tenant_transaction(tenant_id=tenant_id, actor_id=user_id) as session:
        permissions = resolve_permissions(session, user_id=user_id, tenant_id=tenant_id)
        role_codes = resolve_role_codes(session, user_id=user_id, tenant_id=tenant_id)
    return Actor(
        user_id=user_id,
        tenant_id=tenant_id,
        is_active=is_active,
        permissions=permissions,
        role_codes=role_codes,
    )


def authorize(
    actor: Actor | None,
    permission: str,
    resource: ResourceRef | None = None,
) -> Decision:
    """Apply the central decision and raise its denial. The single call a route makes."""
    return enforce(can(actor, permission, resource))


def authorize_grant(actor: Actor | None, permission_codes: Iterable[str]) -> Decision:
    """Apply the R3 grantability rule and raise its denial.

    Separate from `authorize` because it answers a different question: not "may this actor use this
    permission?" but "may this actor confer this bundle?". A bundle containing one permission the actor
    does not hold is refused `403 GRANT_EXCEEDS_ACTOR` in full.
    """
    return enforce(can_grant(actor, permission_codes=permission_codes))


def _tenant_user(
    session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> User | None:
    """One account of this tenant, or `None` for absent **and** for another tenant's.

    The legacy `user` table carries no RLS policy (T1-03 is blocked by D-003), so this explicit
    `tenant_id` predicate is the isolation control here, not a second line of defence. `None` is the
    only not-found answer: the router answers `404` for both cases, so existence is not disclosed
    across a tenant boundary (R6).
    """
    statement = select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    return session.exec(statement).first()


def _permission_rows(session: Session) -> list[Permission]:
    """The catalogue in its declared order, from the database rather than from `catalog.py`."""
    stored: Sequence[Permission] = session.exec(select(Permission)).all()
    return sorted(
        stored,
        key=lambda permission: _CATALOGUE_ORDER.get(
            permission.code, len(_CATALOGUE_ORDER)
        ),
    )


def _permission_reads(
    session: Session,
) -> tuple[dict[uuid.UUID, PermissionRead], dict[str, int]]:
    """Index the catalogue by id and by code for bundle assembly."""
    rows = _permission_rows(session)
    by_id = {
        row.id: PermissionRead(code=row.code, description=row.description)
        for row in rows
    }
    order = {row.code: index for index, row in enumerate(rows)}
    return by_id, order


def _role_bundle(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    role_id: uuid.UUID,
    by_id: dict[uuid.UUID, PermissionRead],
    order: dict[str, int],
) -> list[PermissionRead]:
    """The permission bundle of one role, in catalogue order."""
    grants: Sequence[RolePermission] = session.exec(
        select(RolePermission).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role_id == role_id,
        )
    ).all()
    reads = [
        by_id[grant.permission_id] for grant in grants if grant.permission_id in by_id
    ]
    return sorted(reads, key=lambda read: order.get(read.code, len(order)))


def list_roles(*, tenant_id: uuid.UUID) -> RolesPublic:
    """Every role of the caller's tenant, with its permission bundle (design: `GET /roles`).

    The tenant is the one the session resolved, so the list is the organisation's seven system roles
    (plus any custom role of that tenant), not the roles the caller's own account holds. RLS scopes
    the query as well, and the explicit `tenant_id` predicate keeps it scoped for the current owner
    connection.
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        by_id, order = _permission_reads(session)
        roles: Sequence[Role] = session.exec(
            select(Role).where(Role.tenant_id == tenant_id).order_by(Role.code)
        ).all()
        data = [
            RoleRead(
                id=role.id,
                code=role.code,
                name=role.name,
                is_system=role.is_system,
                permissions=_role_bundle(
                    session,
                    tenant_id=tenant_id,
                    role_id=role.id,
                    by_id=by_id,
                    order=order,
                ),
            )
            for role in roles
        ]
        return RolesPublic(data=data, count=len(data))


def list_permissions(*, tenant_id: uuid.UUID) -> PermissionsPublic:
    """The global permission catalogue (R7: read-only reference data, no tenant key).

    `tenant_id` opens the transaction with a tenant context so the query follows the same
    `tenant_transaction` rule as every other read in this module; `permissions` itself carries no
    `tenant_id` and no RLS.
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        rows = _permission_rows(session)
        data = [
            PermissionRead(code=row.code, description=row.description) for row in rows
        ]
        return PermissionsPublic(data=data, count=len(data))


def read_user_roles(
    *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> UserRolesPublic | None:
    """The roles one account of this tenant holds, or `None` for absent/cross-tenant."""
    with tenant_transaction(tenant_id=tenant_id) as session:
        if _tenant_user(session, tenant_id=tenant_id, user_id=user_id) is None:
            return None
        roles: Sequence[Role] = session.exec(
            select(Role).where(Role.tenant_id == tenant_id)
        ).all()
        role_by_id = {role.id: role for role in roles}
        assignments: Sequence[UserRole] = session.exec(
            select(UserRole).where(
                UserRole.tenant_id == tenant_id,
                UserRole.user_id == user_id,
            )
        ).all()
        data: list[UserRoleRead] = []
        for assignment in assignments:
            role = role_by_id.get(assignment.role_id)
            if role is None:
                # The role was filtered by RLS or removed; the RLS `WITH CHECK` and the RESTRICT
                # foreign key make this unreachable, and dropping the edge is the fail-safe answer.
                continue
            data.append(
                UserRoleRead(
                    role_id=role.id,
                    code=role.code,
                    name=role.name,
                    is_system=role.is_system,
                    granted_at=assignment.granted_at,
                )
            )
        data.sort(key=lambda read: read.code)
        return UserRolesPublic(data=data, count=len(data))


def effective_permissions(
    *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> UserPermissionsRead | None:
    """The union of one account's role bundles, computed server-side.

    Design: `GET /api/v1/users/{id}/permissions`, "effective set, computed server-side".
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        if _tenant_user(session, tenant_id=tenant_id, user_id=user_id) is None:
            return None
        held = resolve_permissions(session, user_id=user_id, tenant_id=tenant_id)
        data = [
            PermissionRead(code=row.code, description=row.description)
            for row in _permission_rows(session)
            if row.code in held
        ]
        return UserPermissionsRead(user_id=user_id, permissions=data, count=len(data))


def own_permissions(actor: Actor) -> OwnPermissionsRead:
    """The caller's own effective permission codes, sorted (`GET /users/me/permissions`).

    The set is the one `actor_for` resolved for this request, from the session's user and tenant only,
    under `tenant_transaction` and forced RLS, recomputed per request (R2). Reusing it rather than
    querying again means the list the caller sees is exactly the set that authorises the same request,
    and costs no second transaction. Nothing from the request body, path or query is read (INV-1).
    """
    return OwnPermissionsRead(permissions=sorted(actor.permissions))


def assign_role(
    *,
    actor: Actor,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> tuple[RoleRead, bool] | None:
    """Grant one role to one account of the actor's tenant.

    Returns `(role, created)`, where `created` is `False` when the account already holds the role —
    the operation is idempotent rather than a `500` from the unique constraint. `None` means "absent
    or another tenant's", for the account and for the role alike, so the router answers `404` (R6).

    The grantability rule (R3) runs **before** the row is written: a bundle containing a permission the
    actor does not hold is refused `403 GRANT_EXCEEDS_ACTOR` and nothing is inserted.

    **The audit event is written on this transaction (INV-4).** A grant that cannot be audited does
    not happen: [`record`][app.modules.audit.service.record] runs before this block commits, and a
    refusal or a database error propagates out of the `with`, rolling the grant back with it. The
    idempotent path writes an event too, with `change = NONE` — an authorised grant call that changed
    nothing is still access-administration activity, and US-6 says failure and refusal are audited with
    the same fidelity as success.
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
    ) as session:
        if _tenant_user(session, tenant_id=actor.tenant_id, user_id=user_id) is None:
            return None
        role = session.exec(
            select(Role).where(
                Role.id == role_id,
                Role.tenant_id == actor.tenant_id,
            )
        ).first()
        if role is None:
            return None

        by_id, order = _permission_reads(session)
        bundle = _role_bundle(
            session,
            tenant_id=actor.tenant_id,
            role_id=role.id,
            by_id=by_id,
            order=order,
        )
        authorize_grant(actor, (permission.code for permission in bundle))

        existing = session.exec(
            select(UserRole).where(
                UserRole.tenant_id == actor.tenant_id,
                UserRole.user_id == user_id,
                UserRole.role_id == role.id,
            )
        ).first()
        created = existing is None
        if created:
            session.add(
                UserRole(
                    user_id=user_id,
                    role_id=role.id,
                    tenant_id=actor.tenant_id,
                    granted_by=actor.user_id,
                )
            )
            session.flush()

        granted = sorted(permission.code for permission in bundle)
        audit.record(
            session,
            audit.AuditEvent(
                action=USER_PERMISSION_CHANGE,
                result="SUCCESS",
                resource_id=user_id,
                payload={
                    "target_user_id": str(user_id),
                    "role_code": role.code,
                    "change": "GRANT" if created else "NONE",
                    "added": granted if created else [],
                    "removed": [],
                    "step_up": False,
                },
            ),
        )

        return (
            RoleRead(
                id=role.id,
                code=role.code,
                name=role.name,
                is_system=role.is_system,
                permissions=bundle,
            ),
            created,
        )


def _removal_locks_out_the_organisation(
    session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID, role_id: uuid.UUID
) -> bool:
    """R8: `True` when deleting this one assignment would leave nobody able to manage users.

    "The last Administrator permission" is `ADMINISTRATION_PERMISSION` (`01-requirements.md`,
    permission matrix: `users:manage` is held by `PRACTICE_OWNER` and `ADMINISTRATOR` only). The check
    asks whether any *other* assignment in the tenant still resolves to a role granting it.

    It fails closed: an unreadable catalogue refuses the removal rather than assuming an administrator
    survives it. That path is unreachable for an authorised caller — the actor had to hold
    `users:manage` to reach here, so the permission row exists — and the refusal is the safe answer if
    it ever is not.
    """
    permission = session.exec(
        select(Permission).where(Permission.code == ADMINISTRATION_PERMISSION)
    ).first()
    if permission is None:
        return True

    managing_role_ids = {
        grant.role_id
        for grant in session.exec(
            select(RolePermission).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.permission_id == permission.id,
            )
        ).all()
    }
    if role_id not in managing_role_ids:
        return False

    remaining = {
        (assignment.user_id, assignment.role_id)
        for assignment in session.exec(
            select(UserRole).where(UserRole.tenant_id == tenant_id)
        ).all()
        if assignment.role_id in managing_role_ids
    }
    remaining.discard((user_id, role_id))
    return not remaining


def revoke_role(
    *,
    actor: Actor,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> RevokeOutcome:
    """Revoke one role from one account of the actor's tenant.

    `NOT_FOUND` for an absent account, an absent role, or an assignment that does not exist — the
    router answers `404` for all three, because distinguishing them would disclose existence across a
    tenant boundary (R6) and because a partial answer would let a caller enumerate assignments.

    `LAST_ADMINISTRATOR` for the removal R8 refuses: taking away the last role that grants
    `ADMINISTRATION_PERMISSION` would leave the organisation with nobody able to manage users, and the
    router answers `409` with nothing removed.

    This is the hard delete the design grants: `03-design.md` gives `clinos_app` `DELETE` on
    `user_roles` and `role_permissions` — *"grant/revoke is real"* — and the append-only audit trail,
    not the row, is the history. There is no soft-delete column on `user_roles`.

    **The audit event is written on this transaction (INV-4), and only when something was removed.**
    `NOT_FOUND` and `LAST_ADMINISTRATOR` change nothing, so they emit nothing here: a refusal is the
    policy layer's business to record, and this function has no evidence to add about a row it did not
    touch. The event that matters is the one for a removal that happened, and it carries the role code
    and the permissions the removal took away.
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
    ) as session:
        if _tenant_user(session, tenant_id=actor.tenant_id, user_id=user_id) is None:
            return RevokeOutcome.NOT_FOUND
        role = session.exec(
            select(Role).where(
                Role.id == role_id,
                Role.tenant_id == actor.tenant_id,
            )
        ).first()
        if role is None:
            return RevokeOutcome.NOT_FOUND
        assignment = session.exec(
            select(UserRole).where(
                UserRole.tenant_id == actor.tenant_id,
                UserRole.user_id == user_id,
                UserRole.role_id == role.id,
            )
        ).first()
        if assignment is None:
            return RevokeOutcome.NOT_FOUND
        if _removal_locks_out_the_organisation(
            session, tenant_id=actor.tenant_id, user_id=user_id, role_id=role.id
        ):
            return RevokeOutcome.LAST_ADMINISTRATOR

        by_id, order = _permission_reads(session)
        removed = sorted(
            permission.code
            for permission in _role_bundle(
                session,
                tenant_id=actor.tenant_id,
                role_id=role.id,
                by_id=by_id,
                order=order,
            )
        )
        session.delete(assignment)
        session.flush()

        audit.record(
            session,
            audit.AuditEvent(
                action=USER_PERMISSION_CHANGE,
                result="SUCCESS",
                resource_id=user_id,
                payload={
                    "target_user_id": str(user_id),
                    "role_code": role.code,
                    "change": "REVOKE",
                    "added": [],
                    "removed": removed,
                    "step_up": False,
                },
            ),
        )
        return RevokeOutcome.REVOKED


# --------------------------------------------------------------------------------------------
# Staff: the organisation's own accounts, and onboarding a new one by invitation
# --------------------------------------------------------------------------------------------


def _staff_roles(
    session: Session, *, tenant_id: uuid.UUID, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[StaffRoleRead]]:
    """The roles each of these accounts holds in this tenant, sorted by role name."""
    if not user_ids:
        return {}
    roles: Sequence[Role] = session.exec(
        select(Role).where(Role.tenant_id == tenant_id)
    ).all()
    role_by_id = {role.id: role for role in roles}
    held: dict[uuid.UUID, list[StaffRoleRead]] = {user_id: [] for user_id in user_ids}
    assignments: Sequence[UserRole] = session.exec(
        select(UserRole).where(
            UserRole.tenant_id == tenant_id,
            col(UserRole.user_id).in_(user_ids),
        )
    ).all()
    for assignment in assignments:
        role = role_by_id.get(assignment.role_id)
        if role is None:
            # Unreachable under the composite foreign key and RLS; dropping the edge is fail-safe.
            continue
        held[assignment.user_id].append(
            StaffRoleRead(role_id=role.id, code=role.code, name=role.name)
        )
    for entries in held.values():
        entries.sort(key=lambda entry: (entry.name, entry.code))
    return held


def _staff_member(user: User, roles: list[StaffRoleRead]) -> StaffMemberRead:
    return StaffMemberRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
        roles=roles,
    )


def list_staff(*, tenant_id: uuid.UUID, skip: int, limit: int) -> StaffPublic:
    """One page of the organisation's accounts, with the roles each holds (`GET /users/staff`).

    The tenant is the one the session resolved (INV-1). The legacy `user` table has no RLS policy
    (T1-03 is blocked by D-003), so the explicit `tenant_id` predicate is the isolation control for
    the accounts, exactly as in `_tenant_user`; the role and assignment reads run under forced RLS as
    well. Ordered by name, then email, then id, so a page boundary is stable. `count` is the
    organisation's total, which `skip`/`limit` do not change.
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        scope = User.tenant_id == tenant_id
        count = session.exec(select(func.count()).select_from(User).where(scope)).one()
        users: Sequence[User] = session.exec(
            select(User)
            .where(scope)
            .order_by(
                func.lower(func.coalesce(col(User.full_name), col(User.email))),
                func.lower(col(User.email)),
                col(User.id),
            )
            .offset(skip)
            .limit(limit)
        ).all()
        held = _staff_roles(
            session, tenant_id=tenant_id, user_ids=[user.id for user in users]
        )
        return StaffPublic(
            data=[_staff_member(user, held[user.id]) for user in users], count=count
        )


@dataclass(frozen=True)
class StaffHoldingRoles:
    """One active account of the organisation, and the system roles it holds there."""

    user_id: uuid.UUID
    full_name: str | None
    email: str
    # `{code: display name}` for the roles held, among the ones asked about.
    roles: dict[str, str]


def active_staff_holding(
    session: Session, *, tenant_id: uuid.UUID, role_codes: Iterable[str]
) -> list[StaffHoldingRoles]:
    """The organisation's **active** accounts that hold at least one of `role_codes`.

    Runs on the caller's tenant transaction, so a reader (the appointments module's practitioner
    roster) can decide on the same snapshot it writes under. The account table has no RLS (T1-03), so
    the explicit `tenant_id` predicate is the isolation control for it, exactly as in `list_staff`;
    the role and assignment reads run under forced RLS as well. Ordered by name, then email, then id.
    """
    wanted = frozenset(role_codes)
    roles: Sequence[Role] = session.exec(
        select(Role).where(Role.tenant_id == tenant_id, col(Role.code).in_(wanted))
    ).all()
    if not roles:
        return []
    role_by_id = {role.id: role for role in roles}
    assignments: Sequence[UserRole] = session.exec(
        select(UserRole).where(
            UserRole.tenant_id == tenant_id,
            col(UserRole.role_id).in_(list(role_by_id)),
        )
    ).all()
    held: dict[uuid.UUID, dict[str, str]] = {}
    for assignment in assignments:
        role = role_by_id[assignment.role_id]
        held.setdefault(assignment.user_id, {})[role.code] = role.name
    if not held:
        return []
    users: Sequence[User] = session.exec(
        select(User)
        .where(
            User.tenant_id == tenant_id,
            col(User.is_active).is_(True),
            col(User.id).in_(list(held)),
        )
        .order_by(
            func.lower(func.coalesce(col(User.full_name), col(User.email))),
            func.lower(col(User.email)),
            col(User.id),
        )
    ).all()
    return [
        StaffHoldingRoles(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            roles=held[user.id],
        )
        for user in users
    ]


class InvitationOutcome(StrEnum):
    """What one invitation attempt did, so the router maps it to a status without re-deciding.

    `ROLE_NOT_FOUND` is the answer for a role id that is absent **or another tenant's** (`404`, R6).
    `GRANT_EXCEEDS_ACTOR` is R3's refusal (`403`). `EMAIL_UNAVAILABLE` is the one answer for an
    address that already has an account anywhere (`409`): it never says which organisation.
    """

    INVITED = "INVITED"
    ROLE_NOT_FOUND = "ROLE_NOT_FOUND"
    GRANT_EXCEEDS_ACTOR = "GRANT_EXCEEDS_ACTOR"
    EMAIL_UNAVAILABLE = "EMAIL_UNAVAILABLE"


@dataclass(frozen=True)
class InvitationResult:
    outcome: InvitationOutcome
    member: StaffMemberRead | None = None
    # The policy layer's refusal, for `GRANT_EXCEEDS_ACTOR`, so the router raises the policy's own
    # answer rather than restating it.
    denial: Decision | None = None


def _email_taken(session: Session, email: str) -> bool:
    """Whether any account, in any organisation, already uses this address (case-insensitively).

    `user.email` is unique across the whole platform (one account is one organisation's, OPEN-3), so
    the check is deliberately not tenant-scoped; what is tenant-scoped is the **answer**, which is
    the same for every organisation (see `invite_staff`).
    """
    taken = session.exec(
        select(func.count())
        .select_from(User)
        .where(func.lower(col(User.email)) == email.lower())
    ).one()
    return taken > 0


def _record_invitation_refusal(
    session: Session, *, reason: str, role_codes: Sequence[str]
) -> None:
    audit.record(
        session,
        audit.AuditEvent(
            action=USER_CREATE,
            result="DENIED",
            reason=reason,
            payload={"added": sorted(role_codes), "step_up": False},
        ),
    )


def record_invitation_denial(*, actor: Actor, reason: str) -> None:
    """Audit an invitation the policy layer refused before the service ran (`PERMISSION_NOT_HELD`).

    Its own transaction, because nothing else is written: the refusal happened before any change.
    A failure here propagates, so a refusal that cannot be audited fails closed.
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        _record_invitation_refusal(session, reason=reason, role_codes=())


def invite_staff(
    *, actor: Actor, invite: StaffInvite, client_tenant_id_supplied: bool
) -> InvitationResult:
    """Create an account in the actor's organisation, grant its roles and email an invitation.

    The order is the design's deny-by-default path, and each refusal is decided before anything is
    written:

    1. Every role must be the actor's tenant's (`404` otherwise; another tenant's role looks absent).
    2. R3: the union of the roles' bundles must be held by the actor (`403 GRANT_EXCEEDS_ACTOR`).
       Checked **before** the address, so a caller who may not grant a role learns nothing about
       which addresses exist.
    3. The address must not already have an account anywhere (`409 EMAIL_UNAVAILABLE`, one answer
       whether the account is in this organisation or another, so no tenant is disclosed).

    The account is created with an unusable password and `tenant_id` from the session (a client
    `tenant_id` was dropped by the schema and is audited here as `CLIENT_TENANT_ID_IGNORED`). The
    grants, the `user.create` event, one `user.permission_change` per role and the email all happen
    on this one transaction (INV-4): the email is sent last, inside it, so a send that raises rolls the
    account back and no account exists that was never invited. A refusal at steps 2 and 3 writes its
    `DENIED` event on this transaction and returns, so the event commits and nothing else does.
    """
    role_ids = list(dict.fromkeys(invite.role_ids))
    try:
        with tenant_transaction(
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            actor_role=actor.actor_role,
        ) as session:
            roles: Sequence[Role] = session.exec(
                select(Role).where(
                    Role.tenant_id == actor.tenant_id, col(Role.id).in_(role_ids)
                )
            ).all()
            if len(roles) != len(role_ids):
                return InvitationResult(InvitationOutcome.ROLE_NOT_FOUND)
            roles = sorted(roles, key=lambda role: role.code)
            role_codes = [role.code for role in roles]

            by_id, order = _permission_reads(session)
            bundles = {
                role.id: sorted(
                    permission.code
                    for permission in _role_bundle(
                        session,
                        tenant_id=actor.tenant_id,
                        role_id=role.id,
                        by_id=by_id,
                        order=order,
                    )
                )
                for role in roles
            }
            conferred = {code for bundle in bundles.values() for code in bundle}
            grant = can_grant(actor, permission_codes=conferred)
            if not grant.allowed:
                _record_invitation_refusal(
                    session, reason=grant.code.value, role_codes=role_codes
                )
                return InvitationResult(
                    InvitationOutcome.GRANT_EXCEEDS_ACTOR, denial=grant
                )

            if _email_taken(session, invite.email):
                _record_invitation_refusal(
                    session, reason=EMAIL_UNAVAILABLE, role_codes=role_codes
                )
                return InvitationResult(InvitationOutcome.EMAIL_UNAVAILABLE)

            if client_tenant_id_supplied:
                _record_invitation_refusal(
                    session, reason=CLIENT_TENANT_ID_IGNORED, role_codes=role_codes
                )

            user = User(
                email=invite.email,
                full_name=invite.full_name,
                is_active=True,
                is_superuser=False,
                tenant_id=actor.tenant_id,
                hashed_password=invitations.unusable_password_hash(),
            )
            session.add(user)
            session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role_id=role.id,
                        tenant_id=actor.tenant_id,
                        granted_by=actor.user_id,
                    )
                )
            session.flush()

            audit.record(
                session,
                audit.AuditEvent(
                    action=USER_CREATE,
                    result="SUCCESS",
                    resource_id=user.id,
                    payload={
                        "target_user_id": str(user.id),
                        "added": role_codes,
                        "step_up": False,
                    },
                ),
            )
            for role in roles:
                audit.record(
                    session,
                    audit.AuditEvent(
                        action=USER_PERMISSION_CHANGE,
                        result="SUCCESS",
                        resource_id=user.id,
                        payload={
                            "target_user_id": str(user.id),
                            "role_code": role.code,
                            "change": "GRANT",
                            "added": bundles[role.id],
                            "removed": [],
                            "step_up": False,
                        },
                    ),
                )

            invitations.send_invitation_email(
                email_to=user.email,
                full_name=invite.full_name,
                organisation=identity_tenancy.tenant_display_name(
                    session, tenant_id=actor.tenant_id
                ),
                token=invitations.issue(
                    user_id=user.id, hashed_password=user.hashed_password
                ),
            )
            return InvitationResult(
                InvitationOutcome.INVITED,
                _staff_member(
                    user,
                    [
                        StaffRoleRead(role_id=role.id, code=role.code, name=role.name)
                        for role in sorted(roles, key=lambda r: (r.name, r.code))
                    ],
                ),
            )
    except IntegrityError:
        # Two requests raced for the same address (an invitation and a signup, or two
        # invitations): the unique index refused the second insert and everything rolled back.
        # The answer is the one a sequential duplicate gets.
        return InvitationResult(InvitationOutcome.EMAIL_UNAVAILABLE)


def accept_invitation(*, token: str, new_password: str) -> InvitationAccepted | None:
    """Spend an invitation link: set the invitee's own password. `None` for any unusable link.

    One answer for a tampered, expired, wrong-purpose or already-spent token, for an account that no
    longer exists, and for a deactivated one, so the response cannot be used to probe accounts. The
    account row is locked while the link is checked and spent, so two concurrent submissions of the
    same link cannot both succeed: the second sees the new password hash and is refused.
    """
    claims = invitations.read(token)
    if claims is None:
        return None
    # The token names the account; the account names its organisation. `user` has no RLS (legacy
    # layer), so this lookup is the same plain read sign-in makes, and the write below runs under
    # the account's own tenant context.
    with Session(engine) as lookup:
        found = lookup.get(User, claims.user_id)
        tenant_id = None if found is None else found.tenant_id
    if tenant_id is None:
        return None
    with tenant_transaction(tenant_id=tenant_id, actor_id=claims.user_id) as session:
        user = session.exec(
            select(User)
            .where(User.id == claims.user_id, User.tenant_id == tenant_id)
            .with_for_update()
        ).first()
        if (
            user is None
            or not user.is_active
            or not invitations.still_unspent(claims, user.hashed_password)
        ):
            return None
        user.hashed_password = get_password_hash(new_password)
        session.add(user)
        return InvitationAccepted(email=user.email)
