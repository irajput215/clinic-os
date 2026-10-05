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
from collections.abc import Sequence

from sqlmodel import Session, select

from app.core.db import tenant_transaction
from app.modules.users_roles.catalog import (
    BOOTSTRAP_ROLE_CODE,
    SYSTEM_ROLE_CATALOGUE,
)
from app.modules.users_roles.models import Permission, Role, RolePermission, UserRole
from app.modules.users_roles.policy import (
    Actor,
    Decision,
    ResourceRef,
    can,
    enforce,
)

__all__ = [
    "Actor",
    "Decision",
    "ResourceRef",
    "actor_for",
    "authorize",
    "can",
    "enforce",
    "provision_tenant",
    "provision_tenant_roles",
    "resolve_permissions",
    "seed_tenant_roles",
]


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
    `PRACTICE_OWNER`. Every later grant goes through the policy layer and the R5/R3 grantability rule,
    which this slice does not build (the `/users/{id}/roles` endpoints are not in scope).
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
