"""A test sink that sees exactly what the application's own pipeline would emit.

`RecordingSink` copies the installed handler's construction — `JSONFormatter` plus
`RedactionFilter` (and, when asked, `EnvelopeFilter`) — so a test asserts against the pipeline the
application ships rather than an approximation of it. It formats at `emit` time, like a real
handler, so request-scoped fields are captured while the request context is still bound.

`capture_logs` attaches that sink to the root logger at `DEBUG`, which is the *widest* view
available: a test can then assert that a sentinel is absent from everything the process was
willing to say, not merely from what survived a filter.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core.logging import EnvelopeFilter, JSONFormatter, RedactionFilter


class RecordingSink(logging.Handler):
    """Collects formatted lines exactly as the application's JSON sink would write them."""

    def __init__(self, *, envelope_filter: bool = True) -> None:
        super().__init__(level=logging.DEBUG)
        self.name = "clinos.test-sink"
        self.setFormatter(JSONFormatter())
        self.addFilter(RedactionFilter())
        if envelope_filter:
            self.addFilter(EnvelopeFilter())
        self._emitted: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self._emitted.append(self.format(record))

    @property
    def raw(self) -> str:
        """Every byte this sink wrote, joined — the haystack a leak test searches."""
        return "\n".join(self._emitted)

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self._emitted]

    def matching(self, message: str) -> list[dict[str, Any]]:
        return [line for line in self.lines() if line.get("message") == message]

    def only(self, message: str) -> dict[str, Any]:
        found = self.matching(message)
        assert len(found) == 1, (
            f"expected exactly one {message!r} line, got {len(found)}"
        )
        return found[0]


@contextmanager
def capture_logs(*, envelope_filter: bool = True) -> Iterator[RecordingSink]:
    """Attach a sink to the root logger at `DEBUG` for the duration of the block."""
    sink = RecordingSink(envelope_filter=envelope_filter)
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(sink)
    root.setLevel(logging.DEBUG)
    try:
        yield sink
    finally:
        root.removeHandler(sink)
        root.setLevel(previous_level)
