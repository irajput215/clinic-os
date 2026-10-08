"""Per-request database timing: the `Server-Timing` header and the request line's `db_*` fields.

Speed is judged at the origin, not from wherever the person measuring happens to sit
(`docs/reference/performance.md`). Every request therefore records, from the driver itself:

- ``db-connect``: time spent opening new database connections (TCP, TLS and authentication). Zero
  when the request reused pooled connections, which is the normal case.
- ``db``: time spent waiting on the database for statements, ``BEGIN``, ``COMMIT`` and ``ROLLBACK``.
- ``db-rt``: the number of network round trips to the database. Latency between the app and the
  database multiplies by this number, so it is the figure a test pins per hot endpoint.
- ``app``: the whole request, from the edge middleware to the start of the response.

**What is measured, and how.** Every psycopg operation on a connection goes through
``Connection.wait``. :class:`TimedConnection` wraps it: the wall time of the call is ``db`` time,
a call that had to wait on the socket at least once is one round trip, and a call that started
outside a transaction and left one open also sent psycopg's implicit ``BEGIN``, which is a second
round trip. Opening a connection is timed around the driver's ``connect``, through SQLAlchemy's
``do_connect`` hook, and the pool's ``checkout`` event says whether the request reused a pooled
connection or had to open one.

**What is never recorded.** No SQL text, no parameter, no identifier, no row and no error message
reaches the header or the log line: only durations and counts (INV-5). The header is also withheld
on every route that a timing difference could turn into an oracle. It is sent only on responses to
a request whose session verified (`app.api.deps.get_current_user`) and on the platform probes; an
unauthenticated route such as password recovery never carries it, so the number of round trips
cannot reveal whether an email address has an account. Deny by default: a route is quiet unless it
opted in.
"""

import os
from collections.abc import Generator
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from time import monotonic, perf_counter
from typing import Any, Final
from uuid import uuid4

import psycopg
from psycopg.pq import TransactionStatus
from sqlalchemy import Engine, event
from sqlalchemy.pool import ConnectionPoolEntry
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

SERVER_TIMING_HEADER: Final = "Server-Timing"

#: Which process served a request, so instance lifetime and pool reuse can be read from the request
#: log. Random per process: it identifies nothing outside this deployment.
INSTANCE_ID: Final = f"{uuid4().hex[:8]}-{os.getpid()}"
_INSTANCE_STARTED: Final = monotonic()


@dataclass
class RequestTimings:
    """What one request spent on the database. Durations in milliseconds, counts as integers."""

    started: float = field(default_factory=perf_counter)
    db_ms: float = 0.0
    db_round_trips: int = 0
    connect_ms: float = 0.0
    connections_opened: int = 0
    checkouts: int = 0
    #: Set by an opted-in route (see the module docstring). False sends no header.
    exposable: bool = False

    @property
    def connections_reused(self) -> int:
        return self.checkouts - self.connections_opened

    def header_value(self, now: float) -> str:
        app_ms = (now - self.started) * 1000
        return ", ".join(
            (
                f"app;dur={app_ms:.1f}",
                f"db;dur={self.db_ms:.1f}",
                f"db-connect;dur={self.connect_ms:.1f}",
                f'db-rt;desc="{self.db_round_trips}"',
            )
        )


@dataclass
class _InstanceCounters:
    requests: int = 0
    connections_opened: int = 0


_instance = _InstanceCounters()
_current: ContextVar[RequestTimings | None] = ContextVar(
    "clinos_request_timings", default=None
)


def current_timings() -> RequestTimings | None:
    """The timings of the request being served, or ``None`` outside one."""
    return _current.get()


def start_request() -> tuple[RequestTimings, Token[RequestTimings | None]]:
    """Open a measurement for the request about to run (used by the middleware and by tests)."""
    _instance.requests += 1
    timings = RequestTimings()
    return timings, _current.set(timings)


def end_request(token: Token[RequestTimings | None]) -> None:
    _current.reset(token)


def expose_server_timing() -> None:
    """Allow the current response to carry `Server-Timing` (an opt-in, see the module docstring)."""
    timings = _current.get()
    if timings is not None:
        timings.exposable = True


