"""Authorisation, tenant-isolation and abuse-protection tests for the roles administration API.

Design: `docs/features/03-users-and-roles/03-design.md`, "Endpoints" (every row is `users:manage`),
"The grantability rule (R3)" and "Deny-by-default request path"; threat model T-03.11 (the
administrative rate limit). Requirements R2, R3, R6 and R7.

The right to `users:manage` is hard-coded from `01-requirements.md`'s matrix, so this file is a check
on the catalogue rather than a restatement of it: `PRACTICE_OWNER` and `ADMINISTRATOR` hold it; the
other five roles do not.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.modules.users_roles.catalog import SYSTEM_ROLE_CODES
from tests.utils.rbac import ActorSession, RbacApi

ROLES_URL = f"{settings.API_V1_STR}/roles"
PERMISSIONS_URL = f"{settings.API_V1_STR}/permissions"


def _user_roles_url(user_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/users/{user_id}/roles"


def _user_permissions_url(user_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/users/{user_id}/permissions"


# The `G` cells of the `users:manage` row in `01-requirements.md`'s permission matrix.
ROLES_HOLDING_USERS_MANAGE = frozenset({"PRACTICE_OWNER", "ADMINISTRATOR"})


def test_unauthenticated_requests_are_refused_401(client: TestClient) -> None:
    """Part 2 of the Definition of Done: the endpoint requires the identity it should."""
    unknown = uuid.uuid4()
    assert client.get(ROLES_URL).status_code == 401
    assert client.get(PERMISSIONS_URL).status_code == 401
    assert client.get(_user_roles_url(unknown)).status_code == 401
    assert client.get(_user_permissions_url(unknown)).status_code == 401
    assert (
        client.post(
            _user_roles_url(unknown), json={"role_id": str(unknown)}
        ).status_code
        == 401
    )
    assert client.delete(f"{_user_roles_url(unknown)}/{unknown}").status_code == 401


def test_only_the_roles_holding_users_manage_reach_the_admin_routes(
    rbac: RbacApi,
) -> None:
    """R1/S2: a role without the route's permission is refused `403` and nothing is written."""
    owner = rbac.register_tenant(clinic_name="Matrix Clinic")
    assert owner.tenant_id is not None
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    doctor_role = rbac.role_id_for(tenant_id=owner.tenant_id, code="DOCTOR")

    actors: dict[str, ActorSession] = {"PRACTICE_OWNER": owner}
    for code in SYSTEM_ROLE_CODES:
        if code != "PRACTICE_OWNER":
            actors[code] = rbac.add_actor(
                tenant_id=owner.tenant_id,
                granted_by=owner.user_id,
                role_code=code,
            )

    for code in SYSTEM_ROLE_CODES:
        actor = actors[code]
        expected = 200 if code in ROLES_HOLDING_USERS_MANAGE else 403
        listed = rbac.client.get(ROLES_URL, headers=actor.headers)
        assert listed.status_code == expected, f"{code}: {listed.text}"
        if expected == 403:
            assert listed.json()["detail"]["code"] == "PERMISSION_NOT_HELD"

    # A non-holder cannot assign either, and the refusal changes nothing.
    pharmacy = actors["PHARMACY"]
    refused = rbac.client.post(
        _user_roles_url(target.user_id),
        json={"role_id": str(doctor_role)},
        headers=pharmacy.headers,
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "PERMISSION_NOT_HELD"
    assert (
        rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=target.user_id) == []
    )


def test_a_cross_tenant_user_or_role_returns_404_and_changes_nothing(
    rbac: RbacApi,
) -> None:
    """R6/S4: existence is not disclosed, and a cross-tenant write removes and adds nothing."""
    alpha = rbac.register_tenant(clinic_name="Alpha Clinic")
    beta = rbac.register_tenant(clinic_name="Beta Clinic")
    assert alpha.tenant_id is not None and beta.tenant_id is not None
    alpha_target = rbac.add_actor(tenant_id=alpha.tenant_id, granted_by=alpha.user_id)
    beta_target = rbac.add_actor(tenant_id=beta.tenant_id, granted_by=beta.user_id)
    alpha_doctor = rbac.role_id_for(tenant_id=alpha.tenant_id, code="DOCTOR")
    beta_doctor = rbac.role_id_for(tenant_id=beta.tenant_id, code="DOCTOR")
    rbac.grant(
        tenant_id=alpha.tenant_id,
        user_id=alpha_target.user_id,
        role_code="DOCTOR",
        granted_by=alpha.user_id,
    )
    rbac.grant(
        tenant_id=beta.tenant_id,
        user_id=beta_target.user_id,
        role_code="DOCTOR",
        granted_by=beta.user_id,
    )

    # Beta's administrator may not read Alpha's account.
    assert (
        rbac.client.get(
            _user_roles_url(alpha_target.user_id), headers=beta.headers
        ).status_code
        == 404
    )
    assert (
        rbac.client.get(
            _user_permissions_url(alpha_target.user_id), headers=beta.headers
        ).status_code
        == 404
    )

    # Alpha's role is invisible in Beta, and Beta's account is invisible in Alpha: both `404`.
    refused_foreign_user = rbac.client.post(
        _user_roles_url(alpha_target.user_id),
        json={"role_id": str(beta_doctor)},
        headers=beta.headers,
    )
    assert refused_foreign_user.status_code == 404
    refused_foreign_role = rbac.client.post(
        _user_roles_url(beta_target.user_id),
        json={"role_id": str(alpha_doctor)},
        headers=beta.headers,
    )
    assert refused_foreign_role.status_code == 404

    # A cross-tenant revoke removes nothing, on either side of the boundary.
    assert (
        rbac.client.delete(
            f"{_user_roles_url(alpha_target.user_id)}/{alpha_doctor}",
            headers=beta.headers,
        ).status_code
        == 404
    )
    assert (
        rbac.client.delete(
            f"{_user_roles_url(beta_target.user_id)}/{alpha_doctor}",
            headers=beta.headers,
        ).status_code
        == 404
    )

    assert rbac.assignment_codes(
        tenant_id=alpha.tenant_id, user_id=alpha_target.user_id
    ) == ["DOCTOR"], "a cross-tenant request changed Alpha's assignments"
    assert rbac.assignment_codes(
        tenant_id=beta.tenant_id, user_id=beta_target.user_id
    ) == ["DOCTOR"], "a cross-tenant request changed Beta's assignments"


