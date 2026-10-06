"""Request and response schemas for the audit read API.

Design: `docs/features/04-audit-log/03-design.md` §"Endpoints" and §"Deny-by-default request path"
step 4 (*"Validate filters strictly: unknown fields rejected, unbounded scan refused `422`"*).
Requirement R12.

Two things are deliberately absent, and both are load-bearing:

- **No request schema accepts a tenant identifier.** The tenant is resolved from the authenticated
  session and from nowhere else (INV-1), so a `tenant_id` in the query string is never read and the
  request cannot name one.
- **No response schema carries a clinical field, an unlisted payload key or a secret.**
  `AuditEventRead` declares the design's envelope and nothing else. The per-action `metadata` object is
  exposed as `payload` because it is the allow-listed object the writer stored — and the writer refuses
  a key outside the allow-list before the row exists, so what is exposed here is what a deliberate
  change put there (R11).

**This module does not import `service`.** The filter *parameters* are declared in the router as
explicit `Query(...)` arguments, so the OpenAPI document lists each filter by name — which is what the
generated SDK is built from — and the window rule is validated by the service, which owns it.
"""

import uuid
from datetime import datetime

from pydantic import Field
from sqlmodel import SQLModel

# PRIVATE API, deliberately. SQLModel annotates `model_config` as `SQLModelConfig`, so a plain
# `ConfigDict` is rejected by BOTH mypy --strict and ty; this is the only spelling that satisfies
# both, and it is the same import `app/modules/patients/schemas.py` already carries.
from sqlmodel._compat import SQLModelConfig

# R12: the page size defaults to 50 and the hard maximum is 200. A client may ask for less and never
# for more; the router's `Query(ge=..., le=...)` enforces the same bounds at the edge.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# The `result` vocabulary the design's envelope fixes. Declared here as well as in the model so a
# filter value is refused at the schema rather than matched against nothing.
RESULT_VALUES = ("SUCCESS", "DENIED", "FAILED", "UNKNOWN")

# The longest cursor this API accepts. A cursor is an HMAC-signed
# `base64url({"e": uuid, "t": timestamp})` pair, far under this; the bound exists so an oversized
# input is refused at the edge.
MAX_CURSOR_LENGTH = 512


class AuditEventRead(SQLModel):
    """One audit event as the API returns it — the design's envelope, and nothing else.

    `tenant_id` is not declared: the caller already knows its own tenant, and the row was read under
    it. `prev_hash` and `hash` are exposed because verifying the trail is the point of reading it.
    """

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    event_id: uuid.UUID
    timestamp: datetime
    actor_id: uuid.UUID | None = None
    actor_role: str | None = None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    result: str
    reason: str | None = None
    source_ip: str | None = None
    request_id: str
    correlation_id: str | None = None
    prev_hash: str
    hash: str
    payload: dict[str, object] | None = None


class AuditEventsPublic(SQLModel):
    """A keyset page of audit events.

    `next_cursor` is opaque and `None` on the last page. `count` is the number of rows in this page,
    not the tenant's total: the total is not disclosed and is not knowable without a scan, which R12
    refuses.
    """

    data: list[AuditEventRead]
    count: int = Field(ge=0)
    next_cursor: str | None = None


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_CURSOR_LENGTH",
    "MAX_PAGE_SIZE",
    "RESULT_VALUES",
    "AuditEventRead",
    "AuditEventsPublic",
]
