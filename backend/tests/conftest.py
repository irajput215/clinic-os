import secrets
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.core.rate_limit import limiter
from app.main import app
from app.models import User
from app.modules.users_roles.models import UserRole
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers

# The local compose database, reachable as `localhost` from the host (CI and local
# runs) or as `db` from inside the compose network.
_ALLOWED_TEST_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db"})


def _refuse_to_run_against_a_remote_database() -> None:
    """Fail closed before a single test runs.

    The suite deletes users and tenants on teardown. A `.env` pointing at a deployed
    database has already emptied a live `user` table once; a remote host is a
    configuration error, not a test environment.
    """
    host = settings.DATABASE_URL.hosts()[0]["host"]
    if host not in _ALLOWED_TEST_DATABASE_HOSTS:
        raise RuntimeError(
            f"DATABASE_URL points at {host!r}, which is not the local database. "
            "pytest deletes users and tenants on teardown, so this is refused. "
            "Point DATABASE_URL at the local compose database in .env."
        )


_refuse_to_run_against_a_remote_database()


# HS256 needs a key of at least 32 bytes (RFC 7518 §3.2); PyJWT warns below that, and the suite
# turns every warning into an error. CI copies `.env.example`, whose `SECRET_KEY` is the
# `REPLACE_ME` placeholder, so a test run signs with a fresh random key of the right length
# instead. A key that is already long enough is kept. This touches only the test process; the
# deployed configuration is never read from here.
_HS256_MIN_KEY_BYTES = 32
if len(settings.SECRET_KEY.encode()) < _HS256_MIN_KEY_BYTES:
    settings.SECRET_KEY = secrets.token_urlsafe(48)


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    """The limiter is process-wide, so no test inherits another's window."""
    limiter.clear()


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    with Session(engine) as session:
        init_db(session)
        yield session
        # `user_roles` references `user` with ON DELETE RESTRICT, so the grants go before the
        # accounts they belong to. Nothing here deletes tenants; the module fixtures that own a
        # tenant clean their RBAC rows up themselves.
        session.execute(delete(UserRole))
        session.execute(delete(User))
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
