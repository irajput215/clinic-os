"""The roles and role-assignment administration API — functional and denial-path tests.

Design: `docs/features/03-users-and-roles/03-design.md`, "Endpoints" and "The grantability rule
(R3)". Requirements R1-R3, R6, R7 and the no-hard-delete reversal in `03-design.md` §Database
privileges (*"grant/revoke is real"*).

The denial path is asserted first, because a route that only works is not evidence
(`docs/reference/definition-of-done.md` §9). Every case names the permission in
`03-design.md`: `users:manage`, held by `PRACTICE_OWNER` and `ADMINISTRATOR` only
(`01-requirements.md`, "Permission catalogue (role x permission)").
"""

import uuid

from app.core.config import settings
from tests.utils.rbac import ActorSession, RbacApi

ROLES_URL = f"{settings.API_V1_STR}/roles"
PERMISSIONS_URL = f"{settings.API_V1_STR}/permissions"
PATIENTS_URL = f"{settings.API_V1_STR}/patients"


def _user_roles_url(user_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/users/{user_id}/roles"


def _user_permissions_url(user_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/users/{user_id}/permissions"


def _denied_code(response: object) -> str:
    return str(response.json()["detail"]["code"])  # type: ignore[attr-defined]


def _role_id(rbac: RbacApi, session: ActorSession, code: str) -> uuid.UUID:
    return rbac.role_id_for(tenant_id=session.tenant_id, code=code)  # type: ignore[arg-type]


def test_a_caller_without_the_permission_is_refused_and_changes_nothing(
    rbac: RbacApi,
) -> None:
    """Deny by default: a caller without `users:manage` is refused on every route and writes nothing."""
    owner = rbac.register_tenant(clinic_name="Denial Clinic")
    assert owner.tenant_id is not None
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    pharmacy = rbac.add_actor(
        tenant_id=owner.tenant_id,
        granted_by=owner.user_id,
        role_code="PHARMACY",
    )
    doctor_role = _role_id(rbac, owner, "DOCTOR")

    assert rbac.client.get(ROLES_URL, headers=pharmacy.headers).status_code == 403
    assert rbac.client.get(PERMISSIONS_URL, headers=pharmacy.headers).status_code == 403
    assert (
        rbac.client.get(
            _user_roles_url(target.user_id), headers=pharmacy.headers
        ).status_code
        == 403
    )
    assert (
        rbac.client.get(
            _user_permissions_url(target.user_id), headers=pharmacy.headers
        ).status_code
        == 403
    )

    refused_assign = rbac.client.post(
        _user_roles_url(target.user_id),
        json={"role_id": str(doctor_role)},
        headers=pharmacy.headers,
    )
    assert refused_assign.status_code == 403
    assert _denied_code(refused_assign) == "PERMISSION_NOT_HELD"
    assert (
        rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=target.user_id) == []
    ), "a refused assignment still wrote a row"

    refused_revoke = rbac.client.delete(
        f"{_user_roles_url(target.user_id)}/{doctor_role}", headers=pharmacy.headers
    )
    assert refused_revoke.status_code == 403
    assert _denied_code(refused_revoke) == "PERMISSION_NOT_HELD"


def test_an_account_with_no_role_is_refused_the_same_way(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="No Role Clinic")
    assert owner.tenant_id is not None
    nobody = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    assert rbac.client.get(ROLES_URL, headers=nobody.headers).status_code == 403


def test_a_caller_with_the_permission_lists_roles_with_their_bundles(
    rbac: RbacApi,
) -> None:
    """R1: a role is a bundle of permission codes; the route never branches on a role name."""
    owner = rbac.register_tenant(clinic_name="Bundle Clinic")
    assert owner.tenant_id is not None

    response = rbac.client.get(ROLES_URL, headers=owner.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 7
    bundles = {
        role["code"]: {p["code"] for p in role["permissions"]} for role in body["data"]
    }
    assert set(bundles) == {
        "PRACTICE_OWNER",
        "AUTHORISED_PRESCRIBER",
        "DOCTOR",
        "NURSE",
        "ADMINISTRATOR",
        "PHARMACY",
        "COMPLIANCE_AUDITOR",
    }
    assert "prescription:sign" in bundles["DOCTOR"]
    assert "tenant:configure" not in bundles["DOCTOR"]
    assert bundles["PHARMACY"] == {"patient:read", "pharmacy:dispatch"}


def test_a_caller_with_the_permission_lists_the_permission_catalogue(
    rbac: RbacApi,
) -> None:
    """R7: the catalogue is global reference data, read-only, and the declared codes.

    **20, not 19, and the twentieth is the one recorded deviation**: `tenant:read`, which
    `01-tenancy-and-clinics/03-design.md` "Endpoints" requires for `GET /api/v1/tenants/current` and
    records as OPEN-2 ("absent from the fixed 19-permission catalogue"). It is named here rather than
    left to `catalog.py` so the count stays a check on the catalogue instead of a restatement of it.
    """
    owner = rbac.register_tenant(clinic_name="Catalogue Clinic")
    assert owner.tenant_id is not None

    response = rbac.client.get(PERMISSIONS_URL, headers=owner.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 20
    codes = [permission["code"] for permission in body["data"]]
    assert len(set(codes)) == 20
    assert "users:manage" in codes
    # The one code beyond the 19 of `01-requirements.md`.
    assert "tenant:read" in codes
    # A candidate code is never granted (OPEN-1).
    assert "role:manage" not in codes
    assert "admin:feature_flag" not in codes


def test_assigning_a_role_grants_the_permission_and_revoking_removes_it(
    rbac: RbacApi,
) -> None:
    """R2 and the design's `ROLE_ASSIGNED`/`ROLE_REVOKED` flow: no cache, no new login needed."""
    owner = rbac.register_tenant(clinic_name="Assignment Clinic")
    assert owner.tenant_id is not None
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    doctor_role = _role_id(rbac, owner, "DOCTOR")

    # Before the grant the account holds no permission at all, so the patient list is refused.
    assert rbac.client.get(PATIENTS_URL, headers=target.headers).status_code == 403

    granted = rbac.client.post(
        _user_roles_url(target.user_id),
        json={"role_id": str(doctor_role)},
        headers=owner.headers,
    )
    assert granted.status_code == 201, granted.text
    assert granted.json()["code"] == "DOCTOR"
    assert granted.json()["permissions"], "the granted role returned an empty bundle"

    # The permission set is recomputed on every request: the existing token now authorises.
    assert rbac.client.get(PATIENTS_URL, headers=target.headers).status_code == 200
    assert rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=target.user_id) == [
        "DOCTOR"
    ]

    listed = rbac.client.get(_user_roles_url(target.user_id), headers=owner.headers)
    assert listed.status_code == 200, listed.text
    assert [role["code"] for role in listed.json()["data"]] == ["DOCTOR"]

    effective = rbac.client.get(
        _user_permissions_url(target.user_id), headers=owner.headers
    )
    assert effective.status_code == 200, effective.text
    assert "patient:read" in {
        permission["code"] for permission in effective.json()["permissions"]
    }

    revoked = rbac.client.delete(
        f"{_user_roles_url(target.user_id)}/{doctor_role}", headers=owner.headers
    )
    assert revoked.status_code == 204, revoked.text
    assert (
        rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=target.user_id) == []
    ), "the revoke did not remove the assignment"
    # The user loses the permission immediately, on the same token.
    assert rbac.client.get(PATIENTS_URL, headers=target.headers).status_code == 403


def test_revoking_an_assignment_that_does_not_exist_is_404(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="Revoke Twice Clinic")
    assert owner.tenant_id is not None
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    doctor_role = _role_id(rbac, owner, "DOCTOR")
    url = f"{_user_roles_url(target.user_id)}/{doctor_role}"

    assert rbac.client.delete(url, headers=owner.headers).status_code == 404
    assert (
        rbac.client.post(
            _user_roles_url(target.user_id),
            json={"role_id": str(doctor_role)},
            headers=owner.headers,
        ).status_code
        == 201
    )
    assert rbac.client.delete(url, headers=owner.headers).status_code == 204
    assert rbac.client.delete(url, headers=owner.headers).status_code == 404


def test_assigning_the_same_role_twice_is_idempotent(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="Idempotent Grant Clinic")
    assert owner.tenant_id is not None
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    doctor_role = _role_id(rbac, owner, "DOCTOR")
    body = {"role_id": str(doctor_role)}

    first = rbac.client.post(
        _user_roles_url(target.user_id), json=body, headers=owner.headers
    )
    second = rbac.client.post(
        _user_roles_url(target.user_id), json=body, headers=owner.headers
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=target.user_id) == [
        "DOCTOR"
    ], "a repeated assignment duplicated a row"


def test_the_effective_set_is_the_union_of_the_accounts_roles(rbac: RbacApi) -> None:
    """R1: effective permissions are the union of the actor's role bundles."""
    owner = rbac.register_tenant(clinic_name="Union Clinic")
    assert owner.tenant_id is not None
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    for code in ("DOCTOR", "PHARMACY"):
        granted = rbac.client.post(
            _user_roles_url(target.user_id),
            json={"role_id": str(_role_id(rbac, owner, code))},
            headers=owner.headers,
        )
        assert granted.status_code == 201, granted.text

    effective = rbac.client.get(
        _user_permissions_url(target.user_id), headers=owner.headers
    )
    assert effective.status_code == 200, effective.text
    codes = {permission["code"] for permission in effective.json()["permissions"]}
    assert "prescription:sign" in codes, "the DOCTOR bundle was not included"
    assert "pharmacy:dispatch" in codes, "the PHARMACY bundle was not included"
    assert effective.json()["count"] == len(codes)


def test_a_caller_cannot_grant_a_permission_they_do_not_hold(rbac: RbacApi) -> None:
    """R3 / S5: an Administrator holds `users:manage` but not `tenant:configure`."""
    owner = rbac.register_tenant(clinic_name="Escalation Clinic")
    assert owner.tenant_id is not None
    administrator = rbac.add_actor(
        tenant_id=owner.tenant_id,
        granted_by=owner.user_id,
        role_code="ADMINISTRATOR",
    )
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    practice_owner_role = _role_id(rbac, owner, "PRACTICE_OWNER")

    # The PRACTICE_OWNER bundle contains `tenant:configure`, which the Administrator does not hold.
    refused = rbac.client.post(
        _user_roles_url(target.user_id),
        json={"role_id": str(practice_owner_role)},
        headers=administrator.headers,
    )
    assert refused.status_code == 403, refused.text
    assert _denied_code(refused) == "GRANT_EXCEEDS_ACTOR"
    assert (
        rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=target.user_id) == []
    ), "a refused escalation still wrote a grant"

    # S7: the same rule refuses a self-grant, so an actor cannot promote themselves.
    self_grant = rbac.client.post(
        _user_roles_url(administrator.user_id),
        json={"role_id": str(practice_owner_role)},
        headers=administrator.headers,
    )
    assert self_grant.status_code == 403, self_grant.text
    assert _denied_code(self_grant) == "GRANT_EXCEEDS_ACTOR"
    assert rbac.assignment_codes(
        tenant_id=owner.tenant_id, user_id=administrator.user_id
    ) == ["ADMINISTRATOR"], "a refused self-grant widened the actor's roles"

    # A bundle the actor does hold is still granted: the rule is not "Administrators cannot assign".
    administrator_role = _role_id(rbac, owner, "ADMINISTRATOR")
    allowed = rbac.client.post(
        _user_roles_url(target.user_id),
        json={"role_id": str(administrator_role)},
        headers=administrator.headers,
    )
    assert allowed.status_code == 201, allowed.text


