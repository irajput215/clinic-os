"""The redaction filter: every sensitive category, on the records the application emits.

Requirement `R3` / scenario `S3` of
`docs/features/16-operations-and-observability/06-test-plan.md` — *"classification lookup,
redaction and deny-list scrub run before every sink write, with no bypass for debug, trace, crash
or error paths"* — and the `INV-5` sentinel rule in `docs/reference/build-contract.md` §5.

Every case here is a record that carries a category of prohibited value, pushed through the
application's own pipeline (`tests/observability/log_sinks.py`). "Absent" is asserted on the
serialised line, so a leak is a failing assertion rather than a code review.
"""

import base64
import json
import logging

import pytest

from app.core.logging import REDACTED, request_context
from tests.observability.log_sinks import RecordingSink

LOGGER_NAME = "app.redaction.test"
REQUEST_ID = "req-redaction-1"


def synthetic_jwt() -> str:
    """Assemble a JWT-*shaped* value at runtime, from parts.

    A literal three-segment token in this file is a finding in the repository's own secret scan
    (the `jwt` rule), and this suite must not have to be allow-listed to pass its own gate. The
    value exists only to exercise the redaction pattern, so it is built from encoded JSON here and
    never written down as one token.
    """

    def segment(claims: dict[str, str]) -> str:
        encoded = base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":")).encode()
        )
        return encoded.decode().rstrip("=")

    return ".".join(
        [
            segment({"alg": "HS256", "typ": "JWT"}),
            segment({"sub": "QZQZsubject", "iss": "clinos-test"}),
            "QZQZsignature",
        ]
    )


#: One sentinel per prohibited category. The sentinels are synthetic and distinctive
#: (`06-test-plan.md`: "Sentinel values are distinctive and synthetic").
REDACTION_CASES: dict[str, tuple[dict[str, object], str]] = {
    # HEALTH_INFORMATION: a health identifier.
    "medicare_number": ({"medicare_number": "2123456789"}, "2123456789"),
    "ihi": ({"ihi": "8003608833357361"}, "8003608833357361"),
    # HEALTH_INFORMATION: a patient name, in the typed fields that carry one.
    "patient_name": (
        {"given_name": "QZQZWilhelmina", "family_name": "QZQZSynthetic"},
        "QZQZWilhelmina",
    ),
    # HEALTH_INFORMATION: a date of birth.
    "date_of_birth": ({"date_of_birth": "1974-03-12"}, "1974-03-12"),
    # HIGHLY_SENSITIVE: a full clinical request body, however it was passed.
    "request_body": (
        {
            "request_body": {
                "given_name": "QZQZAda",
                "date_of_birth": "1974-03-12",
                "medicare_number": "2123456789",
            }
        },
        "QZQZAda",
    ),
    "json_body": ({"json": {"note": "QZQZclinical-note"}}, "QZQZclinical-note"),
    # SECRET: credentials and session material.
    "authorization_header": (
        {"authorization": f"Bearer {synthetic_jwt()}"},
        "QZQZsignature",
    ),
    "cookie_header": ({"cookie": "session=QZQZcookievalue"}, "QZQZcookievalue"),
    "password": ({"password": "QZQZpasswordvalue"}, "QZQZpasswordvalue"),
    "token": ({"access_token": "QZQZtokenvalue"}, "QZQZtokenvalue"),
}


def _emit(sink: RecordingSink, **fields: object) -> dict[str, object]:
    with request_context(REQUEST_ID, REQUEST_ID):
        logging.getLogger(LOGGER_NAME).info("redaction.case", extra=fields)
    return sink.only("redaction.case")


@pytest.mark.parametrize(
    ("fields", "sentinel"),
    list(REDACTION_CASES.values()),
    ids=list(REDACTION_CASES),
)
def test_each_prohibited_category_is_redacted_before_the_sink(
    json_sink: RecordingSink, fields: dict[str, object], sentinel: str
) -> None:
    line = _emit(json_sink, **fields)

    rendered = json.dumps(line)
    assert sentinel not in rendered, f"{sentinel!r} reached the sink"
    assert REDACTED in rendered, (
        "the field must be marked redacted, not silently dropped"
    )


