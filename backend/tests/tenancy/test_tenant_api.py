"""The tenancy API: `GET` and `PATCH /api/v1/tenants/current`.

Design: `docs/features/01-tenancy-and-clinics/03-design.md`, "Endpoints" and "Deny-by-default request
path". Requirements: R1 (tenant resolved, never supplied), R9 (`404`, never `403`), R12 (a security
change needs step-up), R15 (administrative rate class), and user stories US-1/US-2/US-5 in
`02-user-stories.md`. Scenarios F1, F2, F12 and S12 in `06-test-plan.md`.

The denial paths come first (`docs/reference/definition-of-done.md` §9): a route that only works is not
evidence. Both routes are asserted for the unauthenticated case, the no-organisation case, the
missing-permission case, a supplied tenant value, and the step-up refusal that is the only outcome the
`PATCH` can produce while feature 02 is blocked by D-003.

**Audit is deferred** to feature 04 and is asserted as such rather than faked: no test here writes or
reads an audit row, and the deferred event names are declared on the router module.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.modules.identity_tenancy.router import (
    STEP_UP_REQUIRED,
    _current_tenant,
    _tenant_not_found,
)
from tests.utils.rbac import RbacApi

TENANTS_URL = f"{settings.API_V1_STR}/tenants/current"

# The columns `clinos_app` is granted on `tenants` (`03-design.md`, "Database privileges"), which is
# exactly what the response may carry: `retention_profile` is withheld from the application role and
# `legal_name` is not in the grant either.
EXPECTED_RESPONSE_FIELDS = {
    "id",
    "slug",
    "status",
    "data_region",
    "created_at",
    "updated_at",
}


@pytest.fixture
def rbac(client: TestClient, db: Session) -> Iterator[RbacApi]:
    helper = RbacApi(client, db)
    yield helper
    helper.cleanup()


def _tenant_row(tenant_id: uuid.UUID) -> dict[str, object]:
    """Read the tenant as the owner, for "the row did not change" assertions."""
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT slug, legal_name, status, data_region, retention_profile, updated_at"
                    " FROM tenants WHERE id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
            .mappings()
            .one()
        )
        return dict(row)


def test_get_tenants_current_resolves_from_session(rbac: RbacApi) -> None:
    """F1/US-1: the resolved tenant only, with `status` and `data_region`."""
    owner = rbac.register_tenant(clinic_name="Northside Family Clinic")
    assert owner.tenant_id is not None

    response = rbac.client.get(TENANTS_URL, headers=owner.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(owner.tenant_id)
    assert body["slug"] == "northside-family-clinic"
    assert body["status"] == "ACTIVE"
    assert body["data_region"] == "ap-southeast-2"


def test_get_tenants_current_never_returns_a_withheld_column(rbac: RbacApi) -> None:
    """US-1: "`retention_profile` is never returned to the application surface"."""
    owner = rbac.register_tenant(clinic_name="Withheld Column Clinic")
    assert owner.tenant_id is not None

    response = rbac.client.get(TENANTS_URL, headers=owner.headers)

    assert set(response.json()) == EXPECTED_RESPONSE_FIELDS
    assert "retention_profile" not in response.text
    # `legal_name` is CONFIDENTIAL and outside the application role's column grant as well.
    assert "legal_name" not in response.text


def test_another_tenants_identifier_changes_nothing(rbac: RbacApi) -> None:
    """R1/US-5: a supplied tenant value is ignored, so the caller gets its own data back."""
    alpha = rbac.register_tenant(clinic_name="Alpha Tenancy")
    beta = rbac.register_tenant(clinic_name="Beta Tenancy")
    assert alpha.tenant_id is not None and beta.tenant_id is not None

    response = rbac.client.get(
        f"{TENANTS_URL}?tenant_id={beta.tenant_id}",
        headers={**alpha.headers, "X-Tenant-Id": str(beta.tenant_id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(alpha.tenant_id)
    # The dropped value is not audited: feature 04 owns the writer and no second one is invented here.
    # `TENANT_CROSS_ACCESS_ATTEMPT` is the event the router declaration names.


def test_get_requires_authentication(rbac: RbacApi) -> None:
    assert rbac.client.get(TENANTS_URL).status_code == 401


def test_an_account_without_an_organisation_is_refused(rbac: RbacApi) -> None:
    account = rbac.register_tenant(clinic_name=None)
    assert account.tenant_id is None

    response = rbac.client.get(TENANTS_URL, headers=account.headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NO_ORGANISATION"


def test_a_role_without_tenant_read_is_refused(rbac: RbacApi) -> None:
    """`tenant:read` is granted to `PRACTICE_OWNER` (US-1) and `COMPLIANCE_AUDITOR` (US-7) only."""
    owner = rbac.register_tenant(clinic_name="Tenant Read Clinic")
    assert owner.tenant_id is not None

    doctor = rbac.add_actor(
        tenant_id=owner.tenant_id,
        granted_by=owner.user_id,
        role_code="DOCTOR",
    )
    refused = rbac.client.get(TENANTS_URL, headers=doctor.headers)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "PERMISSION_NOT_HELD"

    auditor = rbac.add_actor(
        tenant_id=owner.tenant_id,
        granted_by=owner.user_id,
        role_code="COMPLIANCE_AUDITOR",
    )
    allowed = rbac.client.get(TENANTS_URL, headers=auditor.headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["id"] == str(owner.tenant_id)


def test_patch_requires_authentication(rbac: RbacApi) -> None:
    assert rbac.client.patch(TENANTS_URL, json={}).status_code == 401


def test_patch_rejects_a_body_tenant_id(rbac: RbacApi) -> None:
    """INV-1 and the design's step 6: an unknown field is `422`, so the value never reaches a query."""
    owner = rbac.register_tenant(clinic_name="Forged Body Clinic")
    assert owner.tenant_id is not None

    response = rbac.client.patch(
        TENANTS_URL,
        json={"tenant_id": str(uuid.uuid4())},
        headers=owner.headers,
    )

    assert response.status_code == 422, response.text
    assert "tenant_id" in response.text
    assert _tenant_row(owner.tenant_id)["legal_name"] == "Forged Body Clinic"