def test_a_body_field_the_design_does_not_expose_is_422(rbac: RbacApi) -> None:
    """S14: `tenant_id`, `granted_by` and `user_id` are not assignable through the body."""
    owner = rbac.register_tenant(clinic_name="Mass Assignment Clinic")
    assert owner.tenant_id is not None
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    doctor_role = str(_role_id(rbac, owner, "DOCTOR"))
    url = _user_roles_url(target.user_id)

    for forged in (
        {"role_id": doctor_role, "tenant_id": str(uuid.uuid4())},
        {"role_id": doctor_role, "granted_by": str(owner.user_id)},
        {"role_id": doctor_role, "user_id": str(target.user_id)},
        {"role_id": doctor_role, "granted_at": "2026-01-01T00:00:00Z"},
        {"role_id": doctor_role, "id": str(uuid.uuid4())},
    ):
        response = rbac.client.post(url, json=forged, headers=owner.headers)
        assert response.status_code == 422, response.text
        extra = set(forged) - {"role_id"}
        assert any(field in response.text for field in extra), (
            f"{sorted(extra)} was silently ignored rather than rejected: {response.text}"
        )
    assert (
        rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=target.user_id) == []
    )

    assert rbac.client.post(url, json={}, headers=owner.headers).status_code == 422


def test_revoking_the_last_role_granting_users_manage_is_409(rbac: RbacApi) -> None:
    """R8: the organisation cannot lose its last holder of `users:manage`.

    `PRACTICE_OWNER` is the tenant's first account and the only role granting `users:manage` here, so
    removing it would leave nobody able to manage users. A refusal must also remove nothing, and the
    tenant must still be able to manage users afterwards — a `409` that had already deleted the row
    would be a lockout with extra steps.
    """
    owner = rbac.register_tenant(clinic_name="Last Administrator Clinic")
    assert owner.tenant_id is not None
    practice_owner_role = _role_id(rbac, owner, "PRACTICE_OWNER")

    refused = rbac.client.delete(
        f"{_user_roles_url(owner.user_id)}/{practice_owner_role}", headers=owner.headers
    )
    assert refused.status_code == 409, refused.text
    assert _denied_code(refused) == "LAST_ADMINISTRATOR"
    assert rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=owner.user_id) == [
        "PRACTICE_OWNER"
    ], "a refused last-administrator revoke removed the assignment"
    assert rbac.client.get(ROLES_URL, headers=owner.headers).status_code == 200


