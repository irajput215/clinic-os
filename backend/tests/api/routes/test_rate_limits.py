"""Rate limiting on the unauthenticated endpoints.

The limiter is process-wide, so `tests/conftest.py` clears it before every test;
these exercise the real dependency, status and header.
"""

from fastapi.testclient import TestClient

from app.core.config import settings


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
    url = f"{settings.API_V1_STR}/password-recovery/nobody@example.com"

    for _ in range(5):
        assert client.post(url).status_code == 200

    blocked = client.post(url)

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


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
