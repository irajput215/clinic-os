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

## Provisioning a tenant

The seven system roles are **per tenant** (`roles.tenant_id NOT NULL`, unique `(tenant_id, code)`), so
they cannot be seeded once globally. They are created for a tenant when the tenant is created:
`provision_tenant(...)` does it for self-service signup and assigns the bootstrap role, and
`provision_tenant_roles(...)` does it without an owner (the demo tenant). The seed migration does the
same for tenants that already existed when it ran.
"""

import uuid
from collections.abc import Iterable, Sequence

from sqlmodel import Session, select

from app.core.db import tenant_transaction
from app.models import User
from app.modules.users_roles.catalog import (
    BOOTSTRAP_ROLE_CODE,
    PERMISSION_CATALOGUE,
    SYSTEM_ROLE_CATALOGUE,
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
    PermissionRead,
    PermissionsPublic,
    RoleRead,
    RolesPublic,
    UserPermissionsRead,
    UserRoleRead,
    UserRolesPublic,
)

__all__ = [
    "Actor",
    "Decision",
    "ResourceRef",
    "actor_for",
    "assign_role",
    "authorize",
    "authorize_grant",
    "can",
    "can_grant",
    "effective_permissions",
    "enforce",
    "list_permissions",
    "list_roles",
    "provision_tenant",
    "provision_tenant_roles",
    "read_user_roles",
    "resolve_permissions",
    "revoke_role",
    "seed_tenant_roles",
]

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


def provision_tenant(*, tenant_id: uuid.UUID, owner_user_id: uuid.UUID) -> None:
    """Create a tenant's system roles and grant the signer the bootstrap role.

    This is the organisation-signup bootstrap, not the grant endpoint: there is no prior actor whose
    permission set a grantability rule could check, so the *tenant's own* first account is made
    `PRACTICE_OWNER`. Every later grant goes through the policy layer and the R3 grantability rule:
    `assign_role` below calls `authorize_grant` on the incoming bundle before it writes anything.
    """
    with tenant_transaction(tenant_id=tenant_id, actor_id=owner_user_id) as session:
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


def resolve_permissions(
    session: Session, *, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> frozenset[str]:
    """The union of the permission codes of the roles this account holds in this tenant.

    The caller supplies the tenant the session resolved, never a request value; the query runs under
    forced RLS as well.
    """
    permissions: Sequence[Permission] = session.exec(select(Permission)).all()
    code_by_id = {permission.id: permission.code for permission in permissions}
    held_role_ids = {
        granted.role_id
        for granted in session.exec(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.tenant_id == tenant_id,
            )
        ).all()
    }
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


def actor_for(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    is_active: bool,
) -> Actor:
    """Build the request's `Actor`, resolving its permissions under the tenant's RLS context.

    The tenant is the one the session resolved. A boundary that has no tenant refuses before calling
    here, so this always resolves under RLS rather than an unscoped query.
    """
    with tenant_transaction(tenant_id=tenant_id, actor_id=user_id) as session:
        permissions = resolve_permissions(session, user_id=user_id, tenant_id=tenant_id)
    return Actor(
        user_id=user_id,
        tenant_id=tenant_id,
        is_active=is_active,
        permissions=permissions,
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
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id
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


def revoke_role(
    *,
    actor: Actor,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> bool:
    """Revoke one role from one account of the actor's tenant.

    Returns `True` when a row was removed and `False` when there was nothing to remove — for an absent
    account, an absent role, or an assignment that does not exist. The router answers `404` for all
    three, because distinguishing them would disclose existence across a tenant boundary (R6) and
    because a partial answer would let a caller enumerate assignments.

    This is the hard delete the design grants: `03-design.md` gives `clinos_app` `DELETE` on
    `user_roles` and `role_permissions` — *"grant/revoke is real"* — and the append-only audit trail,
    not the row, is the history. There is no soft-delete column on `user_roles`.
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id
    ) as session:
        if _tenant_user(session, tenant_id=actor.tenant_id, user_id=user_id) is None:
            return False
        role = session.exec(
            select(Role).where(
                Role.id == role_id,
                Role.tenant_id == actor.tenant_id,
            )
        ).first()
        if role is None:
            return False
        assignment = session.exec(
            select(UserRole).where(
                UserRole.tenant_id == actor.tenant_id,
                UserRole.user_id == user_id,
                UserRole.role_id == role.id,
            )
        ).first()
        if assignment is None:
            return False
        session.delete(assignment)
        return True
