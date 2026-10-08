"""The pool and the pipelined tenant context (`app/core/db.py`, `docs/reference/performance.md` §4).

Three properties, each with the failure it guards against:

1. **A connection the server closed is never handed to a request.** There is no `pool_pre_ping`;
   the checkout sees the closed socket and opens a fresh connection instead, so the request succeeds.
2. **The tenant context never outlives its transaction on a shared connection**, now that it is
   queued with `BEGIN` and sent with the transaction's first statement. Two tenants, a failed first
   statement and an empty transaction are interleaved over one pooled connection, and every
   transaction sees its own context and nothing else.
3. **The context reaches the database before the first statement runs**, including when that first
   statement is a write or a pipelined batch.

Every transaction that reads rows runs as `clinos_app`: the process engine connects as the owner with
`BYPASSRLS`, and an assertion made as the owner would pass whatever the context said.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.core import db as db_module
from app.core.config import settings
from app.core.db import engine, run_pipelined, tenant_transaction
from app.core.server_timing import instrument_engine
from tests.utils.seeding import create_clinic, create_tenant, delete_tenancy_rows

READINESS_PATH = f"{settings.API_V1_STR}/health/ready/"
AS_APP_ROLE = text("SET LOCAL ROLE clinos_app")
CURRENT_TENANT = text("SELECT current_setting('app.tenant_id', true)")
BACKEND_PID = text("SELECT pg_backend_pid()")


@pytest.fixture
def two_tenants() -> Iterator[dict[str, uuid.UUID]]:
    with engine.begin() as conn:
        a = create_tenant(conn, name="Pipeline A")
        b = create_tenant(conn, name="Pipeline B")
        create_clinic(conn, tenant_id=a, name="Alpha Pipeline Site")
        create_clinic(conn, tenant_id=b, name="Beta Pipeline Site")
    yield {"a": a, "b": b}
    with engine.begin() as conn:
        delete_tenancy_rows(conn, a, b)


@pytest.fixture
def one_connection(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Route `tenant_transaction` through a pool of exactly one connection, so reuse is certain."""
    single = create_engine(
        str(settings.DATABASE_URL), pool_size=1, max_overflow=0, pool_timeout=5
    )
    instrument_engine(single)
    monkeypatch.setattr(db_module, "engine", single)
    yield
    single.dispose()


def _terminate_idle_connections() -> int:
    """End every idle server connection to this database, and wait until they are gone.

    The asking connection comes from its own pool-less engine, so it is never one of the pooled
    connections it is about to end.
    """
    killer = create_engine(str(settings.DATABASE_URL), poolclass=NullPool)
    with killer.connect() as conn:
        ended = conn.execute(
            text(
                "SELECT count(*) FROM ("
                " SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity"
                " WHERE datname = current_database() AND pid <> pg_backend_pid()"
                " AND state = 'idle') AS ended"
            )
        ).scalar_one()
        conn.rollback()
    killer.dispose()
    return int(ended)


# --- 1. A dead pooled connection ----------------------------------------------------------------


def test_a_request_after_its_pooled_connection_was_killed_still_succeeds(
    client: TestClient,
) -> None:
    client.get(READINESS_PATH)  # the pool now holds at least one idle connection
    assert _terminate_idle_connections() >= 1

    response = client.get(READINESS_PATH)

    assert response.status_code == 200
    assert response.json() is True
    # The dead connection was discarded at checkout and a new one opened in its place.
    assert "db-connect;dur=0.0" not in response.headers["Server-Timing"]


