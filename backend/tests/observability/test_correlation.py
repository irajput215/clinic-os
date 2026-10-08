"""Correlation handles: the round trip, generation, validation and the database session.

Requirement `R1` and scenarios `F4`/`F5` of
`docs/features/16-operations-and-observability/06-test-plan.md`:

- An inbound `X-Request-ID` is honoured, echoed and logged; without one, a handle is generated.
- An inbound handle that is not a safe handle is **refused, not sanitised** — a header that could
  forge a log line, or that carries a health identifier, must never reach the sink
  (`04-threat-model.md` T-16.10; `INV-5`).
- The handle reaches `app.core.db.tenant_transaction`, so a database session opened while serving
  a request carries `app.request_id` (`03-design.md` step 1).
"""

import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import db as db_module
from app.core.db import tenant_transaction
from app.core.logging import current_request_id, request_context
from tests.observability.log_sinks import RecordingSink
from tests.patients.conftest import PatientsApi

READINESS_PATH = "/api/v1/health/ready/"

_GENERATED = re.compile(r"\A[0-9a-f]{32}\Z")


def assert_generated_handle(handle: str) -> None:
    """A generated handle is a UUID4 hex: it replaces the caller's value, it is not derived from it."""
    assert _GENERATED.match(handle), f"{handle!r} is not a generated handle"


# --- The round trip -----------------------------------------------------------------------------


def test_an_inbound_request_id_is_honoured_echoed_and_logged(
    client: TestClient, json_sink: RecordingSink
) -> None:
    response = client.get(READINESS_PATH, headers={"X-Request-ID": "edge-7f3a9c2b"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "edge-7f3a9c2b"
    line = json_sink.only("http.request")
    assert line["request_id"] == "edge-7f3a9c2b"
    assert line["correlation_id"] == "edge-7f3a9c2b"


def test_a_handle_is_generated_when_the_caller_sends_none(
    client: TestClient, json_sink: RecordingSink
) -> None:
    response = client.get(READINESS_PATH)

    generated = response.headers["X-Request-ID"]
    assert_generated_handle(generated)
    assert json_sink.only("http.request")["request_id"] == generated


def test_an_inbound_correlation_id_is_kept_separate_from_the_request_id(
    client: TestClient, json_sink: RecordingSink
) -> None:
    """`correlation_id` joins a user intent across calls; it is not simply the request handle."""
    response = client.get(
        READINESS_PATH,
        headers={"X-Request-ID": "req-1", "X-Correlation-ID": "intent-9"},
    )

    assert response.headers["X-Request-ID"] == "req-1"
    line = json_sink.only("http.request")
    assert line["request_id"] == "req-1"
    assert line["correlation_id"] == "intent-9"


# --- The denial path: an unsafe handle is refused -------------------------------------------------

UNSAFE_HANDLES: dict[str, tuple[str, str]] = {
    "too_long": ("a" * 129, "a" * 129),
    "name_with_spaces": ("John Smith patient", "John Smith"),
    "newline_injection": ("line\nforged", "forged"),
    "quotes": ('abc"def', 'abc"def'),
    "medicare_shaped": ("2123456789", "2123456789"),
    "ihi_shaped": ("8003608833357361", "8003608833357361"),
}


@pytest.mark.parametrize(
    ("unsafe", "sentinel"),
    list(UNSAFE_HANDLES.values()),
    ids=list(UNSAFE_HANDLES),
)
def test_an_unsafe_inbound_handle_is_refused_and_never_reaches_the_sink(
    client: TestClient, json_sink: RecordingSink, unsafe: str, sentinel: str
) -> None:
    """`INV-5`: the correlation path is not a route for PHI into the log sink."""
    response = client.get(READINESS_PATH, headers={"X-Request-ID": unsafe})

    echoed = response.headers["X-Request-ID"]
    assert echoed != unsafe, "the unsafe value must not be echoed back"
    assert_generated_handle(echoed)

    line = json_sink.only("http.request")
    assert line["request_id"] == echoed
    assert sentinel not in json.dumps(line)
    assert unsafe.strip() not in response.text


def test_an_empty_inbound_handle_is_replaced(
    client: TestClient, json_sink: RecordingSink
) -> None:
    response = client.get(READINESS_PATH, headers={"X-Request-ID": ""})

    echoed = response.headers["X-Request-ID"]
    assert_generated_handle(echoed)
    assert json_sink.only("http.request")["request_id"] == echoed


# --- The database session -------------------------------------------------------------------------


def test_tenant_transaction_reads_the_ambient_request_id() -> None:
    """`tenant_transaction` resolves the handle, so no caller has to thread it through."""
    tenant_id = uuid.uuid4()

    with request_context("req-ambient", "corr-ambient"):
        with tenant_transaction(tenant_id=tenant_id) as session:
            assert (
                session.exec(
                    text("SELECT current_setting('app.request_id', true)")
                ).scalar()
                == "req-ambient"
            )


def test_an_explicit_request_id_wins_over_the_ambient_one() -> None:
    with request_context("req-ambient"):
        with tenant_transaction(
            tenant_id=uuid.uuid4(), request_id="req-explicit"
        ) as session:
            assert (
                session.exec(
                    text("SELECT current_setting('app.request_id', true)")
                ).scalar()
                == "req-explicit"
            )


def test_no_request_id_is_set_outside_a_request() -> None:
    """Outside a request nothing changes: the transaction still opens, with no handle set."""
    assert current_request_id() is None

    with tenant_transaction(tenant_id=uuid.uuid4()) as session:
        assert session.exec(
            text("SELECT current_setting('app.request_id', true)")
        ).scalar() in (None, "")


def test_the_database_session_of_a_real_request_carries_the_handle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: the middleware's handle is the one `_set_context` writes into the session."""
    patients = PatientsApi(client)
    recorded: dict[str, str] = {}
    real_set_context = db_module._set_context

    def spy(session: object, values: dict[str, str]) -> None:
        recorded.update(values)
        real_set_context(session, values)  # type: ignore[arg-type]

    monkeypatch.setattr(db_module, "_set_context", spy)
    try:
        tenant = patients.register(clinic_name="Correlation Clinic")
        response = patients.list(tenant, limit=1)
    finally:
        patients.cleanup()

    assert response.status_code == 200, response.text
    assert recorded["app.tenant_id"] == str(tenant.tenant_id)
    assert recorded["app.request_id"] == response.headers["X-Request-ID"]


# --- The pseudonyms ---------------------------------------------------------------------------


def test_the_request_line_carries_keyed_pseudonyms_not_raw_identifiers(
    client: TestClient, json_sink: RecordingSink
) -> None:
    """`05-data-and-audit.md`: the tenant and the actor are pseudonymised in application logs."""
    patients = PatientsApi(client)
    try:
        tenant = patients.register(clinic_name="Pseudonym Clinic")
        # `POST /patients` passes the actor, so both pseudonyms are populated; a read does not.
        response = patients.create_raw(
            tenant, given_name="Ada", family_name="Synthetic"
        )
    finally:
        patients.cleanup()

    assert response.status_code == 201, response.text
    line = json_sink.matching("http.request")[-1]

    assert isinstance(line["tenant_context"], str)
    assert isinstance(line["user_context"], str)
    assert line["tenant_context"].startswith("t_")
    assert line["user_context"].startswith("u_")
    assert str(tenant.tenant_id) not in json.dumps(line)
    assert str(tenant.user_id) not in json.dumps(line)
