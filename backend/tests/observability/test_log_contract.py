"""The structured log contract: the field set, the template route and the envelope validator.

Requirements `R1` (structured log contract) of
`docs/features/16-operations-and-observability/01-requirements.md`, scenarios `F1` and `F2` of
`06-test-plan.md`:

- Every request line is JSON carrying the mandatory field set, and `route` is a **template**,
  never the resolved path and never a path parameter.
- A line without `request_id` and `correlation_id` is **dropped and counted, never emitted**.

The first test is the one that keeps this honest in production: the sink and the redaction filter
must be installed by the application's own import path, not by a test fixture
(`06-test-plan.md` S1).
"""

import json
import logging

from fastapi.testclient import TestClient

from app.core.correlation import UNMATCHED_ROUTE
from app.core.logging import (
    HANDLER_NAME,
    MANDATORY_REQUEST_FIELDS,
    EnvelopeFilter,
    JSONFormatter,
    RedactionFilter,
    current_request_id,
    envelope_drop_count,
    request_context,
)
from app.main import app  # noqa: F401 - importing the application installs the sink
from tests.observability.log_sinks import RecordingSink

READINESS_PATH = "/api/v1/health/ready/"
PATIENTS_PATH = "/api/v1/patients"


def test_the_json_sink_and_the_redaction_filter_are_installed_by_the_application() -> (
    None
):
    """`configure_logging()` runs in `app.main`, so serving a request never depends on a test."""
    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if handler.name == HANDLER_NAME
    ]
    assert len(handlers) == 1, (
        "exactly one application sink, however often app.main is imported"
    )

    handler = handlers[0]
    assert isinstance(handler.formatter, JSONFormatter)
    assert any(isinstance(f, RedactionFilter) for f in handler.filters), (
        "the redaction filter must be attached to the sink, not to a call site"
    )
    assert any(isinstance(f, EnvelopeFilter) for f in handler.filters)


def test_every_request_line_has_the_mandatory_fields(
    client: TestClient, json_sink: RecordingSink
) -> None:
    """`R1` / `F2`: field set present, values typed, and nothing free-text."""
    response = client.get(READINESS_PATH, headers={"X-Request-ID": "req-contract-1"})

    assert response.status_code == 200
    line = json_sink.only("http.request")

    for field in MANDATORY_REQUEST_FIELDS:
        assert field in line, f"{field} is missing from the request line"

    assert line["request_id"] == "req-contract-1"
    assert line["correlation_id"] == "req-contract-1"
    assert line["method"] == "GET"
    assert line["status"] == 200
    assert line["outcome"] == "success"
    assert line["error_class"] is None
    assert isinstance(line["latency_ms"], int | float)
    assert line["route"].endswith("/health/ready/")
    assert line["log_category"] == "application"
    assert line["service"], (
        "the service name is how a line is attributed to a component"
    )
    assert line["app_version"]
    assert line["environment"] in {"development", "staging", "production"}
    # A probe resolves no tenant and no actor, so both are absent rather than invented.
    assert line["tenant_context"] is None
    assert line["user_context"] is None


def test_the_route_is_a_template_and_never_a_path_parameter(
    client: TestClient, json_sink: RecordingSink
) -> None:
    """`F2`: the resolved path is not the logged field — a path parameter could be PHI."""
    patient_id = "11111111-2222-3333-4444-555555555555"

    response = client.get(f"{PATIENTS_PATH}/{patient_id}")

    assert response.status_code == 401
    line = json_sink.only("http.request")
    assert line["route"].endswith("/patients/{patient_id}")
    assert patient_id not in json.dumps(line)
    assert line["status"] == 401
    assert line["outcome"] == "denied"
    assert line["error_class"] == "http_401"


def test_an_unmatched_request_does_not_log_its_own_path(
    client: TestClient, json_sink: RecordingSink
) -> None:
    """The path of an unmatched request is caller-supplied: it is never echoed into the sink."""
    sentinel = "qzqz-unmatched-sentinel"

    response = client.get(f"{PATIENTS_PATH}/does-not-exist/{sentinel}")

    assert response.status_code == 404
    line = json_sink.only("http.request")
    assert line["route"] == UNMATCHED_ROUTE
    assert sentinel not in json.dumps(line)


def test_missing_request_id_is_dropped_not_emitted(json_sink: RecordingSink) -> None:
    """`F1`: the envelope validator fails closed, and the drop is counted."""
    assert current_request_id() is None, (
        "this test must run outside any request context"
    )
    before = envelope_drop_count()

    logging.getLogger("app.test").warning("uncorrelated.line")

    assert envelope_drop_count() == before + 1
    assert json_sink.matching("uncorrelated.line") == [], (
        "a line with no request_id must never reach the sink"
    )


def test_a_correlated_line_is_emitted(json_sink: RecordingSink) -> None:
    """The counterpart to `F1`: the validator drops uncorrelated lines, not all lines."""
    with request_context("req-correlated", "corr-correlated"):
        logging.getLogger("app.test").warning("correlated.line")

    line = json_sink.only("correlated.line")
    assert line["request_id"] == "req-correlated"
    assert line["correlation_id"] == "corr-correlated"


def test_the_line_is_one_json_object_per_record(raw_sink: RecordingSink) -> None:
    """One object per line: a caller cannot forge a second line through a newline."""
    logging.getLogger("app.test").warning(
        "first line\ninjected second line", extra={"x": 1}
    )

    raw_lines = [line for line in raw_sink.raw.splitlines() if line.strip()]
    assert len(raw_lines) == 1
    assert json.loads(raw_lines[0])["level"] == "WARNING"
