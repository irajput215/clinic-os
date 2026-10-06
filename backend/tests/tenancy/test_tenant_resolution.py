"""Tenant status is enforced when the request's tenant is resolved.

`docs/features/01-tenancy-and-clinics/01-requirements.md` R10 — *"A `SUSPENDED` tenant is refused on
every request even with a valid unexpired session"* — and the design's deny-by-default path step 2:
*"Resolve tenant from the verified token claim and the addressed resource; enforce `status = ACTIVE`
at resolution — deny if unresolvable or suspended."*

The refusal belongs where the actor is built (`app.api.deps.get_actor`), because that is the only place
a request resolves a tenant at all: every route that reads or writes tenant data depends on `ActorDep`.
The refusal is `403` with the same machine-readable detail shape as `NO_ORGANISATION`, and it is one
code for every non-`ACTIVE` status — including "no such tenant row" — so a caller cannot learn from the
response whether their organisation exists, still exists, or is merely suspended.

Two pre-tenancy routes build no actor: `GET /api/v1/users/me` and `POST /api/v1/login/test-token` take
`CurrentUser` alone. They resolve no tenant and read no tenant data; they return the caller's own
account record. Extending the refusal to them is a one-line move of the check into
`get_current_user`, recorded as a gap in the pull request rather than taken silently.

Status is re-read on every request, so a reactivated organisation is served again without a new login
(R2: no cached authorisation across requests).
"""

import uuid

import pytest
from sqlmodel import Session

from app.api.deps import TENANT_NOT_ACTIVE
from app.core.config import settings
from app.core.db import engine
from app.modules.identity_tenancy.models import Tenant
from app.modules.identity_tenancy.service import is_active_status, tenant_is_active
from tests.utils.rbac import RbacApi

API = settings.API_V1_STR

# One route from each actor-scoped family: the clinical read path and the RBAC read path. Both depend
# on `ActorDep`, which is where the refusal lives.
ACTOR_SCOPED_ROUTES = (f"{API}/patients", f"{API}/roles")


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

    # No disclosure beyond what the caller already knows: the refusal names the condition, never the
    # organisation, its slug, or which non-ACTIVE status it is in.
    body = response.text.lower()
    assert "suspended clinic" not in body
    assert "suspended" not in body
    assert "slug" not in body
    assert response.json()["detail"]["message"] == "This organisation is not active"


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