def request_log_fields() -> dict[str, Any]:
    """Durations and counts for the request log line: never SQL, parameters or identifiers."""
    timings = _current.get()
    fields: dict[str, Any] = {
        "instance_id": INSTANCE_ID,
        "instance_uptime_s": round(monotonic() - _INSTANCE_STARTED, 1),
        "instance_requests": _instance.requests,
        "instance_db_connections_opened": _instance.connections_opened,
    }
    if timings is not None:
        fields |= {
            "db_ms": round(timings.db_ms, 3),
            "db_round_trips": timings.db_round_trips,
            "db_connect_ms": round(timings.connect_ms, 3),
            "db_connections_opened": timings.connections_opened,
            "db_connections_reused": timings.connections_reused,
        }
    return fields


class _Waited:
    """Whether a driver operation had to wait on the socket at least once."""

    __slots__ = ("flag",)

    def __init__(self) -> None:
        self.flag = False


def _observe[RV](
    gen: Generator[Any, Any, RV], waited: _Waited
) -> Generator[Any, Any, RV]:
    """Re-yield a psycopg wait generator unchanged, noting whether it waited on the socket."""
    try:
        request = next(gen)
        while True:
            waited.flag = True
            try:
                ready = yield request
            except GeneratorExit:
                gen.close()
                raise
            except BaseException as exc:  # noqa: BLE001 - forwarded to the driver, not handled
                request = gen.throw(exc)
            else:
                request = gen.send(ready)
    except StopIteration as stop:
        return stop.value  # type: ignore[no-any-return]


class TimedConnection(psycopg.Connection[Any]):
    """A psycopg connection that reports database time and round trips to the current request."""

    def wait(self, gen: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - psycopg's API
        timings = _current.get()
        if timings is None:
            return super().wait(gen, *args, **kwargs)
        opens_transaction = (
            not self.autocommit
            and self.pgconn.transaction_status == TransactionStatus.IDLE
        )
        waited = _Waited()
        started = perf_counter()
        try:
            return super().wait(_observe(gen, waited), *args, **kwargs)
        finally:
            timings.db_ms += (perf_counter() - started) * 1000
            if waited.flag:
                timings.db_round_trips += 1
            # psycopg sends the implicit BEGIN as its own command ahead of the first statement of
            # a transaction, so that statement costs two round trips, not one.
            if opens_transaction and self.pgconn.transaction_status in (
                TransactionStatus.INTRANS,
                TransactionStatus.INERROR,
            ):
                timings.db_round_trips += 1


def instrument_engine(engine: Engine) -> None:
    """Open the engine's connections as :class:`TimedConnection` and count pool reuse."""

    @event.listens_for(engine, "do_connect")
    def _connect(
        _dialect: Any,  # noqa: ANN401 - SQLAlchemy's event signature
        _connection_record: ConnectionPoolEntry,
        cargs: tuple[Any, ...],
        cparams: dict[str, Any],
    ) -> TimedConnection:
        started = perf_counter()
        connection = TimedConnection.connect(*cargs, **cparams)
        elapsed_ms = (perf_counter() - started) * 1000
        _instance.connections_opened += 1
        timings = _current.get()
        if timings is not None:
            timings.connect_ms += elapsed_ms
            timings.connections_opened += 1
        return connection

    @event.listens_for(engine, "checkout")
    def _checkout(
        _dbapi_connection: Any,  # noqa: ANN401 - SQLAlchemy's event signature
        _connection_record: ConnectionPoolEntry,
        _proxy: Any,  # noqa: ANN401 - SQLAlchemy's event signature
    ) -> None:
        # A connection opened for this checkout was counted by `_connect` above, so whatever is
        # left over is reuse (`RequestTimings.connections_reused`).
        timings = _current.get()
        if timings is not None:
            timings.checkouts += 1


class ServerTimingMiddleware:
    """Pure-ASGI middleware: measure each request and, where allowed, send `Server-Timing`.

    Added outermost, so the request log line (written by the correlation middleware inside it) can
    read the finished measurement, and ``app`` covers every other middleware as well as the route.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        timings, token = start_request()

        async def send_with_timing(message: Message) -> None:
            if (
                message["type"] == "http.response.start"
                and settings.SERVER_TIMING_ENABLED
                and timings.exposable
            ):
                MutableHeaders(scope=message).append(
                    SERVER_TIMING_HEADER, timings.header_value(perf_counter())
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            end_request(token)
