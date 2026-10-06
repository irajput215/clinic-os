"""Tenant status is enforced when the request's tenant is resolved.

`docs/features/01-tenancy-and-clinics/01-requirements.md` R10 — *"A `SUSPENDED` tenant is refused on
every request even with a valid unexpired session"* — and the design's deny-by-default path step 2:
*"Resolve tenant from the verified token claim and the addressed resource; enforce `status = ACTIVE`
at resolution — deny if unresolvable or suspended."*

The refusal has two entry points, one implementation: `app.api.deps.get_actor` for every route that
resolves tenant-scoped data, and `app.api.deps.get_active_tenant_user` (`ActiveTenantUser`) for the
self-service routes that act on the caller's **own** account and build no actor. Both call the same
`_refuse_inactive_tenant`, so which statuses pass cannot drift between them. The superuser-only
administration routes (`/users/`, `/users/{user_id}`) are deliberately excluded: the platform
administrator legitimately holds no organisation. The refusal is `403` with the same machine-readable
detail shape as `NO_ORGANISATION`, and it is one code for every non-`ACTIVE` status — including "no
such tenant row" — so a caller cannot learn from the response whether their organisation exists, still
exists, or is merely suspended.

Status is re-read on every request, so a reactivated organisation is served again without a new login
(R2: no cached authorisation across requests).
"""

import uuid
from typing import Any

import pytest
from sqlmodel import Session

from app.api.deps import TENANT_NOT_ACTIVE
from app.core.config import settings
from app.core.db import engine
from app.modules.identity_tenancy.models import Tenant
from app.modules.identity_tenancy.service import is_active_status, tenant_is_active
from tests.utils.rbac import PASSWORD, RbacApi

API = settings.API_V1_STR

# One route from each actor-scoped family: the clinical read path and the RBAC read path. Both depend
# on `ActorDep`, which is where the refusal lives.
ACTOR_SCOPED_ROUTES = (f"{API}/patients", f"{API}/roles")

# Every self-service route the caller reaches as their own account. `GET /users/{user_id}` is absent
# on purpose: it shares the handler shape of the superuser-only administration surface, which a
# platform administrator with no organisation must still reach.
SELF_SERVICE_ROUTES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", f"{API}/users/me", None),
    ("POST", f"{API}/login/test-token", None),
    ("PATCH", f"{API}/users/me", {"full_name": "Renamed Owner"}),
    (
        "PATCH",
        f"{API}/users/me/password",
        {
            "current_password": PASSWORD,
            "new_password": "another-correct-horse-battery",
        },
    ),
    ("DELETE", f"{API}/users/me", None),
)


def _set_tenant_status(tenant_id: uuid.UUID, status: str) -> None:
    """Flip an organisation's status, as the deployment's own administrative path would.

    Written as the owner connection: no API in this slice changes a tenant's status (feature 15 owns
    that), and the test needs the state to exist, not a route to produce it.
    """
    with Session(engine) as session:
        tenant = session.get(Tenant, tenant_id)
        assert tenant is not None
        tenant.status = status
        session.add(tenant)
        session.commit()


def test_suspended_tenant_refused_on_every_request(rbac: RbacApi) -> None:
    """R10: refused even though the access token is valid and unexpired."""
    owner = rbac.register_tenant(clinic_name="Suspended Clinic")
    assert owner.tenant_id is not None

    # The control case comes first: the very same request is served while the organisation is ACTIVE,
    # so what the test observes afterwards is the status change and not the route.
    assert (
        rbac.client.get(ACTOR_SCOPED_ROUTES[0], headers=owner.headers).status_code
        == 200
    )

    _set_tenant_status(owner.tenant_id, "SUSPENDED")

    for route in ACTOR_SCOPED_ROUTES:
        response = rbac.client.get(route, headers=owner.headers)
        assert response.status_code == 403, route
        assert response.json()["detail"]["code"] == TENANT_NOT_ACTIVE

    # Every self-service route too: those build no actor, and before `ActiveTenantUser` they were the
    # last authenticated surface a suspended organisation could still reach.
    for method, route, payload in SELF_SERVICE_ROUTES:
        response = rbac.client.request(
            method, route, headers=owner.headers, json=payload
        )
        assert response.status_code == 403, (method, route)
        assert response.json()["detail"]["code"] == TENANT_NOT_ACTIVE

    # No disclosure beyond what the caller already knows: the refusal names the condition, never the
    # organisation, its slug, or which non-ACTIVE status it is in.
    body = response.text.lower()
    assert "suspended clinic" not in body
    assert "suspended" not in body
    assert "slug" not in body
    assert response.json()["detail"]["message"] == "This organisation is not active"


def test_an_active_tenant_is_served_on_the_self_service_routes(rbac: RbacApi) -> None:
    """The control case for the routes above: an ACTIVE organisation's account is untouched.

    A fresh account per route, because two of these routes change the account's own state
    (`PATCH /users/me/password`, `DELETE /users/me`) and one shared session would mask a failure
    behind the previous route's effect.
    """
    owner = rbac.register_tenant(clinic_name="Self Service Clinic")
    assert owner.tenant_id is not None

    for method, route, payload in SELF_SERVICE_ROUTES:
        actor = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)
        response = rbac.client.request(
            method, route, headers=actor.headers, json=payload
        )
        assert response.status_code == 200, (method, route, response.text)


@pytest.mark.parametrize("status", ["SUSPENDED", "CLOSING", "CLOSED"])
def test_every_non_active_status_is_refused(rbac: RbacApi, status: str) -> None:
    """The allow-list is `ACTIVE`; `CLOSING` and `CLOSED` are refused exactly as `SUSPENDED` is."""
    owner = rbac.register_tenant(clinic_name=f"{status.title()} Clinic")
    assert owner.tenant_id is not None

    _set_tenant_status(owner.tenant_id, status)

    response = rbac.client.get(f"{API}/patients", headers=owner.headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == TENANT_NOT_ACTIVE


def test_a_reactivated_tenant_is_served_again(rbac: RbacApi) -> None:
    """Status is read per request: no cached authorisation survives the suspension (R2)."""
    owner = rbac.register_tenant(clinic_name="Reactivated Clinic")
    assert owner.tenant_id is not None

    _set_tenant_status(owner.tenant_id, "SUSPENDED")
    assert rbac.client.get(f"{API}/patients", headers=owner.headers).status_code == 403

    _set_tenant_status(owner.tenant_id, "ACTIVE")
    assert rbac.client.get(f"{API}/patients", headers=owner.headers).status_code == 200


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ACTIVE", True),
        ("SUSPENDED", False),
        ("CLOSING", False),
        ("CLOSED", False),
        ("ROGUE", False),
        ("", False),
        (None, False),
    ],
)
def test_only_the_active_status_passes(status: str | None, expected: bool) -> None:
    """Fail closed for any unknown status: the check is an allow-list of one value."""
    assert is_active_status(status) is expected


def test_an_unknown_tenant_fails_closed() -> None:
    """A tenant row that cannot be read is refused, not defaulted to active."""
    with Session(engine) as session:
        assert tenant_is_active(session, tenant_id=uuid.uuid4()) is False
