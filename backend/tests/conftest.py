import secrets
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.core.rate_limit import limiter
from app.main import app
from app.models import User
from app.modules.care_relationships.models import CareRelationship
from app.modules.users_roles.models import StaffInvitation, UserRole
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


@dataclass
class MailSink:
    """Every booking email the app handed to SMTP, in order; `accept` is the server's answer."""

    sent: list[dict[str, Any]] = field(default_factory=list)
    accept: bool = True

    def to(self, address: str) -> list[dict[str, Any]]:
        return [message for message in self.sent if message["email_to"] == address]


@pytest.fixture(autouse=True)
def mail_sink() -> Iterator[MailSink]:
    """No test sends real mail: the patient-facing sender (`app.utils.deliver_email`) is a sink.

    `.env.example` configures SMTP (Mailpit) for the e2e suite, so `settings.emails_enabled` is true
    in a test run and every booking queues its emails; this keeps them in memory.
    """
    sink = MailSink()

    def deliver(**message: Any) -> bool:
        sink.sent.append(message)
        return sink.accept

    with patch("app.utils.deliver_email", side_effect=deliver):
        yield sink


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    """The limiter is process-wide, so no test inherits another's window."""
    limiter.clear()


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    with Session(engine) as session:
        init_db(session)
        yield session
        # `user_roles` and `staff_invitations` reference `user` with ON DELETE RESTRICT, so they go
        # before the accounts they belong to. Nothing here deletes tenants; the module fixtures that own a
        # tenant clean their RBAC rows up themselves.
        session.execute(delete(UserRole))
        session.execute(delete(StaffInvitation))
        # A care relationship names its practitioner (`ON DELETE RESTRICT`); module fixtures remove
        # their own, and this catches any a failed test left behind before the accounts go.
        session.execute(delete(CareRelationship))
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
