"""Platform readiness probes.

A probe is **not** a domain endpoint. It owns no table, resolves no tenant, emits no audit event
and returns no more than a boolean status. It is one of exactly two surfaces permitted to skip
authentication ([`definition-of-done.md` §4](../../../docs/reference/definition-of-done.md)) — the
other is public intake — so anything it reports is world-readable and must stay a boolean.

Liveness and readiness answer different questions and must not be collapsed:

- **liveness** — "is this process wedged?" A wedged process should be replaced, so liveness must
  *not* depend on the database: a database blip would otherwise restart every container and turn a
  partial outage into a full one. See `app/api/routes/utils.py`.
- **readiness** — "can this process actually serve a request?" That includes reaching the database,
  which is what this module checks.
"""

import logging

from sqlalchemy import text

from app.core.db import autocommit_engine

logger = logging.getLogger(__name__)

# Not a tenant query: a probe runs before any tenant exists and is never routed through tenant
# resolution. `SELECT 1` is the smallest statement that proves the connection authenticates.
_READY_PROBE = text("SELECT 1")


def database_is_ready() -> bool:
    """Return ``True`` only when a query can actually be executed against the database.

    Never raises: a probe has to answer, and an unhandled exception would surface as a 500 and read
    as "the process is broken" rather than "the database is unreachable".

    The failure reason is never returned to the caller — not in the body, not in a header. A probe
    that explains itself turns a pure operations signal into an information disclosure
    (INV-5, no PHI in logs or error responses), so the reason is reduced to a constant, typed-free
    log line with no interpolated data.
    """
    try:
        # Outside a transaction: `BEGIN` and `ROLLBACK` around one `SELECT` would triple the probe's
        # round trips, and the probe's figure is what the deploy gate and the performance record read.
        with autocommit_engine.connect() as connection:
            connection.execute(_READY_PROBE)
    except Exception:  # noqa: BLE001 - a probe must answer, never propagate
        # Constant message only: the underlying driver error can name the host and role, and this
        # line is emitted on a public-facing hot path.
        logger.warning("Readiness probe failed: the database is unreachable")
        return False
    return True
