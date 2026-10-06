"""Rate limiting on the unauthenticated endpoints.

The limiter is process-wide, so `tests/conftest.py` clears it before every test;
these exercise the real dependency, status and header.

Control 10 (`docs/reference/build-contract.md` §6) requires a `429` with `Retry-After` on every
abuse-prone route. Password recovery has two of them — asking for a link and spending the token —
and both carry the same 5/min limit, because a reset token is a bearer credential that grants a
session: guessing one must cost at least as much as asking for one.
"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

RECOVERY_URL = f"{settings.API_V1_STR}/password-recovery/nobody@example.com"
RESET_URL = f"{settings.API_V1_STR}/reset-password/"
RESET_PAYLOAD = {
    "token": "not-a-reset-token",
    "new_password": "correct-horse-battery-staple",
}


def test_login_is_rate_limited(client: TestClient) -> None:
    payload = {"username": "nobody@example.com", "password": "not-the-password"}

    for _ in range(20):
        response = client.post(
            f"{settings.API_V1_STR}/login/access-token", data=payload
        )
        assert response.status_code == 400

    blocked = client.post(f"{settings.API_V1_STR}/login/access-token", data=payload)

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many requests"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_password_recovery_is_rate_limited(client: TestClient) -> None:
    """Recovery is capped tighter: every allowed attempt can send mail."""

    for _ in range(5):
        assert client.post(RECOVERY_URL).status_code == 200

    blocked = client.post(RECOVERY_URL)

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_reset_password_is_rate_limited(client: TestClient) -> None:
    """The sixth request in the window is refused, whatever the token turns out to be."""
    for _ in range(5):
        assert client.post(RESET_URL, json=RESET_PAYLOAD).status_code == 400

    blocked = client.post(RESET_URL, json=RESET_PAYLOAD)

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many requests"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_the_limit_is_per_client_not_per_instance(client: TestClient) -> None:
    """An exhausted window on one address must not deny service to another."""
    for _ in range(6):
        client.post(RESET_URL, json=RESET_PAYLOAD)
    assert client.post(RESET_URL, json=RESET_PAYLOAD).status_code == 429

    with TestClient(app, client=("203.0.113.7", 54321)) as other:
        assert other.post(RESET_URL, json=RESET_PAYLOAD).status_code == 400


def test_the_limiter_can_be_switched_off(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    payload = {"username": "nobody@example.com", "password": "not-the-password"}
    codes = {
        client.post(
            f"{settings.API_V1_STR}/login/access-token", data=payload
        ).status_code
        for _ in range(25)
    }

    assert codes == {400}
