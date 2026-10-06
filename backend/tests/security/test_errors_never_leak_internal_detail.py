"""Control 9: one error envelope, no diagnostics to the client, correlation, fail closed.

Requirement `docs/reference/build-contract.md` §6 control 9 and its evidence artefact
`backend/tests/security/test_errors_never_leak_internal_detail.py`
(`docs/reference/control-matrix.md`).

The envelope is RFC 7807 `application/problem+json` with two documented departures from the RFC:
`detail` keeps the API's existing payload (a string, or the machine-readable
`{"code": ..., "message": ...}` object the policy layer raises), and `request_id` is added as a
top-level extension so a clinician can quote the handle that finds the log line.

The tests below are the *denial* path first: a database error and an unhandled exception must
produce the same generic body, with the traceback, the SQL, its parameters and any table or column
name kept on the server. The diagnostic is not discarded — it goes to the log, which is where an
operator can see it and a client cannot.
"""

import json
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.errors import PROBLEM_MEDIA_TYPE, classify_error
from app.core.security import create_access_token
from app.main import app
from app.models import UserCreate
from tests.observability.log_sinks import capture_logs
from tests.patients.conftest import PatientsApi
from tests.utils.utils import random_email, random_lower_string

API = settings.API_V1_STR
USERS_ME = f"{API}/users/me"
PATIENTS_URL = f"{API}/patients"
READINESS_PATH = f"{API}/health/ready/"

#: A statement and a parameter value of the kind a driver puts in an exception message. Neither
#: may reach the client; both may reach the log.
LEAKY_SQL = "SELECT medicare_number FROM patients WHERE id = '11111111-2222-3333-4444-555555555555'"

#: Everything a 500 must never say.
FORBIDDEN_IN_A_500 = (
    "SELECT",
    "medicare_number",
    "patients",
    "connection refused",
    "Traceback",
    "OperationalError",
    "RuntimeError",
    "site-packages",
    "/Users/",
)


def _problem(response: Response, *, status: int, path: str) -> dict[str, object]:
    """Assert the envelope's shape once, so each test below asserts only its own point."""
    assert response.status_code == status
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    for member in ("type", "title", "status", "detail", "instance", "request_id"):
        assert member in body, f"{member} is missing from the error envelope"
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["instance"] == path
    assert body["request_id"], "every error response carries its correlation handle"
    assert response.headers["X-Request-ID"] == body["request_id"]
    return body