def test_a_health_identifier_in_free_text_is_scrubbed(json_sink: RecordingSink) -> None:
    """Pattern redaction, not just key redaction: the value is caught wherever it appears."""
    with request_context(REQUEST_ID, REQUEST_ID):
        logging.getLogger(LOGGER_NAME).warning(
            "patient born %s with medicare %s", "1974-03-12", "2123456789"
        )

    assert json_sink.lines(), "the diagnostic line must still be emitted"
    rendered = json_sink.raw
    assert "1974-03-12" not in rendered
    assert "2123456789" not in rendered


def test_an_authorization_header_in_free_text_is_scrubbed(
    json_sink: RecordingSink,
) -> None:
    with request_context(REQUEST_ID, REQUEST_ID):
        logging.getLogger(LOGGER_NAME).warning(
            "upstream refused: Authorization: Bearer QZQZopaquetokenvalue"
        )

    rendered = json_sink.raw
    assert "QZQZopaquetokenvalue" not in rendered
    assert REDACTED in rendered


def test_a_credential_assignment_in_free_text_is_scrubbed(
    json_sink: RecordingSink,
) -> None:
    with request_context(REQUEST_ID, REQUEST_ID):
        logging.getLogger(LOGGER_NAME).warning("attempt failed password=QZQZleaveitout")

    assert "QZQZleaveitout" not in json_sink.raw


def test_a_bare_jwt_in_free_text_is_scrubbed(json_sink: RecordingSink) -> None:
    """The value pattern, not the field key: a token pasted into a message is still a secret."""
    jwt = synthetic_jwt()

    with request_context(REQUEST_ID, REQUEST_ID):
        logging.getLogger(LOGGER_NAME).warning("token was %s", jwt)

    assert jwt not in json_sink.raw
    assert jwt.split(".")[0] not in json_sink.raw, "no segment of it may survive either"
    assert REDACTED in json_sink.raw


def test_positional_arguments_are_scrubbed(json_sink: RecordingSink) -> None:
    """`%s` interpolation happens after redaction, so the argument itself is the leak vector."""
    with request_context(REQUEST_ID, REQUEST_ID):
        logging.getLogger(LOGGER_NAME).warning("medicare %s", "2123456789")

    assert "2123456789" not in json_sink.raw


def test_redaction_runs_on_the_error_path(json_sink: RecordingSink) -> None:
    """`R3`: no bypass for a crash, a traceback or an error line."""
    with request_context(REQUEST_ID, REQUEST_ID):
        try:
            raise RuntimeError("medicare 2123456789 for QZQZWilhelmina")
        except RuntimeError:
            logging.getLogger(LOGGER_NAME).exception(
                "unhandled", extra={"error_class": "RuntimeError"}
            )

    line = json_sink.only("unhandled")
    assert "2123456789" not in json.dumps(line)
    assert REDACTED in str(line["exception"])
    assert "RuntimeError" in str(line["exception"]), (
        "the class is diagnostic, the value is not"
    )


def test_redaction_is_fail_closed_on_a_name_that_merely_looks_sensitive(
    json_sink: RecordingSink,
) -> None:
    """An over-broad deny-list is the safe direction: an unexpected key is redacted, not trusted."""
    line = _emit(json_sink, patient_surname="QZQZanything")

    assert "QZQZanything" not in json.dumps(line)
    assert REDACTED in json.dumps(line)


def test_safe_fields_survive_redaction(json_sink: RecordingSink) -> None:
    """The filter redacts the prohibited values and leaves the operational ones alone."""
    line = _emit(json_sink, status=200, latency_ms=12.5, error_class=None)

    assert line["status"] == 200
    assert line["latency_ms"] == 12.5
    assert line["error_class"] is None
    assert line["request_id"] == REQUEST_ID
    assert line["service"] == "ClinicOS"
