"""Request and response schemas for the roles and role-assignment administration API.

Design: `docs/features/03-users-and-roles/03-design.md`, "Endpoints" and "Deny-by-default request
path" step 5 ("Validate the body against a strict Pydantic v2 model — extra fields forbidden, so a
`tenant_id`, `role_ids` or `granted_by` in the body is rejected `422`").

Every request model is strict — `extra="forbid"` — so a body carrying `tenant_id`, `granted_by`,
`id`, `granted_at` or any other column the design does not expose is a `422` rather than a quietly
ignored field (S14). There is no request model that accepts a tenant identifier: the tenant is
resolved from the authenticated session and from nowhere else (INV-1).

Output models carry no tenant identifier: the caller already knows its own tenant, and nothing that is
not needed is exposed. `user_roles.granted_by` is SENSITIVE and is deliberately **not** returned —
an administrator needs the role and when it was granted, not the granter's identifier. `id` on a
permission is internal join-key material and is not exposed; `code` is the catalogue's stable identity.

`SQLModelConfig` is imported from `sqlmodel._compat` for the same reason the patients schemas do it:
SQLModel annotates `model_config` as its own type, so a plain `ConfigDict` is rejected by both
`mypy --strict` and `ty`.
"""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

# PRIVATE API, deliberately; see the module docstring.
from sqlmodel._compat import SQLModelConfig


class PermissionRead(SQLModel):
    """One entry of the global permission catalogue.

    `permissions.id` is not exposed: `code` is the catalogue's stable identity and the join key is
    internal. `permissions` is global read-only reference data (R7).
    """

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    code: str
    description: str


class PermissionsPublic(SQLModel):
    """The permission catalogue, or a computed subset of it, plus its size."""

    data: list[PermissionRead]
    count: int


class RoleRead(SQLModel):
    """A tenant-scoped role and the permission bundle it resolves to."""

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    is_system: bool
    permissions: list[PermissionRead]


class RolesPublic(SQLModel):
    """The organisation's roles, ordered by code, plus their count."""

    data: list[RoleRead]
    count: int


class RoleAssignmentCreate(SQLModel):
    """The body of `POST /api/v1/users/{user_id}/roles`.

    Only `role_id` is accepted. A `tenant_id` (INV-1), a `granted_by` or a `user_id` is an unknown
    field and is rejected `422` before any query runs — the design's step 5 names exactly those three.
    """

    model_config = SQLModelConfig(extra="forbid", str_strip_whitespace=True)

    role_id: uuid.UUID


class UserRoleRead(SQLModel):
    """One role an account holds inside the caller's tenant.

    `granted_at` is returned because an access review needs the age of the grant (US-2); the granter's
    identifier is not.
    """

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    role_id: uuid.UUID
    code: str
    name: str
    is_system: bool
    granted_at: datetime


class UserRolesPublic(SQLModel):
    """The roles one account holds, plus their count."""

    data: list[UserRoleRead]
    count: int


class UserPermissionsRead(SQLModel):
    """The effective permission set of one account, computed server-side from its roles.

    The design names this "effective set, computed server-side": nothing here comes from the request,
    and the set is the union of the account's role bundles (R1).
    """

    model_config = SQLModelConfig(extra="forbid")

    user_id: uuid.UUID
    permissions: list[PermissionRead]
    count: int
