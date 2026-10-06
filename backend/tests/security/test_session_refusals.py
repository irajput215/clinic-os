"""What the API answers a session that cannot be used, versus one that simply may not do this.

`docs/features/03-users-and-roles/01-requirements.md` R5 — *"the deactivated user's next request
returns `401`"* — and R6. `app.api.deps.get_current_user` answers `401` for **every** unusable
session (a token that does not verify, an account that no longer exists, a deactivated account) and
`403` only when the session is valid and the identity is refused. That split is the contract the
client relies on: it signs out on `401` and keeps every other status on the page, so a session
problem reported as `403` or `404` leaves a signed-in user on a screen that will never load.

Before this file, `get_current_user` answered `403` and `404` for those cases, and the patients
screen was the visible cost: opening it with an account that had no organisation cleared the token
and bounced the user to sign-in, in a loop.
"""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.security import create_access_token
from app.models import UserCreate
from tests.utils.rbac import RbacApi
from tests.utils.utils import random_email, random_lower_string

API = settings.API_V1_STR


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token_for(subject: uuid.UUID) -> str:
    return create_access_token(str(subject), timedelta(minutes=5))


def test_a_token_that_does_not_verify_is_401(client: TestClient) -> None:
    response = client.get(f"{API}/users/me", headers=_bearer("not-a-jwt"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_no_token_at_all_is_401(client: TestClient) -> None:
    assert client.get(f"{API}/users/me").status_code == 401


def test_a_token_for_an_account_that_no_longer_exists_is_401(
    client: TestClient,
) -> None:
    """A deleted account's live token is a dead session, not a missing record."""
    response = client.get(f"{API}/users/me", headers=_bearer(_token_for(uuid.uuid4())))
    assert response.status_code == 401


def test_a_deactivated_account_is_401(client: TestClient, db: Session) -> None:
    """R5: the deactivated user's next request returns `401`."""
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=random_lower_string(),
            is_active=False,
        ),
    )
    db.refresh(user)
    response = client.get(f"{API}/users/me", headers=_bearer(_token_for(user.id)))
    assert response.status_code == 401
    assert response.json()["detail"] == "Inactive user"


def test_an_account_with_no_organisation_is_403_with_a_reason_code(
    client: TestClient, db: Session
) -> None:
    """The session is valid; the identity cannot be scoped. That is a `403`, never a sign-out."""
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    db.refresh(user)
    response = client.get(f"{API}/patients", headers=_bearer(_token_for(user.id)))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NO_ORGANISATION"


def test_a_role_without_the_permission_is_403_permission_not_held(
    rbac: RbacApi,
) -> None:
    """The other `403`: a valid session inside a tenant, holding no role at all."""
    owner = rbac.register_tenant(clinic_name="Refusal Clinic")
    assert owner.tenant_id is not None
    outsider = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)

    response = rbac.client.get(f"{API}/patients", headers=outsider.headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"
