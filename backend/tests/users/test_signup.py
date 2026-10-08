"""Organisation signup verified by email: `POST /users/signup`, `/signup/resend`, `/signup/verify`.

Decision: `docs/reference/decisions/D-007-signup-email-verification.md`; contract:
`docs2/sdlc/01-auth-and-shell/api.md`. Nothing exists until the emailed link is used; every address
gets the same answer and the same work; a taken address's owner gets a notice, never a link.

Denial path first (`docs/reference/definition-of-done.md` §9): closed registration, no outgoing mail,
unknown keys, a taken address (which must look exactly like a new one), every kind of bad link, a
second signup for the same address, and the rate limits. Then the success path and the expiry purge.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.rate_limit import limiter
from app.core.security import create_access_token, verify_password
from app.modules.users_roles import signup
from app.modules.users_roles.models import SignupRequest
from tests.utils.rbac import RbacApi
from tests.utils.signup import VERIFY_URL, link_token, request_signup

API = settings.API_V1_STR
SIGNUP_URL = f"{API}/users/signup"
RESEND_URL = f"{API}/users/signup/resend"
LOGIN_URL = f"{API}/login/access-token"
PASSWORD = "correct-horse-battery-staple"
# The resend route's one answer, whatever the id.
RESENT = "If that signup is still waiting, its email is on its way again."


@pytest.fixture(autouse=True)
def _no_leftover_requests() -> Iterator[None]:
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM signup_requests"))


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "email": f"signup-{uuid.uuid4()}@example.com",
        "password": PASSWORD,
        "full_name": "Dr Ana Petrovic",
        "clinic_name": f"Wattle Clinic {uuid.uuid4()}",
    } | overrides


def _requests(email: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM signup_requests WHERE email_key = lower(:email)"
                " ORDER BY created_at"
            ),
            {"email": email},
        ).mappings()
        return [dict(row) for row in rows]


def _account(email: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    'SELECT id, tenant_id, hashed_password FROM "user"'
                    " WHERE lower(email) = lower(:email)"
                ),
                {"email": email},
            )
            .mappings()
            .first()
        )
        return None if row is None else dict(row)


def _verify(client: TestClient, token: str | None) -> Any:
    return client.post(VERIFY_URL, json={"token": token})


def _signed_up(client: TestClient, **overrides: Any) -> tuple[dict[str, Any], str]:
    """Post a signup and return its payload and the emailed link's token, untouched."""
    payload = _payload(**overrides)
    response, sent = request_signup(client, payload)
    assert response.status_code == 202, response.text
    (message,) = sent
    token = link_token(message["html_content"])
    assert token is not None
    return payload, token


def _track(rbac: RbacApi, email: str) -> None:
    """Hand a verified account's organisation to the fixture's cleanup."""
    account = _account(email)
    if account is not None and account["tenant_id"] is not None:
        rbac._tenant_ids.append(account["tenant_id"])


@contextmanager
def _counting_statements() -> Iterator[list[str]]:
    """The kind (first word) of every SQL statement the app runs inside the block, in order."""
    kinds: list[str] = []

    def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        kinds.append(statement.split(None, 1)[0].upper())

    event.listen(engine, "before_cursor_execute", count)
    try:
        yield kinds
    finally:
        event.remove(engine, "before_cursor_execute", count)


def _code(response: Any) -> str:
    return str(response.json()["detail"]["code"])


# --- Denial path -------------------------------------------------------------------------------


def test_closed_registration_is_403_and_writes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", False)
    payload = _payload()
    response, sent = request_signup(client, payload)
    assert response.status_code == 403
    assert sent == []
    assert _requests(payload["email"]) == []


