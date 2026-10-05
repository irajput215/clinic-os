"""Domain modules.

One package per module, laid out as `models.py`, `schemas.py`, `service.py` and
`router.py`. A module owns its tables and is reached only through its service
facade; no module reads another module's tables or private helpers
(`docs/reference/build-contract.md` §7). The import-boundary lint that enforces
this is task T0-3.

Every table in this package must be imported by `app.db_models`, the single place
Alembic reads. That registry imports this package, which is why the naming
convention is applied here: Python executes a parent package before its submodules,
so the convention is in place before any table in it is defined.
"""

from app.core.metadata import NAMING_CONVENTION  # noqa: F401
