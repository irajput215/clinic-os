"""`INV-5`: a synthetic clinical value reaches no log sink, at any level.

Requirement `R2` and scenario `S1` of
`docs/features/16-operations-and-observability/06-test-plan.md` — *"a synthetic clinical value is
processed through every path; the sentinel appears in no log sink"* — and the standing rule in
`docs/reference/build-contract.md` §6: *"Do not log a request body from a clinical endpoint, at any
log level, including in errors."*

The sentinels are **names**, deliberately: a name has no shape, so no value pattern can redact it.
If a call site logged a request body, the name would be the first thing to escape — the assertions
below are therefore evidence that the body was never said, not that a filter removed it. The sink
is the widest view available: root logger at `DEBUG`, redaction on, envelope validator *off*, so a
dropped line cannot make the test pass vacuously.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests.observability.log_sinks import capture_logs
from tests.patients.conftest import PatientsApi

API = settings.API_V1_STR

#: Distinctive, synthetic, and only findable if a call site copied a request body.
NAME_SENTINEL = "QZQZWilhelmina"
SURNAME_SENTINEL = "QZQZSynthetic"
DOB_SENTINEL = "1974-03-12"
MEDICARE_SENTINEL = "2123456789"
USERNAME_SENTINEL = "qzqz-clinician@example.com"
PASSWORD_SENTINEL = "QZQZ-correct-horse-battery"

SENTINELS = (
    NAME_SENTINEL,
    SURNAME_SENTINEL,
    DOB_SENTINEL,
    USERNAME_SENTINEL,
    PASSWORD_SENTINEL,
)


@pytest.fixture
def patients(client: TestClient) -> Iterator[PatientsApi]:
    helper = PatientsApi(client)
    yield helper
    helper.cleanup()


def test_sentinel_clinical_value_absent_from_all_sinks(
    client: TestClient, patients: PatientsApi
) -> None:
    """`S1`: create, read, reject and authenticate — every path, with the sink at `DEBUG`."""
    with capture_logs(envelope_filter=False) as sink:
        tenant = patients.register(clinic_name="Sentinel Clinic")

        # The success path: the body is parsed, validated and written.
        created = patients.create(
            tenant, given_name=NAME_SENTINEL, family_name=SURNAME_SENTINEL
        )
        # The read path.
        assert patients.read(tenant, created["id"]).status_code == 200
        # The validation-denial path: the body is parsed and refused. The value is on the wire
        # and in the validation error, which is exactly where a careless logger would echo it.
        assert (
            patients.create_raw(
                tenant,
                given_name=NAME_SENTINEL,
                date_of_birth=DOB_SENTINEL,
                medicare_number=MEDICARE_SENTINEL,
            ).status_code
            == 422
        )
        # The authentication-denial path, with a credential in the body.
        login = client.post(
            f"{API}/login/access-token",
            data={"username": USERNAME_SENTINEL, "password": PASSWORD_SENTINEL},
        )

    assert login.status_code in {400, 401, 422}
    assert sink.matching("http.request"), (
        "the sink must have been live to prove anything at all"
    )

    for sentinel in SENTINELS:
        assert sentinel not in sink.raw, f"{sentinel!r} reached a log sink"


def test_a_request_body_sent_to_a_denied_route_is_not_logged(
    client: TestClient,
) -> None:
    """A body that never reaches a handler is still not a log line."""
    sentinels = {
        "given_name": NAME_SENTINEL,
        "family_name": SURNAME_SENTINEL,
        "date_of_birth": DOB_SENTINEL,
        "medicare_number": MEDICARE_SENTINEL,
    }

    with capture_logs(envelope_filter=False) as sink:
        response = client.post(f"{API}/patients", json=sentinels)

    assert response.status_code == 401
    assert sink.matching("http.request")
    for sentinel in (NAME_SENTINEL, SURNAME_SENTINEL, DOB_SENTINEL):
        assert sentinel not in sink.raw


def test_a_health_identifier_in_an_error_is_scrubbed_on_the_error_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error path is not a licence to dump a value: the 500 is generic and the log is scrubbed."""

    def boom() -> bool:
        raise RuntimeError(f"failed while saving medicare {MEDICARE_SENTINEL}")

    monkeypatch.setattr("app.api.routes.health.database_is_ready", boom)

    with capture_logs(envelope_filter=False) as sink:
        with TestClient(app, raise_server_exceptions=False) as failing:
            response = failing.get(f"{API}/health/ready/")

    assert response.status_code == 500
    assert MEDICARE_SENTINEL not in response.text
    assert sink.matching("http.unhandled_exception"), (
        "the diagnostic must still be logged"
    )
    assert MEDICARE_SENTINEL not in sink.raw


def test_the_validation_error_returned_to_the_client_carries_no_body(
    patients: PatientsApi,
) -> None:
    """The 422 is the one place a value could be echoed *to the client* rather than to a sink."""
    tenant = patients.register(clinic_name="Sentinel Clinic")

    response = patients.create_raw(
        tenant, given_name=NAME_SENTINEL, unknown_field=str(uuid.uuid4())
    )

    assert response.status_code == 422
    for echoed in (NAME_SENTINEL, "Synthetic"):
        assert echoed not in response.text, f"{echoed!r} was echoed back to the caller"
