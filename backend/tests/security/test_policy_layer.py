"""T1-29 — the central policy layer decides, and it fails closed.

`can(actor, permission, resource)` is pure, so every branch is asserted directly here rather than
through a route. The order of the branches matters as much as the verdicts: the design fixes it as
failure first, then the resource's tenant, then the permission, then resource rules
(`docs/features/03-users-and-roles/03-design.md`, "The central policy layer").

Requirements: R1-R3 and R6 in `docs/features/03-users-and-roles/01-requirements.md`.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.modules.users_roles.policy import (
    Actor,
    DecisionCode,
    ResourceRef,
    can,
    enforce,
)

TENANT = uuid.uuid4()
ANOTHER_TENANT = uuid.uuid4()


def _actor(
    *,
    permissions: frozenset[str] = frozenset({"patient:read"}),
    is_active: bool = True,
    tenant_id: uuid.UUID = TENANT,
) -> Actor:
    return Actor(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        is_active=is_active,
        permissions=permissions,
    )


def test_a_missing_actor_is_denied_401_no_identity() -> None:
    decision = can(None, "patient:read")
    assert decision.allowed is False
    assert decision.status_code == 401
    assert decision.code is DecisionCode.NO_IDENTITY


def test_a_non_active_actor_is_denied_403_identity_not_active() -> None:
    decision = can(_actor(is_active=False), "patient:read")
    assert decision.allowed is False
    assert decision.status_code == 403
    assert decision.code is DecisionCode.IDENTITY_NOT_ACTIVE


def test_a_cross_tenant_resource_is_denied_404_not_403() -> None:
    """R6: a `403` would confirm the resource exists across a tenant boundary."""
    decision = can(_actor(), "patient:read", ResourceRef(tenant_id=ANOTHER_TENANT))
    assert decision.allowed is False
    assert decision.status_code == 404
    assert decision.code is DecisionCode.CROSS_TENANT


def test_the_tenant_check_precedes_the_permission_check() -> None:
    """Design order: the resource-tenant mismatch is answered before the permission is examined."""
    decision = can(
        _actor(permissions=frozenset()),
        "patient:read",
        ResourceRef(tenant_id=ANOTHER_TENANT),
    )
    assert decision.status_code == 404
    assert decision.code is DecisionCode.CROSS_TENANT


def test_a_permission_not_held_is_denied_403_permission_not_held() -> None:
    decision = can(_actor(), "patient:create")
    assert decision.allowed is False
    assert decision.status_code == 403
    assert decision.code is DecisionCode.PERMISSION_NOT_HELD


def test_deny_by_default_for_an_unknown_permission() -> None:
    """An unseeded or invented permission code matches nothing, never everything."""
    decision = can(_actor(permissions=frozenset()), "patient:merge")
    assert decision.allowed is False
    assert decision.code is DecisionCode.PERMISSION_NOT_HELD


def test_a_held_permission_with_a_matching_resource_is_allowed() -> None:
    decision = can(_actor(), "patient:read", ResourceRef(tenant_id=TENANT))
    assert decision.allowed is True
    assert decision.status_code == 200
    assert decision.code is DecisionCode.ALLOWED


def test_a_resource_is_optional_for_a_collection_or_a_create() -> None:
    assert can(
        _actor(permissions=frozenset({"patient:create"})), "patient:create"
    ).allowed


def test_enforce_raises_the_denial_with_a_machine_readable_code() -> None:
    with pytest.raises(HTTPException) as raised:
        enforce(can(_actor(), "patient:create"))
    assert raised.value.status_code == 403
    assert raised.value.detail == {
        "code": "PERMISSION_NOT_HELD",
        "message": "The required permission is not held",
    }


def test_enforce_returns_an_allow_unchanged() -> None:
    decision = can(_actor(), "patient:read")
    assert enforce(decision) is decision
