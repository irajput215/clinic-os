"""`GET /api/v1/users/me/permissions` - the caller's own effective permission codes.

Contract: `docs2/sdlc/01-auth-and-shell/api.md` (`{permissions: string[]}`), which is the design's
`GET /api/v1/auth/capabilities` row in `docs/features/03-users-and-roles/03-design.md` ("valid
session", "advisory UI data only; never a control"). Any authenticated, active account of an active
organisation may call it; it is not gated by `users:manage`.

The denial path is asserted first (`docs/reference/definition-of-done.md` §9): no session, a dead
session, a deactivated account, an account with no organisation and a suspended organisation all fail
closed before any permission is disclosed. Then the empty set, the tenant boundary, the full set, and
the route-ordering trap: `/users/me/permissions` must never be captured by
`/users/{user_id}/permissions`, which would answer `422` for the literal `me`.
"""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app import crud
from app.api.deps import NO_ORGANISATION, TENANT_NOT_ACTIVE
from app.core.config import settings
from app.core.db import engine
from app.core.security import create_access_token
from app.main import app
from app.models import UserCreate
from app.modules.identity_tenancy.models import Tenant
from app.modules.users_roles.catalog import PERMISSION_CATALOGUE, SYSTEM_ROLE_CATALOGUE
from tests.utils.rbac import RbacApi
from tests.utils.utils import random_email, random_lower_string

API = settings.API_V1_STR
OWN_PERMISSIONS_URL = f"{API}/users/me/permissions"

ALL_CODES = sorted(code for code, _description in PERMISSION_CATALOGUE)
BUNDLES = {code: bundle for code, _name, bundle in SYSTEM_ROLE_CATALOGUE}


def _bearer(subject: uuid.UUID) -> dict[str, str]:
    token = create_access_token(str(subject), timedelta(minutes=5))
    return {"Authorization": f"Bearer {token}"}


def _audit_count(tenant_id: uuid.UUID) -> int:
    """Rows in the trail for one tenant, read as the owner (bypasses RLS)."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM audit_log WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )


# --- Denial path -------------------------------------------------------------------------------


def test_no_session_is_401(client: TestClient) -> None:
    response = client.get(OWN_PERMISSIONS_URL)
    assert response.status_code == 401
    assert "permissions" not in response.json()


def test_a_token_that_does_not_verify_is_401(client: TestClient) -> None:
    response = client.get(
        OWN_PERMISSIONS_URL, headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


def test_a_token_for_an_account_that_no_longer_exists_is_401(
    client: TestClient,
) -> None:
    response = client.get(OWN_PERMISSIONS_URL, headers=_bearer(uuid.uuid4()))
    assert response.status_code == 401


def test_a_deactivated_account_in_an_organisation_is_401(rbac: RbacApi) -> None:
    """R5: a deactivated account's next request is `401`, even though it still holds a role."""
    owner = rbac.register_tenant(clinic_name="Deactivated Clinic")
    assert owner.tenant_id is not None
    doctor = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="DOCTOR"
    )
    with Session(engine) as session:
        user = crud.get_user_by_email(session=session, email=doctor.email)
        assert user is not None
        user.is_active = False
        session.add(user)
        session.commit()

    response = rbac.client.get(OWN_PERMISSIONS_URL, headers=doctor.headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Inactive user"
    assert "prescription:sign" not in response.text


def test_an_account_with_no_organisation_is_403_no_organisation(
    client: TestClient, db: Session
) -> None:
    """No tenant cannot be scoped: refused before any RBAC query, never defaulted to a set."""
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    db.refresh(user)
    response = client.get(OWN_PERMISSIONS_URL, headers=_bearer(user.id))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == NO_ORGANISATION
    assert "permissions" not in response.json()


def test_a_suspended_organisation_is_403_tenant_not_active(rbac: RbacApi) -> None:
    """R10: refused on every request even with a valid, unexpired session."""
    owner = rbac.register_tenant(clinic_name="Suspended Permissions Clinic")
    assert owner.tenant_id is not None
    # Control: the same request is served while the organisation is active.
    assert (
        rbac.client.get(OWN_PERMISSIONS_URL, headers=owner.headers).status_code == 200
    )

    with Session(engine) as session:
        tenant = session.get(Tenant, owner.tenant_id)
        assert tenant is not None
        tenant.status = "SUSPENDED"
        session.add(tenant)
        session.commit()

    response = rbac.client.get(OWN_PERMISSIONS_URL, headers=owner.headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == TENANT_NOT_ACTIVE
    assert "tenant:configure" not in response.text


# --- What the caller sees ----------------------------------------------------------------------


def test_an_account_with_no_role_gets_an_empty_list(rbac: RbacApi) -> None:
    """Deny by default: no role is no permission, and it is `200 []`, not an error and not a default."""
    owner = rbac.register_tenant(clinic_name="Empty Set Clinic")
    assert owner.tenant_id is not None
    nobody = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)

    response = rbac.client.get(OWN_PERMISSIONS_URL, headers=nobody.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"permissions": []}


def test_the_practice_owner_sees_the_full_catalogue_sorted(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="Full Set Clinic")

    response = rbac.client.get(OWN_PERMISSIONS_URL, headers=owner.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"permissions": ALL_CODES}


def test_a_role_sees_exactly_its_bundle_and_roles_union(rbac: RbacApi) -> None:
    """R1: the set is the union of the account's role bundles, nothing more, sorted."""
    owner = rbac.register_tenant(clinic_name="Union Clinic")
    assert owner.tenant_id is not None
    clinician = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="PHARMACY"
    )
    first = rbac.client.get(OWN_PERMISSIONS_URL, headers=clinician.headers)
    assert first.status_code == 200, first.text
    assert first.json() == {"permissions": sorted(BUNDLES["PHARMACY"])}

    rbac.grant(
        tenant_id=owner.tenant_id,
        user_id=clinician.user_id,
        role_code="NURSE",
        granted_by=owner.user_id,
    )
    second = rbac.client.get(OWN_PERMISSIONS_URL, headers=clinician.headers)
    assert second.json() == {
        "permissions": sorted(BUNDLES["PHARMACY"] | BUNDLES["NURSE"])
    }


