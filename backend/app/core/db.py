"""Engine, session and the tenant-scoped transaction helper.

Tenant context is set with `SET LOCAL` inside the transaction that runs the query
and nowhere else, so a pooled connection cannot carry one tenant's context into
another tenant's request
(`docs/features/01-tenancy-and-clinics/03-design.md`, "The connection-pool hazard").
"""

import logging
import select as io_select
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Final, LiteralString, cast
from uuid import UUID

import psycopg
from sqlalchemy import Select, TextClause, event, exc
from sqlalchemy.pool import ConnectionPoolEntry, PoolProxiedConnection
from sqlalchemy.sql.compiler import SQLCompiler
from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.core.logging import (
    current_correlation_id,
    current_request_id,
    record_identity,
)
from app.core.server_timing import instrument_engine
from app.models import User, UserCreate

logger = logging.getLogger(__name__)


class TenantContextRequired(RuntimeError):
    """No tenant context: refuse to open rather than run an unscoped query."""


# The pool (`docs/reference/performance.md` §4). Every round trip to the database costs the full
# app-to-database latency, so the pool is built to reuse connections and never to spend a round trip
# on bookkeeping:
#
# - **No `pool_pre_ping`.** It sent a statement on every checkout: one round trip per transaction.
#   A dead connection is found instead by `_refuse_dead_connection` below at no network cost.
# - **`pool_recycle`** replaces a connection after four minutes, inside Neon's five-minute idle
#   suspend and any proxy idle timeout, so a pooled connection is never older than the compute it
#   was opened against.
# - **TCP keepalives** make the kernel notice a silently dropped connection (a NAT or proxy that
#   forgets it without a FIN), which then reads as dead at checkout.
# - **Size**: five per process plus ten overflow, the default, sized for one request holding at most
#   one connection at a time.
POOL_SIZE: Final = 5
POOL_MAX_OVERFLOW: Final = 10
POOL_RECYCLE_SECONDS: Final = 240
_KEEPALIVES: Final = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}

engine = create_engine(
    str(settings.DATABASE_URL),
    pool_size=POOL_SIZE,
    max_overflow=POOL_MAX_OVERFLOW,
    pool_recycle=POOL_RECYCLE_SECONDS,
    connect_args=_KEEPALIVES,
)
instrument_engine(engine)

#: The same pool, without a transaction: each statement commits on its own. Only for a single read of
#: a global table, where `BEGIN` and `ROLLBACK` would be two extra round trips and no tenant context
#: is involved (a `SET LOCAL` needs a transaction, so tenant data is never read through this).
autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")


@event.listens_for(engine, "checkout")
def _refuse_dead_connection(
    dbapi_connection: Any,  # noqa: ANN401 - SQLAlchemy's event signature
    _connection_record: ConnectionPoolEntry,
    _proxy: PoolProxiedConnection,
) -> None:
    """Discard a pooled connection the server has already closed, without a round trip.

    An idle connection has nothing to read: the server sends nothing between transactions. When the
    server ends one (a restart, `pg_terminate_backend`, Neon suspending the compute) it sends an
    error and closes the socket, and when keepalives find a dropped peer the socket reports an
    error. Either way the socket becomes readable, so a readable socket at checkout means the
    connection is dead. Raising `DisconnectionError` makes the pool drop it and hand out another,
    which is what `pool_pre_ping` did, minus the round trip on every healthy checkout.
    """
    if dbapi_connection.closed or dbapi_connection.broken:
        raise exc.DisconnectionError("pooled connection is closed")
    readable, _, _ = io_select.select([dbapi_connection.fileno()], [], [], 0)
    if readable:
        raise exc.DisconnectionError("pooled connection was closed by the server")


def warm_pool(connections: int = 2) -> None:
    """Open connections before the first request needs them. Never raises.

    A new connection costs several round trips (TCP, TLS, authentication) and, after an idle period,
    Neon's compute start. Paying that at start-up keeps it off the first user's request. A failure is
    logged with a constant message (the driver's text can name the host) and the app starts anyway:
    readiness reports the database separately.
    """
    opened = []
    try:
        for _ in range(connections):
            connection = engine.connect()
            opened.append(connection)
            connection.exec_driver_sql("SELECT 1")
            connection.rollback()
    except Exception:  # noqa: BLE001 - start-up must not fail on a database blip
        logger.warning("Database warm-up failed; connections will open on demand")
    finally:
        for connection in opened:
            connection.close()


