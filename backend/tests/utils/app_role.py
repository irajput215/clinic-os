"""`pytest --as-app-role`: the app serves every HTTP request as `clinos_app`.

The go-live blocker in `docs3/roadmap.md` (`docs/progress.md` P5): production must connect as
`clinos_app`, the least-privilege role row-level security binds. Every API test otherwise runs as the
`postgres` superuser, which ignores RLS and every grant, so a query the application role may not run
passes the suite and fails only in production.

With the option, each request the test client sends is served with its pooled connection switched to
`clinos_app` (background tasks included, since they run inside the same ASGI call), and reset when the
connection returns to the pool. Test setup, cleanup and direct service calls keep the test connection's
own role, so a `permission denied` during a request is a gap in the application's grants, not the
harness's. `tests/isolation/test_api_as_app_role.py` keeps a smaller always-on version of this.

The round-trip budget tests count statements, and the switch adds two per checkout, so they are
skipped under the option (`SKIPPED_UNDER_APP_ROLE`).
"""

import contextvars
from typing import Any

from sqlalchemy import event

from app.core.db import engine

_serving: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "serving", default=False
)

# Tests whose assertion is a statement or round-trip count.
SKIPPED_UNDER_APP_ROLE = (
    "tests/performance/test_round_trips.py",
    "tests/api/routes/test_login.py::test_sign_in_costs_one_database_round_trip",
    "tests/observability/test_server_timing.py",
)


def _run(dbapi_connection: Any, statement: str) -> None:  # noqa: ANN401
    autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        dbapi_connection.execute(statement)
    finally:
        dbapi_connection.autocommit = autocommit


def _checkout(dbapi_connection: Any, *_: Any) -> None:  # noqa: ANN401
    if _serving.get():
        _run(dbapi_connection, "SET ROLE clinos_app")


def _checkin(dbapi_connection: Any, *_: Any) -> None:  # noqa: ANN401
    if not dbapi_connection.closed:
        _run(dbapi_connection, "RESET ROLE")


class ServeAsAppRole:
    """Pure ASGI middleware: mark the request so its connections check out as `clinos_app`."""

    def __init__(self, inner: Any) -> None:  # noqa: ANN401
        self.inner = inner

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        token = _serving.set(True)
        try:
            await self.inner(scope, receive, send)
        finally:
            _serving.reset(token)


def install() -> None:
    from app.main import app

    event.listen(engine, "checkout", _checkout)
    event.listen(engine, "checkin", _checkin)
    app.add_middleware(ServeAsAppRole)
