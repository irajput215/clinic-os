"""Fixtures for the observability suite.

Two sinks are offered, and the difference matters:

- `json_sink` is the full pipeline: redaction, then the envelope validator, then the formatter.
  That is what the application installs.
- `raw_sink` drops the envelope validator, so an uncorrelated line is still visible. Tests that
  prove *absence* use it, because a filter that dropped the line would make the assertion vacuous.
"""

from collections.abc import Iterator

import pytest

from tests.observability.log_sinks import RecordingSink, capture_logs


@pytest.fixture
def json_sink() -> Iterator[RecordingSink]:
    with capture_logs() as sink:
        yield sink


@pytest.fixture
def raw_sink() -> Iterator[RecordingSink]:
    with capture_logs(envelope_filter=False) as sink:
        yield sink
