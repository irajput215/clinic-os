"""I-015 / T1-20 — tenant context does not survive a checked-in pooled connection.

`docs/features/01-tenancy-and-clinics/03-design.md`, "The connection-pool hazard": a plain
`SET app.tenant_id` survives COMMIT on the server connection, so the next request on that connection —
possibly another tenant — evaluates every policy against the wrong tenant. The controls are `SET LOCAL`
(transaction-scoped, which is what `app.core.db.tenant_transaction` uses), no session-level `SET`, and
this test. S1 in `06-test-plan.md`; T-03.2 in `03-users-and-roles/04-threat-model.md`.

Three facts, each with its own assertion:

1. **`SET LOCAL` reverts at COMMIT on one connection.** The test checks out a single connection, runs
   tenant A's transaction, then tenant B's, then one with **no** context, and asserts the same
   PostgreSQL backend served all three (`pg_backend_pid()`) — so the connection really was reused and
   the second and third transactions started with nothing carried over.
2. **No context is zero rows, not the previous tenant's rows.** The third transaction above is the
   fail-closed state the policy is written for.
3. **Concurrent use through the helper is clean.** A pool of worker threads alternating tenants through
   `tenant_transaction` never returns another tenant's row.

Every transaction runs as `clinos_app`, because the process engine connects as the table owner with
`BYPASSRLS`, and `BYPASSRLS` ignores policies — a leak assertion made as the owner would pass even with
`SET LOCAL` replaced by `SET`.

**Scope, stated rather than implied.** This is the deterministic core of S1 and it carries the file name
the gate names. S1 also asks for 200 concurrent requests through a real transaction-pooling pooler
(PgBouncer or RDS Proxy) with `server_reset_query` confirmed; this repository configures no pooler, and
the pooler configuration per environment is OPEN (`03-design.md` open items; `open-questions.md` §3.3,
ADR-002 F1). That half is not claimed here, and the deployment check remains outstanding.
"""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.core.db import engine, tenant_transaction
from tests.utils.seeding import create_clinic, create_tenant, delete_tenancy_rows

AS_APP_ROLE = text("SET LOCAL ROLE clinos_app")
AS_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@pytest.fixture
def two_tenants() -> Iterator[dict[str, uuid.UUID]]:
    with engine.begin() as conn:
        a = create_tenant(conn, name="Pool Reuse A")
        b = create_tenant(conn, name="Pool Reuse B")
        create_clinic(conn, tenant_id=a, name="Alpha Site")
        create_clinic(conn, tenant_id=b, name="Beta Site")
    yield {"a": a, "b": b}
    with engine.begin() as conn:
        delete_tenancy_rows(conn, a, b)


def _names(conn: object) -> list[str]:
    result = conn.execute(  # type: ignore[attr-defined]
        text("SELECT name FROM clinics ORDER BY name")
    )
    return [row[0] for row in result]


def test_set_local_reverts_at_commit_on_a_reused_connection(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    """A, then B, then nothing — on one connection, with the backend id asserted unchanged."""
    with engine.connect() as conn:
        backend_ids: list[int] = []

        with conn.begin():
            conn.execute(AS_APP_ROLE)
            conn.execute(AS_TENANT, {"tenant_id": str(two_tenants["a"])})
            backend_ids.append(
                conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            assert _names(conn) == ["Alpha Site"]

        with conn.begin():
            conn.execute(AS_APP_ROLE)
            conn.execute(AS_TENANT, {"tenant_id": str(two_tenants["b"])})
            backend_ids.append(
                conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            assert _names(conn) == ["Beta Site"]

        with conn.begin():
            conn.execute(AS_APP_ROLE)
            backend_ids.append(
                conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            assert _names(conn) == [], (
                "a transaction with no tenant context returned rows; either the context survived the "
                "commit, or the policy is not fail-closed"
            )

    assert len(set(backend_ids)) == 1, (
        "the three transactions did not share a connection, so this test proved nothing about reuse"
    )


def _names_through_the_helper(tenant_id: uuid.UUID) -> list[str]:
    """One request's read, through the real helper, with no application-side tenant filter."""
    with tenant_transaction(tenant_id=tenant_id) as session:
        connection = session.connection()
        connection.execute(AS_APP_ROLE)
        rows = connection.execute(text("SELECT name FROM clinics ORDER BY name")).all()
        return [row[0] for row in rows]


def test_the_helper_never_bleeds_a_tenant_across_concurrent_requests(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    """Five worker threads, forty alternating requests: every answer is the caller's own row."""
    tenants = [two_tenants["a"], two_tenants["b"]]
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(
            pool.map(_names_through_the_helper, [tenants[i % 2] for i in range(40)])
        )

    for index, names in enumerate(results):
        expected = "Alpha Site" if index % 2 == 0 else "Beta Site"
        assert names == [expected], (
            f"request {index} for tenant {'A' if index % 2 == 0 else 'B'} returned {names}"
        )