def test_revoking_a_granting_role_is_allowed_while_another_holder_remains(
    rbac: RbacApi,
) -> None:
    """R8 refuses the *last* granting role, not every granting role.

    The owner grants `ADMINISTRATOR` to a second account — a bundle the owner holds — and only then
    gives up `PRACTICE_OWNER`. The organisation still has an administrator, so the revoke is `204`.
    """
    owner = rbac.register_tenant(clinic_name="Second Administrator Clinic")
    assert owner.tenant_id is not None
    other = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    administrator_role = _role_id(rbac, owner, "ADMINISTRATOR")
    practice_owner_role = _role_id(rbac, owner, "PRACTICE_OWNER")

    granted = rbac.client.post(
        _user_roles_url(other.user_id),
        json={"role_id": str(administrator_role)},
        headers=owner.headers,
    )
    assert granted.status_code == 201, granted.text

    revoked = rbac.client.delete(
        f"{_user_roles_url(owner.user_id)}/{practice_owner_role}", headers=owner.headers
    )
    assert revoked.status_code == 204, revoked.text
    assert rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=owner.user_id) == []
    # The new administrator can still reach the administration API.
    assert rbac.client.get(ROLES_URL, headers=other.headers).status_code == 200


def test_revoking_a_role_that_does_not_grant_users_manage_is_unaffected(
    rbac: RbacApi,
) -> None:
    """R8 bites on the administering permission only; a clinical role revokes as before."""
    owner = rbac.register_tenant(clinic_name="Clinical Revoke Clinic")
    assert owner.tenant_id is not None
    target = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
    doctor_role = _role_id(rbac, owner, "DOCTOR")

    granted = rbac.client.post(
        _user_roles_url(target.user_id),
        json={"role_id": str(doctor_role)},
        headers=owner.headers,
    )
    assert granted.status_code == 201, granted.text
    revoked = rbac.client.delete(
        f"{_user_roles_url(target.user_id)}/{doctor_role}", headers=owner.headers
    )
    assert revoked.status_code == 204, revoked.text
    assert (
        rbac.assignment_codes(tenant_id=owner.tenant_id, user_id=target.user_id) == []
    )
