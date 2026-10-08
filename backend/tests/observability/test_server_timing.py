"""`Server-Timing` and the request line's database fields (`app/core/server_timing.py`).

The denial path comes first: the header is withheld from every route that did not opt in, because a
round-trip count on an anonymous route (password recovery, sign-in) would tell a caller whether an
email address has an account. Then what the header and the log line carry, and that they carry
nothing else: durations and counts, never SQL, parameters or identifiers (INV-5).
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.core.db import engine
from app.core.server_timing import (
    SERVER_TIMING_HEADER,
    end_request,
    instrument_engine,
    start_request,
)
from tests.observability.log_sinks import RecordingSink

READINESS_PATH = f"{settings.API_V1_STR}/health/ready/"
ME_PATH = f"{settings.API_V1_STR}/users/me"

#: The whole header, anchored: four metrics, numbers only. Anything else in it is a leak.
_HEADER = re.compile(
    r"^app;dur=\d+\.\d, db;dur=\d+\.\d, db-connect;dur=\d+\.\d, db-rt;desc=\"\d+\"$"
)


def _metrics(header: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for part in header.split(", "):
        name, _, value = part.partition(";")
        metrics[name] = value.split("=", 1)[1].strip('"')
    return metrics


# --- Withheld unless the route opted in ---------------------------------------------------------


def test_an_anonymous_route_never_carries_server_timing(client: TestClient) -> None:
    """Password recovery reads the user table whether or not the address exists: no timing out."""
    response = client.post(
        f"{settings.API_V1_STR}/password-recovery/nobody-here@example.com"
    )

    assert SERVER_TIMING_HEADER not in response.headers


def test_a_failed_sign_in_never_carries_server_timing(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": "nobody-here@example.com", "password": "not-the-password"},
    )

    assert response.status_code == 400
    assert SERVER_TIMING_HEADER not in response.headers


def test_a_session_that_does_not_verify_never_carries_server_timing(
    client: TestClient,
) -> None:
    response = client.get(ME_PATH, headers={"Authorization": "Bearer not-a-token"})

    assert response.status_code == 401
    assert SERVER_TIMING_HEADER not in response.headers


def test_the_setting_turns_the_header_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SERVER_TIMING_ENABLED", False)

    response = client.get(READINESS_PATH)

    assert response.status_code == 200
    assert SERVER_TIMING_HEADER not in response.headers


# --- What an opted-in response carries ----------------------------------------------------------


def test_the_readiness_probe_reports_its_database_time(client: TestClient) -> None:
    response = client.get(READINESS_PATH)

    header = response.headers[SERVER_TIMING_HEADER]
    assert _HEADER.match(header), header
    metrics = _metrics(header)
    # The probe is one statement in autocommit: no BEGIN and no COMMIT to wait for.
    assert int(metrics["db-rt"]) == 1
    assert float(metrics["app"]) >= float(metrics["db"])


def test_a_verified_session_sees_its_own_request_timing(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(ME_PATH, headers=normal_user_token_headers)

    assert response.status_code == 200
    assert _HEADER.match(response.headers[SERVER_TIMING_HEADER])


def test_the_request_line_carries_durations_counts_and_the_instance(
    client: TestClient, json_sink: RecordingSink
) -> None:
    client.get(READINESS_PATH)

    line = json_sink.only("http.request")
    assert isinstance(line["db_ms"], float)
    assert line["db_round_trips"] == 1  # the probe's one autocommit statement
    assert line["db_connections_opened"] + line["db_connections_reused"] >= 1
    assert isinstance(line["db_connect_ms"], float)
    assert re.fullmatch(r"[0-9a-f]{8}-\d+", line["instance_id"])
    assert line["instance_requests"] >= 1
    assert line["instance_uptime_s"] >= 0
    # Nothing that came from the statement itself: no SQL text in any field.
    assert "select" not in json_sink.raw.lower()


# --- The counting itself ------------------------------------------------------------------------


def test_round_trips_count_the_implicit_begin_the_statement_and_the_end() -> None:
    """One statement in a transaction is three trips: BEGIN, the statement and COMMIT."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).one()
        connection.commit()
        timings, token = start_request()
        try:
            connection.execute(text("SELECT 1")).one()
            connection.commit()
        finally:
            end_request(token)

    assert timings.db_round_trips == 3
    assert timings.db_ms > 0
    assert (
        timings.checkouts == 0
    )  # the connection was checked out before the measurement opened


def test_a_commit_with_no_open_transaction_costs_nothing() -> None:
    with engine.connect() as connection:
        timings, token = start_request()
        try:
            connection.commit()
        finally:
            end_request(token)

    assert timings.db_round_trips == 0


def test_a_new_connection_is_counted_as_opened_and_a_pooled_one_as_reused() -> None:
    # Its own engine, so the pool starts empty and the application's pool is left alone.
    fresh = create_engine(str(settings.DATABASE_URL))
    instrument_engine(fresh)
    timings, token = start_request()
    try:
        with fresh.connect() as connection:
            connection.execute(text("SELECT 1")).one()
        with fresh.connect() as connection:
            connection.execute(text("SELECT 1")).one()
    finally:
        end_request(token)
        fresh.dispose()

    assert timings.connections_opened == 1
    assert timings.connections_reused == 1
    assert timings.connect_ms > 0


def test_nothing_is_recorded_outside_a_request() -> None:
    """Work outside a request (start-up, migrations, the test harness) runs unmeasured."""
    timings, token = start_request()
    end_request(token)

    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).one()

    assert timings.db_round_trips == 0
    assert timings.checkouts == 0