def _raising_client(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> TestClient:
    """A client whose readiness route raises, so the exception reaches the last handler.

    `raise_server_exceptions=False` is what a browser sees: Starlette re-raises after sending the
    response, so a client that re-raises as well would never let a test observe the body.
    """

    def boom() -> bool:
        raise exc

    monkeypatch.setattr("app.api.routes.health.database_is_ready", boom)
    return TestClient(app, raise_server_exceptions=False)


# --- The existing payload survives, and the envelope is additive ---------------------------------


def test_a_string_detail_is_preserved(client: TestClient) -> None:
    response = client.get(USERS_ME)

    body = _problem(response, status=401, path=USERS_ME)
    assert body["detail"] == "Not authenticated"
    # The refusal's own headers survive too: the client signs out on this one.
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert body["title"] == "Unauthorized"


def test_a_dict_detail_is_preserved_byte_for_byte(
    client: TestClient, db: Session
) -> None:
    """The policy layer's machine-readable detail is the client's contract; it does not change."""
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    db.refresh(user)
    token = create_access_token(str(user.id), timedelta(minutes=5))

    response = client.get(PATIENTS_URL, headers={"Authorization": f"Bearer {token}"})

    body = _problem(response, status=403, path=PATIENTS_URL)
    assert body["detail"] == {
        "code": "NO_ORGANISATION",
        "message": "This account has no organisation",
    }


def test_an_inbound_request_id_is_echoed_in_the_error_envelope(
    client: TestClient,
) -> None:
    response = client.get(USERS_ME, headers={"X-Request-ID": "error-edge-1"})

    assert response.headers["X-Request-ID"] == "error-edge-1"
    assert response.json()["request_id"] == "error-edge-1"


# --- Validation: the message names the field, never the value -------------------------------------


def test_a_validation_error_does_not_echo_the_submitted_body(
    client: TestClient,
) -> None:
    """`INV-5`: FastAPI's default echoes the offending `input`, which for a body-level failure is
    the whole body. That is a HIGHLY_SENSITIVE payload in an error response, so it is dropped."""
    patients = PatientsApi(client)
    try:
        tenant = patients.register(clinic_name="Envelope Clinic")
        # `tenant_id` is a forbidden body field, so the failure is body-level and the default
        # response would have echoed `{"given_name": "Ada", "family_name": "Synthetic", ...}`.
        response = patients.create_raw(tenant, tenant_id=str(uuid.uuid4()))
    finally:
        patients.cleanup()

    body = _problem(response, status=422, path=PATIENTS_URL)
    assert "tenant_id" in response.text, "the field name is the whole point of a 422"
    for submitted in ("Ada", "Synthetic", "given_name", "family_name"):
        assert submitted not in response.text, (
            f"{submitted!r} was echoed back to the caller"
        )

    errors = body["detail"]
    assert isinstance(errors, list) and errors
    for error in errors:
        assert set(error) <= {"type", "loc", "msg"}


def test_a_validation_error_does_not_echo_a_mistyped_value(client: TestClient) -> None:
    patients = PatientsApi(client)
    try:
        tenant = patients.register(clinic_name="Envelope Clinic")
        response = patients.create_raw(tenant, date_of_birth="QZQZnot-a-date")
    finally:
        patients.cleanup()

    assert response.status_code == 422
    assert "QZQZnot-a-date" not in response.text
    assert "date_of_birth" in response.text


# --- The denial path: a database error and an unhandled exception both fail closed ----------------


def test_a_database_error_returns_the_generic_envelope_without_leaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A driver error message names the statement and its parameters. Neither leaves the process."""
    error = OperationalError(
        LEAKY_SQL,
        {"id": "11111111-2222-3333-4444-555555555555"},
        Exception("connection refused"),
    )
    client = _raising_client(monkeypatch, error)

    with capture_logs() as logs:
        response = client.get(READINESS_PATH)

    body = _problem(response, status=500, path=READINESS_PATH)
    assert body["detail"] == "Internal server error"
    for leaked in FORBIDDEN_IN_A_500:
        assert leaked not in response.text, f"{leaked!r} reached the client"
    assert "11111111-2222-3333-4444-555555555555" not in response.text

    # The diagnostic is not lost: it is on the server side, where it belongs.
    line = logs.only("http.unhandled_exception")
    assert line["error_class"] == "database_unavailable"
    assert "SELECT" in str(line["exception"]), (
        "the statement is in the log, not the response"
    )
    assert line["request_id"] == body["request_id"]
    assert line["log_category"] == "application"
    assert line["route"].endswith("/health/ready/")


def test_an_unhandled_exception_returns_the_generic_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _raising_client(
        monkeypatch, RuntimeError("internal detail that must not surface")
    )

    with capture_logs() as logs:
        response = client.get(READINESS_PATH)

    body = _problem(response, status=500, path=READINESS_PATH)
    assert body["detail"] == "Internal server error"
    assert "internal detail that must not surface" not in response.text
    for leaked in FORBIDDEN_IN_A_500:
        assert leaked not in response.text, f"{leaked!r} reached the client"
    assert logs.only("http.unhandled_exception")["error_class"] == "RuntimeError"


def test_the_500_body_is_the_same_whatever_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indistinguishable to the caller: the body must not become a debugging oracle."""
    bodies = []
    for exc in (
        RuntimeError("boom"),
        OperationalError(LEAKY_SQL, {}, Exception("boom")),
    ):
        client = _raising_client(monkeypatch, exc)
        with capture_logs():
            response = client.get(READINESS_PATH)
        monkeypatch.undo()
        body = response.json()
        body.pop("request_id")  # the one field that is, correctly, per request
        bodies.append(body)

    assert bodies[0] == bodies[1]
    assert bodies[0]["detail"] == "Internal server error"


def test_the_log_diagnostic_still_names_the_failing_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server's copy is detailed; only the client's copy is generic."""
    client = _raising_client(monkeypatch, RuntimeError("boom"))

    with capture_logs() as logs:
        response = client.get(READINESS_PATH)

    line = logs.only("http.unhandled_exception")
    assert "test_errors_never_leak_internal_detail.py" in str(line["exception"])
    assert "test_errors_never_leak_internal_detail.py" not in response.text


def test_an_error_line_is_still_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """An error path is not a bypass: a health identifier in the exception is scrubbed."""
    client = _raising_client(
        monkeypatch, RuntimeError("failed for medicare 2123456789")
    )

    with capture_logs() as logs:
        response = client.get(READINESS_PATH)

    assert "2123456789" not in json.dumps(logs.only("http.unhandled_exception"))
    assert "2123456789" not in response.text


def test_the_500_body_carries_no_query_string(client: TestClient) -> None:
    """`instance` is the path: a query string can carry an identifier and is never echoed."""
    response = client.get(f"{USERS_ME}?token=QZQZleaked")

    body = _problem(response, status=401, path=USERS_ME)
    assert "QZQZleaked" not in response.text
    assert body["instance"] == USERS_ME


def test_instance_names_the_route_and_never_the_path_parameter(
    client: TestClient,
) -> None:
    """`404` must not confirm which resource it refused: the id is replaced by its name.

    The same rule as the log line: a resolved path parameter may be an identifier, so the envelope
    reports the template and `request_id` identifies the occurrence.
    """
    patients = PatientsApi(client)
    try:
        tenant = patients.register(clinic_name="Envelope Clinic")
        missing_id = str(uuid.uuid4())
        response = patients.read(tenant, missing_id)
    finally:
        patients.cleanup()

    body = _problem(response, status=404, path=f"{PATIENTS_URL}/{{patient_id}}")
    assert missing_id not in response.text
    assert missing_id not in json.dumps(body)


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (OperationalError("SELECT 1", {}, Exception("down")), "database_unavailable"),
        (IntegrityError("SELECT 1", {}, Exception("duplicate")), "database_constraint"),
        (DBAPIError("SELECT 1", {}, Exception("driver")), "database_error"),
        (TimeoutError("slow"), "timeout"),
        (ValueError("bad"), "ValueError"),
    ],
)
def test_the_error_class_is_a_closed_vocabulary_not_a_message(
    exception: BaseException, expected: str
) -> None:
    """`error_class` is a classified type (`03-design.md`): never a message, SQL or provider text."""
    assert classify_error(exception) == expected
    assert "SELECT" not in classify_error(exception)
