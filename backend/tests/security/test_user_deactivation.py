"""Deactivation is the only way an account goes away, and it takes effect on the next request.

`docs/features/03-users-and-roles/01-requirements.md` R14 — *"A user is deactivated, not hard-deleted;
clinical attribution survives"* — and R5 — *"the deactivated user's next request returns `401`"*.

Both `user_roles` foreign keys name `user` with `ON DELETE RESTRICT` (the holder and the granter), so
the template's `session.delete(user)` raised a foreign-key error for any account that had ever granted
a role. That is the crash these tests would have caught: the route now deactivates, the row and its
attribution stay, and the account's live token stops working at the next request.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import User
from tests.utils.rbac import RbacApi

API = settings.API_V1_STR


def _stored_user(user_id: object) -> User | None:
    with Session(engine) as session:
        return session.get(User, user_id)


def test_deactivating_the_granter_keeps_the_role_it_granted(
    client: TestClient, superuser_token_headers: dict[str, str], rbac: RbacApi
) -> None:
    """`user_roles.granted_by` is RESTRICT: the crash is on the *granter*, not only the holder."""
    owner = rbac.register_tenant(clinic_name="Attribution Clinic")
    assert owner.tenant_id is not None
    member = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="NURSE"
    )

    response = client.delete(
        f"{API}/users/{owner.user_id}", headers=superuser_token_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["message"] == "User deactivated successfully"

    stored = _stored_user(owner.user_id)
    assert stored is not None
    assert stored.is_active is False
    # The grant the deactivated account made still exists, still names it as the granter.
    assert rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=member.user_id) == [
        "NURSE"
    ]


def test_a_deactivated_accounts_next_request_is_401(
    client: TestClient, superuser_token_headers: dict[str, str], rbac: RbacApi
) -> None:
    """R5, end to end: the same unexpired token that worked a moment ago now fails closed."""
    owner = rbac.register_tenant(clinic_name="Offboarding Clinic")
    assert owner.tenant_id is not None
    member = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="NURSE"
    )
    assert client.get(f"{API}/patients", headers=member.headers).status_code == 200

    response = client.delete(
        f"{API}/users/{member.user_id}", headers=superuser_token_headers
    )
    assert response.status_code == 200

    stored = _stored_user(member.user_id)
    assert stored is not None, (
        "the account row must survive: a hard delete is not the answer"
    )
    assert stored.is_active is False
    assert rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=member.user_id) == [
        "NURSE"
    ]

    refused = client.get(f"{API}/patients", headers=member.headers)
    assert refused.status_code == 401
    assert refused.json()["detail"] == "Inactive user"

    # The rest of the organisation is untouched.
    assert client.get(f"{API}/patients", headers=owner.headers).status_code == 200