def test_a_revoked_role_disappears_on_the_next_request(rbac: RbacApi) -> None:
    """R2: no cache - the set is recomputed per request, so a revoke is visible at once."""
    owner = rbac.register_tenant(clinic_name="Revoke Clinic")
    assert owner.tenant_id is not None
    doctor = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="DOCTOR"
    )
    assert rbac.client.get(OWN_PERMISSIONS_URL, headers=doctor.headers).json() == {
        "permissions": sorted(BUNDLES["DOCTOR"])
    }

    rbac.revoke_all(tenant_id=owner.tenant_id, user_id=doctor.user_id)
    assert rbac.client.get(OWN_PERMISSIONS_URL, headers=doctor.headers).json() == {
        "permissions": []
    }


def test_another_tenants_grant_is_never_visible(rbac: RbacApi) -> None:
    """INV-1: a `user_roles` row carrying tenant B never reaches a caller whose session is tenant A.

    The row is planted as the owner connection - no API can produce it - so the test proves the
    resolution is keyed on the session's tenant, not on whatever rows name the account.
    """
    tenant_a = rbac.register_tenant(clinic_name="Tenant A Clinic")
    tenant_b = rbac.register_tenant(clinic_name="Tenant B Clinic")
    assert tenant_a.tenant_id is not None
    assert tenant_b.tenant_id is not None
    member_of_a = rbac.add_actor(
        tenant_id=tenant_a.tenant_id, granted_by=tenant_a.user_id
    )
    rbac.grant(
        tenant_id=tenant_b.tenant_id,
        user_id=member_of_a.user_id,
        role_code="PRACTICE_OWNER",
        granted_by=tenant_b.user_id,
    )
    try:
        response = rbac.client.get(OWN_PERMISSIONS_URL, headers=member_of_a.headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"permissions": []}

        # And B's owner keeps exactly its own set: the planted row changes nothing for B either.
        b_view = rbac.client.get(OWN_PERMISSIONS_URL, headers=tenant_b.headers)
        assert b_view.json() == {"permissions": ALL_CODES}
    finally:
        # Tenant A is cleaned up first, and this row would RESTRICT the delete of A's account.
        rbac.revoke_all(tenant_id=tenant_b.tenant_id, user_id=member_of_a.user_id)


def test_client_supplied_identifiers_are_ignored(rbac: RbacApi) -> None:
    """INV-1: the route reads no parameter; a `user_id` or `tenant_id` in the query changes nothing."""
    owner = rbac.register_tenant(clinic_name="Ignored Params Clinic")
    other = rbac.register_tenant(clinic_name="Ignored Params Other Clinic")
    assert owner.tenant_id is not None
    assert other.tenant_id is not None
    nobody = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)

    response = rbac.client.get(
        OWN_PERMISSIONS_URL,
        params={"user_id": str(other.user_id), "tenant_id": str(other.tenant_id)},
        headers={**nobody.headers, "X-Tenant-Id": str(other.tenant_id)},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"permissions": []}


def test_reading_own_permissions_writes_no_audit_event(rbac: RbacApi) -> None:
    """The closed action catalogue (`04-audit-log/05-data-and-audit.md`) names no permission read."""
    owner = rbac.register_tenant(clinic_name="No Audit Clinic")
    assert owner.tenant_id is not None
    before = _audit_count(owner.tenant_id)
    assert (
        rbac.client.get(OWN_PERMISSIONS_URL, headers=owner.headers).status_code == 200
    )
    assert _audit_count(owner.tenant_id) == before


# --- Route ordering ----------------------------------------------------------------------------


def test_me_is_not_captured_by_the_user_id_route(rbac: RbacApi) -> None:
    """`/users/me/permissions` must match its own route, never `/users/{user_id}/permissions`.

    Captured, the literal `me` fails UUID validation (`422`) for an administrator, and a caller
    without `users:manage` would be refused `403`. A caller holding no role getting `200` proves the
    request reached the self-service route; the administrator getting the bare-codes shape (not the
    `{user_id, permissions: [{code, description}], count}` shape) proves it for the other side.
    """
    owner = rbac.register_tenant(clinic_name="Ordering Clinic")
    assert owner.tenant_id is not None
    nobody = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)

    as_nobody = rbac.client.get(OWN_PERMISSIONS_URL, headers=nobody.headers)
    assert as_nobody.status_code == 200, as_nobody.text

    as_admin = rbac.client.get(OWN_PERMISSIONS_URL, headers=owner.headers)
    assert as_admin.status_code == 200, as_admin.text
    assert set(as_admin.json()) == {"permissions"}
    assert all(isinstance(code, str) for code in as_admin.json()["permissions"])

    # The administrative route is untouched by the new one.
    by_id = rbac.client.get(
        f"{API}/users/{owner.user_id}/permissions", headers=owner.headers
    )
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["user_id"] == str(owner.user_id)

    # Both are declared in the contract the generated SDKs are built from, under distinct operations.
    paths = app.openapi()["paths"]
    own = paths[OWN_PERMISSIONS_URL]["get"]
    assert own["operationId"] == "users-read_own_permissions"
    assert "parameters" not in own, "the route must take no client-supplied identifier"
    assert (
        paths[f"{API}/users/{{user_id}}/permissions"]["get"]["operationId"]
        == "users-read_user_permissions"
    )