#: The transaction-scoped settings `tenant_transaction` may set, each a fixed SQL fragment with a bound
#: value. The statement is assembled from these constants only; no caller value is ever part of it.
_CONTEXT_SETTINGS: Final = {
    "app.tenant_id": "set_config('app.tenant_id', %(tenant_id)s, true)",
    "app.actor_id": "set_config('app.actor_id', %(actor_id)s, true)",
    "app.request_id": "set_config('app.request_id', %(request_id)s, true)",
}


def _driver_connection(session: Session) -> psycopg.Connection[Any]:
    driver_connection = session.connection().connection.driver_connection
    if not isinstance(driver_connection, psycopg.Connection):
        raise TypeError("pipelined statements need a psycopg connection")
    return driver_connection


def _query(sql: str) -> LiteralString:
    """Driver SQL as psycopg's typing wants it: a constant, never a value.

    Every statement sent to the driver here is either assembled from constant fragments
    (`_CONTEXT_SETTINGS`, `driver_sql`) or compiled by SQLAlchemy (`driver_statement`); every value
    travels as a bound parameter. The cast states that for the type checker.
    """
    return cast(LiteralString, sql)  # type: ignore[redundant-cast]  # mypy reads it as str


def driver_sql(clause: TextClause) -> str:
    """A `text()` clause as psycopg reads it (`:name` becomes `%(name)s`), for `run_pipelined`."""
    return str(clause.compile(dialect=engine.dialect))


def driver_statement(statement: Select[Any]) -> tuple[str, dict[str, Any]]:
    """A SQLAlchemy `select` as psycopg reads it, with its bound parameters, for `run_pipelined`.

    The parameters are what SQLAlchemy itself would send: an `IN` list is expanded into one
    parameter per value, and each value goes through its type's bind processing.
    """
    compiled = statement.compile(dialect=engine.dialect)
    if not isinstance(
        compiled, SQLCompiler
    ):  # pragma: no cover - a select compiles to SQL
        raise TypeError("only a SQL statement can be pipelined")
    state = compiled.construct_expanded_state()
    parameters = {
        name: state.processors[name](value) if name in state.processors else value
        for name, value in state.parameters.items()
    }
    return state.statement, parameters


def account_context_statement(
    *, user_id: UUID, request_id: str | None
) -> tuple[str, dict[str, str]]:
    """The transaction context of a session's account, resolved by the database from its own row.

    The first transaction of an authenticated request runs before the app has read the account, so
    the tenant comes from the account row inside the statement itself: `user.tenant_id` for
    `user.id`, never a request value (INV-1). An account with no organisation, or none at all, sets
    an empty tenant, which every RLS policy reads as "no tenant" and matches nothing (fail closed).
    Pipelined after the account read and before the reads that need the context (`run_pipelined`).
    """
    fragments = [
        "set_config('app.tenant_id', COALESCE("
        "(SELECT tenant_id::text FROM \"user\" WHERE id = %(user_id)s), ''), true)",
        _CONTEXT_SETTINGS["app.actor_id"],
    ]
    parameters = {"user_id": str(user_id), "actor_id": str(user_id)}
    if request_id is not None:
        fragments.append(_CONTEXT_SETTINGS["app.request_id"])
        parameters["request_id"] = request_id
    return "SELECT " + ", ".join(fragments), parameters


