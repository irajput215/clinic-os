"""Test-only helper: register through the real signup flow, emailed link included (D-007).

A signup creates nothing until its emailed link is used, so a test that needs an organisation posts
`POST /users/signup`, reads the link out of the email the app tried to send (captured, never sent),
and spends it at `POST /users/signup/verify`, which answers the owner's access token. Nothing here is
production behaviour.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings

API = settings.API_V1_STR
SIGNUP_URL = f"{API}/users/signup"
VERIFY_URL = f"{API}/users/signup/verify"
_LINK = re.compile(r"/verify-email\?token=([A-Za-z0-9._-]+)")


def link_token(html_content: str) -> str | None:
    """The token of the verification link in an email, or `None` when it carries none."""
    found = _LINK.search(html_content)
    return None if found is None else found.group(1)


def request_signup(
    client: TestClient, payload: dict[str, Any]
) -> tuple[Any, list[dict[str, Any]]]:
    """Post a signup with outgoing mail captured; the response and every email it tried to send."""
    sent: list[dict[str, Any]] = []
    with patch(
        "app.utils.send_email", side_effect=lambda **message: sent.append(message)
    ):
        response = client.post(SIGNUP_URL, json=payload)
    return response, sent


@dataclass(frozen=True)
class SignedUp:
    """A verified signup: the owner's id, organisation (None when unattached) and session."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def sign_up(client: TestClient, payload: dict[str, Any]) -> SignedUp:
    """Sign up and verify through the API, exactly as a person following the email would."""
    response, sent = request_signup(client, payload)
    assert response.status_code == 202, response.text
    (message,) = sent
    token = link_token(message["html_content"])
    assert token, "the signup email carries no verification link"
    verified = client.post(VERIFY_URL, json={"token": token})
    assert verified.status_code == 200, verified.text
    access_token = verified.json()["access_token"]
    me = client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {access_token}"}
    ).json()
    return SignedUp(
        user_id=uuid.UUID(me["id"]),
        tenant_id=uuid.UUID(me["tenant_id"]) if me["tenant_id"] else None,
        token=access_token,
    )