def test_patch_without_step_up_is_refused(rbac: RbacApi) -> None:
    """R12: the change requires a fresh factor, and the factor does not exist yet (D-003).

    The route refuses `403 STEP_UP_REQUIRED` for the one actor who holds `tenant:configure`, and writes
    nothing. That is the whole behaviour of this route in this slice, and it is the design's rule
    enforced at its most restrictive: no step-up, no change.
    """
    owner = rbac.register_tenant(clinic_name="Step Up Clinic")
    assert owner.tenant_id is not None
    before = _tenant_row(owner.tenant_id)

    response = rbac.client.patch(TENANTS_URL, json={}, headers=owner.headers)

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == STEP_UP_REQUIRED
    assert _tenant_row(owner.tenant_id) == before


def test_patch_without_the_permission_is_refused(rbac: RbacApi) -> None:
    """The permission check runs before the step-up refusal.

    `ADMINISTRATOR` holds `users:manage` and does **not** hold `tenant:configure`
    (`01-requirements.md`, "Permission catalogue"; `03-design.md`, "The grantability rule (R3)"), so the
    answer is `PERMISSION_NOT_HELD` and never the step-up code.
    """
    owner = rbac.register_tenant(clinic_name="Administrator Clinic")
    assert owner.tenant_id is not None
    administrator = rbac.add_actor(
        tenant_id=owner.tenant_id,
        granted_by=owner.user_id,
        role_code="ADMINISTRATOR",
    )
    before = _tenant_row(owner.tenant_id)

    response = rbac.client.patch(TENANTS_URL, json={}, headers=administrator.headers)

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"
    assert _tenant_row(owner.tenant_id) == before


def test_the_tenancy_routes_are_rate_limited(rbac: RbacApi) -> None:
    """R15/S12: `/api/v1/tenants/*` is the administrative class, 20 per minute, `429` with `Retry-After`."""
    owner = rbac.register_tenant(clinic_name="Rate Limit Clinic")
    assert owner.tenant_id is not None

    for _ in range(20):
        assert rbac.client.get(TENANTS_URL, headers=owner.headers).status_code == 200

    refused = rbac.client.get(TENANTS_URL, headers=owner.headers)
    assert refused.status_code == 429
    assert "Retry-After" in refused.headers


def test_the_tenant_read_returns_none_for_an_unknown_tenant() -> None:
    """The fail-closed branch the foreign key makes unreachable through the API.

    A tenant row cannot be absent for an authenticated account (`user.tenant_id` is `ON DELETE SET
    NULL`, so deleting the organisation detaches the account instead of dangling), but the read still
    answers `None` rather than inventing a tenant, so the route can refuse it. Called directly, because
    no request can produce the state.
    """
    assert _current_tenant(tenant_id=uuid.uuid4()) is None
    refusal = _tenant_not_found()
    assert refusal.status_code == 404
    assert refusal.detail == {"code": "NOT_FOUND", "message": "Tenant not found"}
