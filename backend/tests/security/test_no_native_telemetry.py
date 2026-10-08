"""FastAPI's native OpenTelemetry stays off (`app/main.py`, `NATIVE_TELEMETRY_OFF`).

`fastapi[standard]` 0.143 ships OpenTelemetry and an OTLP exporter. Its request spans carry the path
and the query string, and the environment alone (`FASTAPI_OTEL_AUTO_CONFIGURE=true` and an OTLP
endpoint) would send them out of the process. That is a new data flow for identifiers and needs a
decision first (INV-5), so the app turns every signal off and refuses environment auto-configuration.
"""

from app.main import NATIVE_TELEMETRY_OFF, app


def test_every_native_telemetry_signal_is_off() -> None:
    assert NATIVE_TELEMETRY_OFF == {
        "tracing": False,
        "metrics": False,
        "logs": False,
        "auto_configure": False,
    }


def test_the_application_runs_with_native_telemetry_off() -> None:
    # The application's resolved configuration, so an environment variable cannot turn it on.
    config = app._telemetry  # noqa: SLF001 - FastAPI exposes no public reader for it
    assert config["tracing"] is False
    assert config["metrics"] is False
    assert config["logs"] is False
    assert config["auto_configure"] is False
