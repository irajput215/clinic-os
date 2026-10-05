"""T1-29 — authorisation is recomputed server-side, never cached from a previous request.

Requirement R2 and threat T-03.5: a role that is granted after a request authorises the next request,
and a role that is revoked stops authorising immediately. Nothing is served from a previous request's
decision, and the permission set is resolved from `user_roles -> role_permissions` each time.

The route is called between the two states without a new login, so a cached decision would keep
returning `200`.
"""

import uuid

from app.core.config import settings
from tests.utils.rbac import RbacApi

PATIENTS_URL = f"{settings.API_V1_STR}/patients"

DEFAULT_PATIENT: dict[str, str] = {
    "given_name": "Ada",
    "family_name": "Synthetic",
    "date_of_birth": "1990-01-01",
}


def test_a_tightened_permission_set_takes_effect_on_the_next_request(
    rbac: RbacApi,
) -> None:
    owner = rbac.register_tenant(clinic_name="Recompute Clinic")
    assert owner.tenant_id is not None
    created = rbac.client.post(
        PATIENTS_URL, json=DEFAULT_PATIENT, headers=owner.headers
    )
    assert created.status_code == 201, created.text
    patient_id = created.json()["id"]

    # An account with no role at all is denied.
    actor = rbac.add_actor(
        tenant_id=owner.tenant_id,
        granted_by=owner.user_id,
        role_code=None,
    )
    read_url = f"{PATIENTS_URL}/{patient_id}"
    assert rbac.client.get(read_url, headers=actor.headers).status_code == 403

    # Granting the role authorises the very next request, without a new login.
    rbac.grant(
        tenant_id=owner.tenant_id,
        user_id=actor.user_id,
        role_code="ADMINISTRATOR",
        granted_by=owner.user_id,
    )
    assert rbac.client.get(read_url, headers=actor.headers).status_code == 200

    # Revoking it denies the next request again.
    rbac.revoke_all(tenant_id=owner.tenant_id, user_id=actor.user_id)
    assert rbac.client.get(read_url, headers=actor.headers).status_code == 403


def test_the_permission_set_is_derived_from_roles_not_from_the_token(
    rbac: RbacApi,
) -> None:
    """A valid access token alone is not authority; the route asks the policy layer each time."""
    owner = rbac.register_tenant(clinic_name="Token Clinic")
    assert owner.tenant_id is not None
    created = rbac.client.post(
        PATIENTS_URL, json=DEFAULT_PATIENT, headers=owner.headers
    )
    assert created.status_code == 201, created.text

    actor = rbac.add_actor(
        tenant_id=owner.tenant_id,
        granted_by=owner.user_id,
        role_code="PHARMACY",
    )
    # Pharmacy holds `patient:read` but not `patient:update` (the matrix's `G dc` and `-` cells).
    patient_id = created.json()["id"]
    assert (
        rbac.client.get(
            f"{PATIENTS_URL}/{patient_id}", headers=actor.headers
        ).status_code
        == 200
    )
    assert (
        rbac.client.patch(
            f"{PATIENTS_URL}/{patient_id}",
            json={"preferred_name": "not allowed"},
            headers=actor.headers,
        ).status_code
        == 403
    )
    assert rbac.patient_row(uuid.UUID(patient_id)) is not None
