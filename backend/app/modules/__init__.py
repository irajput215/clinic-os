"""Domain modules.

One package per module, laid out as `models.py`, `schemas.py`, `service.py` and
`router.py`. A module owns its tables and is reached only through its service
facade; no module reads another module's tables or private helpers
(`docs/reference/build-contract.md` §7). The import-boundary lint that enforces
this is task T0-3.
"""