def test_a_client_supplied_tenant_value_cannot_influence_anything(
    rbac: RbacApi,
) -> None:
    """INV-1: the tenant is resolved from the session; a body, query or header value never wins."""
    alpha = rbac.register_tenant(clinic_name="Alpha Clinic")
    beta = rbac.register_tenant(clinic_name="Beta Clinic")
    assert alpha.tenant_id is not None and beta.tenant_id is not None
    alpha_target = rbac.add_actor(tenant_id=alpha.tenant_id, granted_by=alpha.user_id)
    beta_target = rbac.add_actor(tenant_id=beta.tenant_id, granted_by=beta.user_id)
    alpha_doctor = rbac.role_id_for(tenant_id=alpha.tenant_id, code="DOCTOR")

    # A query parameter and a header naming Beta are ignored on a read: Alpha's own roles come back.
    own = rbac.client.get(ROLES_URL, headers=alpha.headers)
    assert own.status_code == 200, own.text
    own_ids = {role["id"] for role in own.json()["data"]}
    forged_read = rbac.client.get(
        f"{ROLES_URL}?tenant_id={beta.tenant_id}",
        headers={**alpha.headers, "X-Tenant-Id": str(beta.tenant_id)},
    )
    assert forged_read.status_code == 200, forged_read.text
    assert {role["id"] for role in forged_read.json()["data"]} == own_ids
    assert str(alpha_doctor) in own_ids

    # A query parameter and a header naming Beta cannot redirect a write: Alpha writes to Alpha.
    assigned = rbac.client.post(
        f"{_user_roles_url(alpha_target.user_id)}?tenant_id={beta.tenant_id}",
        json={"role_id": str(alpha_doctor)},
        headers={**alpha.headers, "X-Tenant-Id": str(beta.tenant_id)},
    )
    assert assigned.status_code == 201, assigned.text
    assert rbac.assignment_codes(
        tenant_id=alpha.tenant_id, user_id=alpha_target.user_id
    ) == ["DOCTOR"]
    assert (
        rbac.assignment_codes(tenant_id=beta.tenant_id, user_id=beta_target.user_id)
        == []
    ), "a client-supplied tenant id moved the grant to the other tenant"

    # A body `tenant_id` is an unknown field, so it is rejected before any query runs.
    forged_body = rbac.client.post(
        _user_roles_url(alpha_target.user_id),
        json={"role_id": str(alpha_doctor), "tenant_id": str(beta.tenant_id)},
        headers=alpha.headers,
    )
    assert forged_body.status_code == 422, forged_body.text
    assert "tenant_id" in forged_body.text


def test_r8_never_answers_for_another_tenants_role(rbac: RbacApi) -> None:
    """R8 is a decision about the caller's own tenant, and it must not leak a foreign one.

    Alpha's owner is Alpha's last holder of `users:manage`, so Alpha's own revoke is `409`. Beta
    making the same call against Alpha's account must still get the flat `404` (R6) — a `409` there
    would confirm that the foreign account holds a granting role.
    """
    alpha = rbac.register_tenant(clinic_name="R8 Alpha")
    beta = rbac.register_tenant(clinic_name="R8 Beta")
    assert alpha.tenant_id is not None and beta.tenant_id is not None
    alpha_owner_role = rbac.role_id_for(
        tenant_id=alpha.tenant_id, code="PRACTICE_OWNER"
    )

    assert (
        rbac.client.delete(
            f"{_user_roles_url(alpha.user_id)}/{alpha_owner_role}",
            headers=beta.headers,
        ).status_code
        == 404
    )
    assert rbac.assignment_codes(tenant_id=alpha.tenant_id, user_id=alpha.user_id) == [
        "PRACTICE_OWNER"
    ], "a cross-tenant revoke removed Alpha's last administrator"


def test_the_administrative_rate_limit_refuses_the_twenty_first_request(
    rbac: RbacApi,
) -> None:
    """T-03.11: the administrative endpoint class is limited to 20 requests per minute."""
    owner = rbac.register_tenant(clinic_name="Rate Limit Clinic")
    assert owner.tenant_id is not None

    for _ in range(20):
        assert rbac.client.get(ROLES_URL, headers=owner.headers).status_code == 200
    refused = rbac.client.get(ROLES_URL, headers=owner.headers)
    assert refused.status_code == 429, refused.text
    assert "Retry-After" in refused.headers
