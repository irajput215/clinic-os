"""Feature 04 — the append-only, hash-chained audit log.

The module owns `audit_log`, its grants, its hash chain, its verification entry point and its
immutable-export seam. It is reached only through [`service`](service.py).

Design: `docs/features/04-audit-log/03-design.md`. Requirements: `docs/features/04-audit-log/01-requirements.md`.
"""