class _DeferredContext:
    """The tenant context, queued with `BEGIN` and sent with the transaction's first statement.

    `tenant_transaction` cannot know what its caller will run, but it knows the transaction's first
    two statements: `BEGIN` and the context. It queues both in a psycopg pipeline and leaves the
    pipeline open, so they travel in the same flight as whatever the caller runs first; the pipeline
    closes (and waits for every result) straight after that statement, before SQLAlchemy reads its
    result, and from then on the transaction runs as usual. Every statement still executes on the
    server in order, so the first statement already runs under the tenant's context.

    It also closes at `COMMIT` or `ROLLBACK` when nothing ran, and `run_pipelined` closes it with its
    own statements in the same flight. Errors surface exactly where they would without it: a failed
    context statement fails the first statement's execute, which is how a failed `SET LOCAL` would
    have surfaced, and the transaction rolls back.
    """

    def __init__(self, session: Session, values: dict[str, str]) -> None:
        self._connection = session.connection()
        self.driver_connection = _driver_connection(session)
        self._pipeline = self.driver_connection.pipeline()
        self._pipeline.__enter__()
        self.open = True
        context_sql, context_parameters = _context_statement(values)
        self.driver_connection.execute(_query(context_sql), context_parameters)
        for name in _CLOSING_EVENTS:
            event.listen(self._connection, name, self._close_on_event)

    def _close_on_event(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: ANN401
        self.close()

    def close(self) -> None:
        """Send whatever is queued and wait for every result. Idempotent."""
        if not self.open:
            return
        self.open = False
        # The listeners stay: they belong to this one checkout's `Connection` (never the engine),
        # are no-ops from here on, and cannot be removed while SQLAlchemy is dispatching them.
        self._pipeline.__exit__(None, None, None)


#: The first of these on the transaction's connection sends the queued context.
_CLOSING_EVENTS: Final = ("after_cursor_execute", "commit", "rollback")
_DEFERRED_CONTEXT: Final = "clinos_deferred_context"


def run_pipelined(
    session: Session,
    statements: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    commit: bool = False,
) -> list[list[tuple[Any, ...]]]:
    """Send statements in one flight on the session's transaction; return each one's rows.

    The database still runs them one after the other, each with its own snapshot, so a statement
    sees everything the ones before it did (a lock taken, a setting set). Only the waiting is shared:
    one round trip instead of one per statement (`docs/reference/performance.md`). The implicit
    `BEGIN` of a new transaction, and a tenant context still waiting to be sent, ride in the same
    flight; so does `COMMIT` when ``commit`` is set, after which the session's own commit has nothing
    left to send.

    Statements are driver SQL with bound parameters (`driver_sql`); no value is ever interpolated.
    A failing statement raises here and leaves the transaction failed, exactly as a plain execute.
    """
    return [
        rows for _, rows in run_pipelined_described(session, statements, commit=commit)
    ]


def run_pipelined_described(
    session: Session,
    statements: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    commit: bool = False,
) -> list[tuple[list[int], list[tuple[Any, ...]]]]:
    """`run_pipelined`, with each result's column type codes beside its rows.

    The type codes are what a statement's own column types need to decode the rows exactly as
    SQLAlchemy would (`app.core.reads`). A statement that returns no rows has no columns.
    """
    deferred: _DeferredContext | None = session.info.get(_DEFERRED_CONTEXT)
    if deferred is not None and deferred.open:
        driver_connection = deferred.driver_connection
        cursors = [driver_connection.execute(_query(sql), p) for sql, p in statements]
        if commit:
            driver_connection.commit()
        deferred.close()
    else:
        driver_connection = _driver_connection(session)
        cursors = []
        with driver_connection.pipeline():
            for sql, parameters in statements:
                cursors.append(driver_connection.execute(_query(sql), parameters))
            if commit:
                driver_connection.commit()
    results: list[tuple[list[int], list[tuple[Any, ...]]]] = []
    for cursor in cursors:
        description = cursor.description
        if description is None:
            results.append(([], []))
        else:
            results.append(
                ([column.type_code for column in description], cursor.fetchall())
            )
    return results


def _set_context(session: Session, values: dict[str, str]) -> None:
    """Set the transaction's context, to be sent with its `BEGIN` and its first statement.

    `set_config(..., is_local => true)` is the parameterisable form of `SET LOCAL`: the values are
    bound, never interpolated, and revert at `COMMIT` or `ROLLBACK`, so a pooled connection cannot
    carry one tenant's context into another tenant's request. Every setting goes in one `SELECT`, and
    it travels with the transaction's first statement (`_DeferredContext`): opening a tenant
    transaction costs no round trip of its own.
    """
    session.info[_DEFERRED_CONTEXT] = _DeferredContext(session, values)


def _context_statement(values: dict[str, str]) -> tuple[str, dict[str, str]]:
    fragments = [_CONTEXT_SETTINGS[key] for key in values]
    parameters = {key.removeprefix("app."): value for key, value in values.items()}
    # Constant fragments only (see `_CONTEXT_SETTINGS`); every value is a bound parameter.
    return "SELECT " + ", ".join(fragments), parameters


@contextmanager
def tenant_transaction(
    *,
    tenant_id: UUID | None,
    actor_id: UUID | None = None,
    request_id: str | None = None,
    actor_role: str | None = None,
    source_ip: str | None = None,
    correlation_id: str | None = None,
) -> Iterator[Session]:
    """Open one transaction carrying tenant context.

    Fails closed: without a tenant no transaction opens, so there is no path to an
    unscoped query. The settings are transaction-scoped, so they revert at COMMIT
    or ROLLBACK and cannot leak across pooled requests.

    `request_id` and `correlation_id` are resolved, not supplied: an explicit argument wins, and
    otherwise the ambient handles set by `app.core.logging`'s middleware are used, so every database
    session opened while serving a request carries them without each caller having to thread them
    through (`16-operations-and-observability/03-design.md` step 1). Outside a request they are left
    unset, exactly as before.

    **The audit writer reads its actor context from here, not from a parameter**
    (`app.modules.audit.service`). The actor, role, request and correlation identifiers — and the
    source address when a caller supplies one — are recorded on the session, so a caller cannot
    describe an audit event as coming from somebody else, and cannot chain one into another tenant's
    trail (INV-1). `actor_role` is the role held at decision time, which is why the caller supplies
    it rather than the writer re-deriving it later.
    """
    if tenant_id is None:
        raise TenantContextRequired(
            "tenant context is required; refusing to open an unscoped transaction"
        )

    # The same two handles the observability middleware puts on the log line, resolved the same
    # way: an explicit argument wins, otherwise the ambient one. `app.request_id` reaches the
    # database; the audit writer reads its copies from `session.info` (below), because the envelope
    # carries both and the correlation identifier has no `SET LOCAL` key of its own.
    effective_request_id = request_id or current_request_id()
    effective_correlation_id = correlation_id or current_correlation_id()
    context = _context_values(tenant_id, actor_id, effective_request_id)

    with Session(engine) as session, session.begin():
        _set_context(session, context)
        session.info["tenant_id"] = str(tenant_id)
        if actor_id is not None:
            session.info["actor_id"] = str(actor_id)
        if effective_request_id is not None:
            session.info["request_id"] = effective_request_id
        if effective_correlation_id is not None:
            session.info["correlation_id"] = effective_correlation_id
        if actor_role is not None:
            session.info["actor_role"] = actor_role
        if source_ip is not None:
            session.info["source_ip"] = source_ip
        # Keyed pseudonyms for the request log line: a raw identifier never enters a log field
        # (`16-operations-and-observability/05-data-and-audit.md`).
        record_identity(tenant_id=tenant_id, actor_id=actor_id)
        yield session


def _context_values(
    tenant_id: UUID, actor_id: UUID | None, request_id: str | None
) -> dict[str, str]:
    context = {"app.tenant_id": str(tenant_id)}
    if actor_id is not None:
        context["app.actor_id"] = str(actor_id)
    if request_id is not None:
        context["app.request_id"] = request_id
    return context


def tenant_read(
    *,
    tenant_id: UUID | None,
    actor_id: UUID | None,
    statement: str,
    parameters: Mapping[str, Any],
) -> list[tuple[Any, ...]]:
    """One read under tenant context, as a whole transaction, in a single round trip.

    The same transaction `tenant_transaction` opens (`BEGIN`, the transaction-scoped context, the
    statement, `COMMIT`), sent in one flight because every statement is known in advance. For a read
    on the hot path of every request, such as resolving the actor's permission set. Fails closed
    without a tenant, exactly as `tenant_transaction` does. It writes no audit event: a read that must
    be audited belongs in `tenant_transaction`.
    """
    if tenant_id is None:
        raise TenantContextRequired(
            "tenant context is required; refusing to open an unscoped transaction"
        )
    context = _context_values(tenant_id, actor_id, current_request_id())
    with Session(engine) as session:
        _, rows = run_pipelined(
            session,
            [_context_statement(context), (statement, parameters)],
            commit=True,
        )
    record_identity(tenant_id=tenant_id, actor_id=actor_id)
    return rows


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = crud.create_user(session=session, user_create=user_in)
