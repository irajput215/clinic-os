"""The `audit_log` table — append-only, tenant-scoped, hash-chained.

Design: `docs/features/04-audit-log/03-design.md` §"Table: `audit_log`". Requirements:
`docs/features/04-audit-log/01-requirements.md` R6, R8, R14, R15.

Three things about this model are deliberate, and each one is a rule from the design rather than a
preference:

1. **No foreign keys.** *"an audit row must survive the deletion of the resource it describes."* The
   `tenant_id` column is therefore a plain `uuid` with no `REFERENCES tenants(id)`, which is also why
   the append-only trail never blocks a tenant teardown.
2. **Composite primary key `(event_id, timestamp)`.** The design names it, and the timestamp has to be
   in it because the table is partitioned by range on `timestamp`: PostgreSQL requires every unique
   index on a partitioned table to contain the partition key.
3. **`FORCE ROW LEVEL SECURITY`, two policies, no `UPDATE` and no `DELETE` policy.** None of that can
   be expressed in a model — `SQLModel.metadata.create_all` would produce a table that looks correct
   and enforces nothing — so it lives in the migration, and `tests/audit/test_append_only_grants.py`
   reads the resulting catalogue rather than the migration source.

## Why the payload attribute is called `payload` and the column is called `metadata`

The design's `metadata` key is the per-action allow-listed object (R11), and the column carries that
name. The Python attribute cannot: SQLAlchemy reserves the name `metadata` on a declarative class
(*"Attribute name 'metadata' is reserved when using the Declarative API"*), so the attribute is
`payload` and it maps onto the `metadata` column explicitly. The wire and database name is what the
document names; only the attribute differs, and the mapping is one line below.

## Ordering, and what this module uses for "next in the chain"

The design names no sequence column; it names the primary key `(event_id, timestamp)` and describes a
*"sequence gap"* as a break. The chain order is therefore `(timestamp, event_id)`, ascending, which is
a total order because that pair is the primary key. `timestamp` is the writer's own clock reading,
stored at microsecond precision with the time zone, so a row's stored value round-trips byte-for-byte
through the canonical serialisation the hash is computed over.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

# The four values the design's envelope fixes for `result`.
RESULT_VOCABULARY: Final[tuple[str, ...]] = ("SUCCESS", "DENIED", "FAILED", "UNKNOWN")

# The genesis link of every tenant chain: `04-design.md` §"Hash chain" — *"The first event in a
# tenant chain uses a genesis `prev_hash` of 64 zeroes."* Held as the canonical (hex) form, which is
# also how a hash is rendered in the exported JSONL.
GENESIS_HASH: Final[str] = "0" * 64

_TIMESTAMPTZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditLogEntry(SQLModel, table=True):
    """One audit event. Insert-only: nothing in the application ever updates or deletes one."""

    __tablename__ = "audit_log"
    __table_args__ = (
        # Named explicitly: SQLModel cannot infer a composite primary key from two fields, and the
        # convention would key the name off the first column alone — which is what we want anyway.
        sa.PrimaryKeyConstraint("event_id", "timestamp", name="pk_audit_log"),
        # The envelope's closed sets, enforced by the database as well as by the writer. The suffix
        # form (`name="result"`) is what `app.core.metadata` renders as `ck_audit_log_result`.
        sa.CheckConstraint(
            "result IN ('SUCCESS', 'DENIED', 'FAILED', 'UNKNOWN')",
            name="result",
        ),
        sa.CheckConstraint(
            "resource_type IN ('PATIENT', 'CLINICAL_RECORD', 'PRESCRIPTION', 'TGA_APPROVAL',"
            " 'TGA_DOCUMENT', 'USER', 'TENANT', 'SESSION', 'AUDIT', 'REPORT', 'INTEGRATION',"
            " 'EXPORT')",
            name="resource_type",
        ),
        # The keyset the read API uses, and the filter columns the design names. `tenant_id` leads
        # every one of them; `timestamp DESC` matches the read order.
        sa.Index(
            "ix_audit_log_tenant_timestamp", "tenant_id", sa.text("timestamp DESC")
        ),
        sa.Index(
            "ix_audit_log_tenant_actor_timestamp",
            "tenant_id",
            "actor_id",
            sa.text("timestamp DESC"),
        ),
        sa.Index(
            "ix_audit_log_tenant_action_timestamp",
            "tenant_id",
            "action",
            sa.text("timestamp DESC"),
        ),
        sa.Index(
            "ix_audit_log_tenant_resource_timestamp",
            "tenant_id",
            "resource_type",
            "resource_id",
            sa.text("timestamp DESC"),
        ),
    )

    # Assigned by the writer, never by the caller. `server_default` is a defence for a direct SQL
    # insert only; the writer always supplies its own, so the hash covers the identifier that is
    # actually stored.
    event_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    # The server clock, at microsecond precision, stored UTC. It is the partition key, so it is
    # NOT NULL and part of the primary key.
    timestamp: datetime = Field(
        default_factory=_utcnow, sa_column=sa.Column(_TIMESTAMPTZ, nullable=False)
    )
    # From the request's resolved tenant, never a body. NULL is reserved for a platform-level event
    # with no tenant (design, OPEN-7) — `clinos_app` on a tenant-scoped read path never sees one.
    tenant_id: uuid.UUID | None = Field(default=None)
    actor_id: uuid.UUID | None = Field(default=None)
    # The role held **at decision time**, not the role held later.
    actor_role: str | None = Field(default=None, max_length=64)
    action: str = Field(max_length=128)
    resource_type: str = Field(max_length=32)
    resource_id: uuid.UUID | None = Field(default=None)
    result: str = Field(max_length=16)
    # A controlled code, not free text, unless the actor typed a justification. It is captured and
    # never written to a log line (`05-data-and-audit.md`, "What may never be in an audit payload").
    reason: str | None = Field(default=None, max_length=255)
    source_ip: str | None = Field(default=None, max_length=64)
    request_id: str = Field(max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    # The hex-encoded SHA-256 of the previous event in the tenant chain; the genesis value is 64
    # zeroes. Hex rather than `bytea` because that is the form the hash is chained in and exported
    # as, so there is exactly one representation from the writer to the JSONL bundle (design, OPEN-2
    # records the `bytea`-vs-hex ambiguity; this module applies the exportable form).
    prev_hash: str = Field(max_length=64)
    hash: str = Field(max_length=64)
    # The per-action allow-listed object (R11). The attribute is `payload`; the column is
    # `metadata`, which is the name the design gives it. See the module docstring.
    payload: dict[str, Any] | None = Field(
        default=None, sa_column=sa.Column("metadata", JSONB, nullable=True)
    )