def test_no_outgoing_mail_is_503_and_writes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: an account nobody can verify is never created (nor its request)."""
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    payload = _payload()
    response, sent = request_signup(client, payload)
    assert response.status_code == 503
    assert _code(response) == "EMAIL_NOT_CONFIGURED"
    assert sent == []
    assert _requests(payload["email"]) == []
    resend = client.post(RESEND_URL, json={"request_id": str(uuid.uuid4())})
    assert resend.status_code == 503


def test_unknown_keys_are_422(client: TestClient) -> None:
    for extra in ({"tenant_id": str(uuid.uuid4())}, {"is_superuser": True}):
        payload = _payload() | extra
        response, sent = request_signup(client, payload)
        assert response.status_code == 422, extra
        assert sent == []
        assert _requests(payload["email"]) == []


def test_a_taken_address_gets_the_same_answer_and_a_notice(
    client: TestClient, rbac: RbacApi
) -> None:
    """No difference in status, body shape, headers or work tells a taken address from a new one."""
    owner = rbac.register_tenant(clinic_name="Taken Address Clinic")
    with _counting_statements() as fresh_statements:
        fresh, fresh_sent = request_signup(client, _payload())
    with _counting_statements() as taken_statements:
        taken, taken_sent = request_signup(
            client, _payload(email=owner.email.upper(), password="a-guess-at-it")
        )

    for response in (fresh, taken):
        assert response.status_code == 202
    assert set(fresh.json()) == set(taken.json()) == {"request_id", "expires_in_hours"}
    assert fresh.json()["expires_in_hours"] == taken.json()["expires_in_hours"]
    assert set(fresh.headers) == set(taken.headers)
    # The same database work on both paths (the Argon2 hash is on both too; see D-007), and no
    # `Server-Timing` on an unauthenticated route to measure it with.
    assert fresh_statements == taken_statements
    assert "server-timing" not in {key.lower() for key in taken.headers}

    # The owner of the taken address is told, and is given no link.
    (notice,) = taken_sent
    assert notice["email_to"] == owner.email, "to the address the account holds"
    assert "already have an account" in notice["subject"]
    assert link_token(notice["html_content"]) is None
    assert f"{settings.FRONTEND_HOST}/recover-password" in notice["html_content"]
    # Nothing the requester typed but the address reaches them.
    assert "Wattle Clinic" not in notice["html_content"]
    assert "Dr Ana Petrovic" not in notice["html_content"]
    (verification,) = fresh_sent
    assert link_token(verification["html_content"]) is not None

    # The request for the taken address keeps no password and nothing typed but the address.
    (stored,) = _requests(owner.email)
    assert stored["hashed_password"] is None
    assert stored["full_name"] is None and stored["clinic_name"] is None

    # And it can never be verified, even with a correctly signed link for it.
    request = SignupRequest(**stored)
    forged = signup.issue_link_token(request=request)
    assert _verify(client, forged).status_code == 400
    # The existing account is untouched: the guessed password does not sign in.
    assert (
        client.post(
            LOGIN_URL, data={"username": owner.email, "password": "a-guess-at-it"}
        ).status_code
        == 400
    )


def test_an_unverified_signup_cannot_sign_in_and_creates_nothing(
    client: TestClient,
) -> None:
    payload, _token = _signed_up(client)
    assert _account(payload["email"]) is None
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM tenants WHERE legal_name = :name"),
                {"name": payload["clinic_name"]},
            ).scalar_one()
            == 0
        )
    login = client.post(
        LOGIN_URL, data={"username": payload["email"], "password": PASSWORD}
    )
    assert login.status_code == 400
    assert login.json()["detail"] == "Incorrect email or password"


def test_bad_links_get_one_answer(client: TestClient, rbac: RbacApi) -> None:
    payload, token = _signed_up(client)
    (row,) = _requests(payload["email"])
    request = SignupRequest(**row)

    expired_request = SignupRequest(**row)
    expired_request.sent_at = datetime.now(UTC) - timedelta(days=3)
    expired_request.expires_at = datetime.now(UTC) - timedelta(days=2)
    header, body, signature = token.split(".")
    wrong_purpose = jwt.encode(
        {
            "sub": str(request.id),
            "jti": str(request.link_id),
            "purpose": "staff-invitation",
            "nbf": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        signup._key(),
        algorithm="HS256",
    )
    another_link = SignupRequest(**row)
    another_link.link_id = uuid.uuid4()
    for bad in (
        f"{header}.{body}.{signature[::-1]}",
        signup.issue_link_token(request=expired_request),
        wrong_purpose,
        signup.issue_link_token(request=another_link),
        create_access_token(str(request.id), timedelta(minutes=5)),
        "not-a-token",
    ):
        response = _verify(client, bad)
        assert response.status_code == 400, bad
        assert _code(response) == "SIGNUP_LINK_INVALID"
    assert _account(payload["email"]) is None

    # The link is not a session either.
    assert (
        client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401

    # The real link still works after all of that, once.
    assert _verify(client, token).status_code == 200
    _track(rbac, payload["email"])
    again = _verify(client, token)
    assert again.status_code == 400
    assert _code(again) == "SIGNUP_LINK_INVALID"


def test_a_second_signup_never_changes_the_first(
    client: TestClient, rbac: RbacApi
) -> None:
    """The pre-registration attack: whoever verifies their own link gets their own password."""
    email = f"contested-{uuid.uuid4()}@example.com"
    _attacker, attackers_link = _signed_up(
        client, email=email, password="attacker-chosen-password"
    )
    _owner, owners_link = _signed_up(client, email=email.upper())
    first, second = _requests(email)
    assert first["hashed_password"] != second["hashed_password"]

    # The real owner opens their own link: the account carries their password.
    assert _verify(client, owners_link).status_code == 200
    _track(rbac, email)
    account = _account(email)
    assert account is not None
    assert verify_password(PASSWORD, account["hashed_password"])[0]
    assert not verify_password("attacker-chosen-password", account["hashed_password"])[
        0
    ]
    # Every other request for the address is gone, and its link is refused.
    assert _requests(email) == []
    assert _verify(client, attackers_link).status_code == 400


def test_an_address_taken_after_the_signup_is_refused_at_verification(
    client: TestClient, rbac: RbacApi
) -> None:
    payload, token = _signed_up(client)
    with Session(engine) as session:
        owner = rbac.register_tenant(clinic_name="Got There First")
        session.execute(
            text('UPDATE "user" SET email = :email WHERE id = :id'),
            {"email": payload["email"], "id": owner.user_id},
        )
        session.commit()
    assert _verify(client, token).status_code == 400


def test_a_failed_email_leaves_no_request(client: TestClient) -> None:
    payload = _payload()
    with (
        patch("app.utils.send_email", side_effect=ConnectionError("smtp down")),
        pytest.raises(ConnectionError),
    ):
        client.post(SIGNUP_URL, json=payload)
    assert _requests(payload["email"]) == []


def test_signup_resend_and_verify_are_rate_limited(client: TestClient) -> None:
    limiter.clear()
    with patch("app.utils.send_email"):
        resends = [
            client.post(RESEND_URL, json={"request_id": str(uuid.uuid4())}).status_code
            for _ in range(21)
        ]
    assert resends == [202] * 20 + [429]
    verifies = [_verify(client, "guess").status_code for _ in range(21)]
    assert verifies == [400] * 20 + [429]


# --- Resend ------------------------------------------------------------------------------------


def test_resend_issues_a_new_link_and_retires_the_old(
    client: TestClient, rbac: RbacApi
) -> None:
    payload, first_link = _signed_up(client)
    (before,) = _requests(payload["email"])
    sent: list[dict[str, Any]] = []
    with patch("app.utils.send_email", side_effect=lambda **m: sent.append(m)):
        response = client.post(RESEND_URL, json={"request_id": str(before["id"])})
    assert response.status_code == 202
    (message,) = sent
    assert message["email_to"] == payload["email"]
    second_link = link_token(message["html_content"])
    assert second_link is not None and second_link != first_link
    (after,) = _requests(payload["email"])
    assert after["send_count"] == 2
    assert after["expires_at"] > before["expires_at"]

    assert _verify(client, first_link).status_code == 400
    assert _verify(client, second_link).status_code == 200
    _track(rbac, payload["email"])


def test_resend_sends_nothing_for_unknown_expired_or_exhausted_requests(
    client: TestClient,
) -> None:
    payload, _link = _signed_up(client)
    (row,) = _requests(payload["email"])
    sent: list[dict[str, Any]] = []
    with patch("app.utils.send_email", side_effect=lambda **m: sent.append(m)):
        # The cap: the first email and four resends.
        for _ in range(signup.MAX_EMAILS_PER_REQUEST + 2):
            assert (
                client.post(RESEND_URL, json={"request_id": str(row["id"])}).status_code
                == 202
            )
        assert len(sent) == signup.MAX_EMAILS_PER_REQUEST - 1
        sent.clear()
        unknown = client.post(RESEND_URL, json={"request_id": str(uuid.uuid4())})
        assert unknown.status_code == 202
        assert unknown.json() == {"message": RESENT}
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE signup_requests SET send_count = 1,"
                    " sent_at = now() - interval '3 days', expires_at = now() - interval '2 days'"
                )
            )
        client.post(RESEND_URL, json={"request_id": str(row["id"])})
    assert sent == []


def test_resending_a_notice_sends_the_notice_again(
    client: TestClient, rbac: RbacApi
) -> None:
    owner = rbac.register_tenant(clinic_name="Notice Again Clinic")
    request_signup(client, _payload(email=owner.email))
    (row,) = _requests(owner.email)
    sent: list[dict[str, Any]] = []
    with patch("app.utils.send_email", side_effect=lambda **m: sent.append(m)):
        client.post(RESEND_URL, json={"request_id": str(row["id"])})
    (message,) = sent
    assert "already have an account" in message["subject"]
    assert link_token(message["html_content"]) is None


# --- Success -----------------------------------------------------------------------------------


def test_the_link_creates_the_organisation_and_signs_the_owner_in(
    client: TestClient, rbac: RbacApi
) -> None:
    payload, token = _signed_up(client, email=f"New.Owner-{uuid.uuid4()}@example.com")

    verified = _verify(client, token)
    assert verified.status_code == 200, verified.text
    _track(rbac, payload["email"])
    assert verified.json()["token_type"] == "bearer"
    headers = {"Authorization": f"Bearer {verified.json()['access_token']}"}

    me = client.get(f"{API}/users/me", headers=headers).json()
    assert me["email"] == payload["email"], "the address is kept as typed"
    assert me["full_name"] == "Dr Ana Petrovic"
    assert me["tenant_id"] is not None
    with engine.connect() as conn:
        legal_name = conn.execute(
            text("SELECT legal_name FROM tenants WHERE id = :id"),
            {"id": me["tenant_id"]},
        ).scalar_one()
    assert legal_name == payload["clinic_name"]
    permissions = client.get(f"{API}/users/me/permissions", headers=headers).json()
    assert "users:manage" in permissions["permissions"]

    # The account was created in the new tenant's audit trail, by and for its owner.
    with engine.connect() as conn:
        (event,) = (
            conn.execute(
                text(
                    "SELECT action, result, actor_id, metadata AS payload FROM audit_log"
                    " WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": me["tenant_id"]},
            )
            .mappings()
            .all()
        )
    assert (event["action"], event["result"]) == ("user.create", "SUCCESS")
    assert str(event["actor_id"]) == me["id"]
    assert event["payload"] == {
        "target_user_id": me["id"],
        "added": ["PRACTICE_OWNER"],
        "step_up": False,
    }

    # The request is gone, and the chosen password signs in.
    assert _requests(payload["email"]) == []
    login = client.post(
        LOGIN_URL, data={"username": payload["email"], "password": PASSWORD}
    )
    assert login.status_code == 200


def test_expired_requests_are_purged_by_the_next_signup(client: TestClient) -> None:
    stale, _link = _signed_up(client)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE signup_requests SET sent_at = now() - interval '3 days',"
                " expires_at = now() - interval '2 days' WHERE email_key = lower(:email)"
            ),
            {"email": stale["email"]},
        )
    _signed_up(client)
    assert _requests(stale["email"]) == []
