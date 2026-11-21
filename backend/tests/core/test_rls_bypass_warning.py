"""The start-up warning for a login that ignores row-level security (`docs/progress.md` P5)."""

import logging

import pytest
from sqlalchemy import text

from app.core import db
from app.core.db import RLS_BYPASS_WARNING, connection_bypasses_rls, engine


def test_the_superuser_bypasses_and_the_app_role_does_not() -> None:
    with engine.connect() as conn, conn.begin():
        # The suite connects as the `postgres` superuser.
        assert connection_bypasses_rls(conn) is True
        conn.execute(text("SET LOCAL ROLE clinos_app"))
        assert connection_bypasses_rls(conn) is False
        conn.execute(text("SET LOCAL ROLE clinos_extractor"))
        assert connection_bypasses_rls(conn) is False


def test_start_up_warns_when_the_login_bypasses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=db.__name__):
        db.warm_pool(connections=1)
    assert RLS_BYPASS_WARNING in caplog.messages


def test_start_up_is_quiet_for_a_bound_login(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db, "connection_bypasses_rls", lambda _connection: False)
    with caplog.at_level(logging.WARNING, logger=db.__name__):
        db.warm_pool(connections=1)
    assert RLS_BYPASS_WARNING not in caplog.messages


def test_the_warning_names_no_credential_or_host() -> None:
    assert "@" not in RLS_BYPASS_WARNING and "postgres" not in RLS_BYPASS_WARNING
