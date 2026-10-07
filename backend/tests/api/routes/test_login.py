from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlmodel import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.crud import create_user, update_user
from app.models import User, UserCreate, UserUpdate
from app.modules.users_roles import invitations
from app.utils import generate_password_reset_token
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    result = r.json()
    assert r.status_code == 200
    assert "email" in result


def test_recovery_password(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch("app.core.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.core.config.settings.SMTP_USER", "admin@example.com"),
    ):
        email = "test@example.com"
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {
            "message": "If that email is registered, we sent a password recovery link"
        }


def test_recovery_password_user_not_exits(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    email = "jVgQr@example.com"
    r = client.post(
        f"{settings.API_V1_STR}/password-recovery/{email}",
        headers=normal_user_token_headers,
    )
    # Should return 200 with generic message to prevent email enumeration attacks
    assert r.status_code == 200
    assert r.json() == {
        "message": "If that email is registered, we sent a password recovery link"
    }


def test_reset_password(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    new_password = random_lower_string()

    user_create = UserCreate(
        email=email,
        full_name="Test User",
        password=password,
        is_active=True,
        is_superuser=False,
    )
    user = create_user(session=db, user_create=user_create)
    token = generate_password_reset_token(
        email=email, hashed_password=user.hashed_password
    )
    headers = user_authentication_headers(client=client, email=email, password=password)
    data = {"new_password": new_password, "token": token}

    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=headers,
        json=data,
    )

    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}

    db.refresh(user)
    verified, _ = verify_password(new_password, user.hashed_password)
    assert verified


def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()

    assert "detail" in response
    assert r.status_code == 400
    assert response["detail"] == "Invalid token"


def test_login_with_bcrypt_password_upgrades_to_argon2(
    client: TestClient, db: Session
) -> None:
    """Test that logging in with a bcrypt password hash upgrades it to argon2."""
    email = random_email()
    password = random_lower_string()

    # Create a bcrypt hash directly (simulating legacy password)
    bcrypt_hasher = BcryptHasher()
    bcrypt_hash = bcrypt_hasher.hash(password)
    assert bcrypt_hash.startswith("$2")  # bcrypt hashes start with $2

    user = User(email=email, hashed_password=bcrypt_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    assert user.hashed_password.startswith("$2")

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    # Verify the hash was upgraded to argon2
    assert user.hashed_password.startswith("$argon2")

    verified, updated_hash = verify_password(password, user.hashed_password)
    assert verified
    # Should not need another update since it's already argon2
    assert updated_hash is None


def test_login_with_argon2_password_keeps_hash(client: TestClient, db: Session) -> None:
    """Test that logging in with an argon2 password hash does not update it."""
    email = random_email()
    password = random_lower_string()

    # Create an argon2 hash (current default)
    argon2_hash = get_password_hash(password)
    assert argon2_hash.startswith("$argon2")

    # Create user with argon2 hash
    user = User(email=email, hashed_password=argon2_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    original_hash = user.hashed_password

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    assert user.hashed_password == original_hash
    assert user.hashed_password.startswith("$argon2")


def _recovery_token(client: TestClient, email: str) -> str:
    """Ask for a recovery link the way the sign-in page does and return the token it carries."""
    with (
        patch("app.core.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.core.config.settings.SMTP_USER", "admin@example.com"),
        patch("app.api.routes.login.send_email") as send,
    ):
        r = client.post(f"{settings.API_V1_STR}/password-recovery/{email}")
    assert r.status_code == 200
    html = send.call_args.kwargs["html_content"]
    return html.split("reset-password?token=", 1)[1].split('"', 1)[0]


def _new_user(db: Session) -> tuple[User, str]:
    password = random_lower_string()
    user = create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=password),
    )
    return user, password


def test_reset_password_token_is_single_use(client: TestClient, db: Session) -> None:
    """A recovery link sets a password once. Replaying it - after the reset it was issued for has
    been spent - is refused with the same answer as a forged token, and the password stays put."""
    user, _ = _new_user(db)
    token = _recovery_token(client, user.email)
    first, second = random_lower_string(), random_lower_string()

    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        json={"token": token, "new_password": first},
    )
    assert r.status_code == 200

    replay = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        json={"token": token, "new_password": second},
    )
    assert replay.status_code == 400
    assert replay.json()["detail"] == "Invalid token"

    db.refresh(user)
    assert verify_password(first, user.hashed_password)[0]
    assert not verify_password(second, user.hashed_password)[0]


def test_reset_password_token_dies_when_password_changes_otherwise(
    client: TestClient, db: Session
) -> None:
    """A link issued before the password changed some other way (any write of a new password hash,
    such as a second recovery or the user changing it while signed in) no longer works: it was
    issued for a password state that is gone."""
    user, _ = _new_user(db)
    token = _recovery_token(client, user.email)
    changed = random_lower_string()
    update_user(session=db, db_user=user, user_in=UserUpdate(password=changed))

    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        json={"token": token, "new_password": random_lower_string()},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid token"
    db.refresh(user)
    assert verify_password(changed, user.hashed_password)[0]


def test_reset_password_refuses_expired_and_foreign_tokens(
    client: TestClient, db: Session
) -> None:
    """Expired, access and invitation tokens all get the one uniform answer."""
    user, _ = _new_user(db)
    expired = generate_password_reset_token(
        email=user.email,
        hashed_password=user.hashed_password,
        now=datetime.now(UTC)
        - timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS + 1),
    )
    access = create_access_token(user.email, timedelta(minutes=5))
    invitation = invitations.issue(
        user_id=user.id, hashed_password=user.hashed_password
    )
    for bad in (expired, access, invitation):
        r = client.post(
            f"{settings.API_V1_STR}/reset-password/",
            json={"token": bad, "new_password": random_lower_string()},
        )
        assert r.status_code == 400, bad
        assert r.json()["detail"] == "Invalid token"
        limiter.clear()


def test_recovery_link_is_not_an_invitation(client: TestClient, db: Session) -> None:
    """The two password-setting links share one mechanism but never verify as each other."""
    user, _ = _new_user(db)
    token = _recovery_token(client, user.email)
    r = client.post(
        f"{settings.API_V1_STR}/users/invitations/accept",
        json={"token": token, "new_password": random_lower_string()},
    )
    assert r.status_code == 400
    r = client.get(
        f"{settings.API_V1_STR}/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 401