def test_a_tenant_transaction_after_its_pooled_connection_was_killed_still_succeeds(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    with tenant_transaction(tenant_id=two_tenants["a"]) as session:
        session.connection().execute(text("SELECT 1"))
    assert _terminate_idle_connections() >= 1

    with tenant_transaction(tenant_id=two_tenants["a"]) as session:
        tenant = session.connection().execute(CURRENT_TENANT).scalar_one()

    assert tenant == str(two_tenants["a"])


# --- 2. Interleaved tenants on one pooled connection --------------------------------------------


@pytest.mark.usefixtures("one_connection")
def test_interleaved_tenants_on_one_connection_never_see_each_others_context(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    backends: list[int] = []
    seen: list[tuple[str | None, list[str]]] = []

    def read(tenant_id: uuid.UUID) -> None:
        with tenant_transaction(tenant_id=tenant_id) as session:
            conn = session.connection()
            conn.execute(
                AS_APP_ROLE
            )  # the first statement: it carries the queued context
            backends.append(conn.execute(BACKEND_PID).scalar_one())
            names = [
                row[0]
                for row in conn.execute(text("SELECT name FROM clinics ORDER BY name"))
            ]
            seen.append((conn.execute(CURRENT_TENANT).scalar_one(), names))

    read(two_tenants["a"])
    read(two_tenants["b"])

    # A transaction whose first statement fails: the queued context goes with it and is rolled back.
    with pytest.raises(DBAPIError):
        with tenant_transaction(tenant_id=two_tenants["a"]) as session:
            session.connection().execute(text("SELECT 1 / 0"))

    # A transaction that runs nothing at all still sends, and then discards, its context.
    with tenant_transaction(tenant_id=two_tenants["b"]):
        pass

    read(two_tenants["b"])
    read(two_tenants["a"])

    # And the same connection with no tenant context at all sees no tenant and no rows.
    with db_module.engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        backends.append(conn.execute(BACKEND_PID).scalar_one())
        assert conn.execute(CURRENT_TENANT).scalar_one() in (None, "")
        assert conn.execute(text("SELECT name FROM clinics")).all() == []

    assert len(set(backends)) == 1, "the transactions did not share one connection"
    assert seen == [
        (str(two_tenants["a"]), ["Alpha Pipeline Site"]),
        (str(two_tenants["b"]), ["Beta Pipeline Site"]),
        (str(two_tenants["b"]), ["Beta Pipeline Site"]),
        (str(two_tenants["a"]), ["Alpha Pipeline Site"]),
    ]


# --- 3. The context is in place before the first statement runs ---------------------------------


def test_the_first_statement_already_runs_under_the_tenant_context(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    with tenant_transaction(tenant_id=two_tenants["a"]) as session:
        first = session.connection().execute(CURRENT_TENANT).scalar_one()

    assert first == str(two_tenants["a"])


def test_a_pipelined_batch_rides_with_the_queued_context(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    with tenant_transaction(tenant_id=two_tenants["b"]) as session:
        (setting,), (pid,) = run_pipelined(
            session,
            [
                ("SELECT current_setting('app.tenant_id', true)", {}),
                ("SELECT pg_backend_pid()", {}),
            ],
        )
        # The transaction carries on normally afterwards, on the same connection.
        later = session.connection().execute(CURRENT_TENANT).scalar_one()
        same_pid = session.connection().execute(BACKEND_PID).scalar_one()

    assert setting == (str(two_tenants["b"]),)
    assert later == str(two_tenants["b"])
    assert same_pid == pid[0]


def test_a_write_as_the_first_statement_is_scoped_and_committed(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    name = f"Written First {uuid.uuid4().hex[:6]}"
    with tenant_transaction(tenant_id=two_tenants["a"]) as session:
        # The very first statement: its tenant comes from the context, so the context was there.
        session.connection().execute(
            text(
                "INSERT INTO clinics (id, tenant_id, name, created_at, updated_at) VALUES ("
                "gen_random_uuid(), NULLIF(current_setting('app.tenant_id', true), '')::uuid,"
                " :name, now(), now())"
            ),
            {"name": name},
        )

    with tenant_transaction(tenant_id=two_tenants["a"]) as session:
        conn = session.connection()
        conn.execute(AS_APP_ROLE)
        names = conn.execute(text("SELECT name FROM clinics")).scalars().all()
    with tenant_transaction(tenant_id=two_tenants["b"]) as session:
        conn = session.connection()
        conn.execute(AS_APP_ROLE)
        other = conn.execute(text("SELECT name FROM clinics")).scalars().all()

    assert name in names
    assert name not in other
