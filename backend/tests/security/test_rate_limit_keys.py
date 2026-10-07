"""Whose budget a request spends.

The design limits the administrative class "per session" (`03-users-and-roles/04-threat-model.md`
T-03.11, `06-test-plan.md` S15) and tenancy routes "keyed on session and tenant"
(`01-tenancy-and-clinics/04-threat-model.md` T-TEN-10). A request with a session that verifies spends
that session's budget; anything else - no token, a forged one, an expired one - spends its client
address's, so an unauthenticated flood is bounded exactly as before.
"""

from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from tests.utils.rbac import RbacApi

ROLES_URL = f"{settings.API_V1_STR}/roles"


def _spend(client: TestClient, headers: dict[str, str], times: int) -> None:
    for _ in range(times):
        client.get(ROLES_URL, headers=headers)


def test_two_sessions_behind_one_address_have_their_own_budgets(rbac: RbacApi) -> None:
    """A clinic's staff share one office address; one administrator cannot exhaust another's budget."""
    first = rbac.register_tenant(clinic_name="First Budget Clinic")
    second = rbac.register_tenant(clinic_name="Second Budget Clinic")

    _spend(rbac.client, first.headers, 20)

    assert rbac.client.get(ROLES_URL, headers=first.headers).status_code == 429
    assert rbac.client.get(ROLES_URL, headers=second.headers).status_code == 200


def test_one_session_is_still_limited_at_twenty(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="Session Limit Clinic")

    _spend(rbac.client, owner.headers, 20)
    refused = rbac.client.get(ROLES_URL, headers=owner.headers)

    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) >= 1


def test_an_unverified_token_spends_the_address_budget(client: TestClient) -> None:
    """Rotating forged tokens does not buy a fresh budget: they all count against the address."""
    for index in range(20):
        forged = {"Authorization": f"Bearer not-a-token-{index}"}
        assert client.get(ROLES_URL, headers=forged).status_code == 401

    expired = create_access_token("someone", timedelta(minutes=-1))
    refused = client.get(ROLES_URL, headers={"Authorization": f"Bearer {expired}"})
    anonymous = client.get(ROLES_URL)

    assert refused.status_code == 429
    assert anonymous.status_code == 429
