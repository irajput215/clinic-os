"""The audit facade: one writer, one verifier, one export.

Design: `docs/features/04-audit-log/03-design.md`. Requirements: `docs/features/04-audit-log/01-requirements.md`
R3, R4, R8, R11.

Everything outside this module reaches `audit_log` through here. Three properties are the whole point
of the module, and each one is load-bearing:

**One writer, inside the caller's transaction (R3).** [`record`][app.modules.audit.service.record]
takes a `Session` the caller already opened with `app.core.db.tenant_transaction` and inserts on it.
There is no `commit` here and no session of the writer's own: the audit row and the domain change
commit together or not at all, and a rollback leaves neither behind.

**A failed audit write fails the operation (R4, T-AUD-3).** Nothing in this module catches an
exception from the insert. A rejection, a database error or a broken chain propagates out of `record`
and out of the caller's `with` block, which rolls the whole transaction back — *"a change that cannot
be audited must not happen"*.

**Concurrent writers cannot fork the chain (R8).** `record` takes a transaction-scoped advisory lock
keyed on the tenant before it reads `prev_hash`, so two writers for one tenant serialise and the
second chains onto the first. The lock is released by `COMMIT`/`ROLLBACK`, so it cannot leak across a
pooled connection.

The tenant is read from `app.tenant_id`, which `tenant_transaction` set with `SET LOCAL`. It is
deliberately **not** a parameter: a caller cannot pass a tenant, so a caller cannot chain an event
into another tenant's trail even by mistake (INV-1).
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Any, Final, Protocol

from sqlalchemy import and_, or_
from sqlmodel import Session, col, select, text

from app.core.config import settings
from app.modules.audit.actions import (
    ACTIONS,
    PAYLOAD_ALLOW_LIST,
    PAYLOAD_KEYS,
    PAYLOAD_REJECTED,
    RESULTS,
    resource_type_for,
)
from app.modules.audit.models import GENESIS_HASH, AuditLogEntry

# The transaction-scoped advisory lock namespace for the audit chain. `pg_advisory_xact_lock` takes
# two `int4`s or one `int8`; this class id keeps the chain lock out of the namespace any other
# feature uses, and is stable because it is a constant here rather than a hash of anything.
_CHAIN_LOCK_CLASS: Final[int] = 0x04


class AuditWriteRefused(RuntimeError):
    """The writer refused the event. The caller's transaction must roll back.

    Raised for an action outside the closed catalogue, a payload key outside the allow-list, a
    `resource_type` that disagrees with the catalogue, and a result outside the fixed vocabulary. The
    name is the contract: refusing is the writer's job, and swallowing the refusal is not an option
    the caller has.
    """


class AuditContextRequired(RuntimeError):
    """No `app.tenant_id` on this session: refuse to write rather than chain into the wrong trail.

    Fail-closed, like `app.core.db.tenant_transaction` itself. A writer that cannot resolve the
    tenant must not guess one — a platform-level event with no tenant is design OPEN-7 and is
    deliberately not implemented here.
    """


@dataclass(frozen=True)
class AuditEvent:
    """One event as a caller describes it.

    The envelope fields the caller does **not** supply are the ones the platform owns: `event_id`
    (the writer assigns it), `timestamp` (the server clock), `tenant_id` (the resolved session),
    `actor_id`/`actor_role`/`request_id`/`correlation_id` (the session context), `prev_hash` and
    `hash` (the chain), and `resource_type` (the catalogue's binding for the action).
    """

    action: str
    result: str
    resource_id: uuid.UUID | None = None
    reason: str | None = None
    source_ip: str | None = None
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ChainBreak:
    """The first place a tenant's chain stops proving itself.

    `event_id` is the identifier of the row the break was detected *at* — the sequence position, the
    identifier, and why the link failed, which is what an incident report needs.
    """

    sequence: int
    event_id: uuid.UUID
    timestamp: datetime
    reason: str
    expected: str
    actual: str


@dataclass(frozen=True)
class ChainReport:
    """The outcome of walking one tenant's chain.

    An intact chain reports `verified=True` and the head hash, which is what the export manifest and
    the scheduled verification report carry.
    """

    tenant_id: uuid.UUID
    verified: bool
    events: int
    head_hash: str
    first_break: ChainBreak | None


def canonical_json(value: Mapping[str, Any]) -> str:
    """The canonical serialisation the hash is computed over.

    Sorted keys, UTF-8, no insignificant whitespace (`03-design.md` §"Hash chain"). Two processes
    serialising the same event produce the same bytes, which is what makes the chain verifiable by
    something that is not the application.
    """
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _timestamp_form(value: datetime) -> str:
    """One representation of a timestamp, whatever the database hands back.

    `psycopg` returns a `timestamptz` as an aware `datetime` in the session's time zone, and the
    writer stores its own UTC reading, so the canonical form normalises to UTC at microsecond
    precision. Microseconds are the stored precision, so this round-trips exactly.
    """
    if value.tzinfo is None:
        # A naive value can only come from a hand-written row; reading it as UTC is the only reading
        # that is stable across environments.
        return value.isoformat(timespec="microseconds")
    return value.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="microseconds")


def canonical_payload(entry: AuditLogEntry) -> dict[str, Any]:
    """The event without `hash`, in the canonical field set. `prev_hash` is included.

    Public because the export bundle and the offline checker recompute a hash from stored values, and
    both must read the event exactly as the writer did.
    """
    return {
        "action": entry.action,
        "actor_id": None if entry.actor_id is None else str(entry.actor_id),
        "actor_role": entry.actor_role,
        "correlation_id": entry.correlation_id,
        "event_id": str(entry.event_id),
        "metadata": None if entry.payload is None else dict(entry.payload),
        "prev_hash": entry.prev_hash,
        "reason": entry.reason,
        "request_id": entry.request_id,
        "resource_id": None if entry.resource_id is None else str(entry.resource_id),
        "resource_type": entry.resource_type,
        "result": entry.result,
        "source_ip": entry.source_ip,
        "tenant_id": None if entry.tenant_id is None else str(entry.tenant_id),
        "timestamp": _timestamp_form(entry.timestamp),
    }


def compute_hash(entry: AuditLogEntry) -> str:
    """`SHA-256(canonical_json(event without hash) ‖ prev_hash)`, hex encoded.

    The concatenation is the canonical JSON bytes followed by the previous hash's own bytes — the
    previous hash's **hex** form, which is the form the chain is chained in and the form the genesis
    value is written in (64 zero *characters*). One representation end to end: the same bytes are
    hashed here, stored in the column and exported in the JSONL bundle.
    """
    return hashlib.sha256(
        canonical_json(canonical_payload(entry)).encode("utf-8")
        + entry.prev_hash.encode("ascii")
    ).hexdigest()


def _chain_lock_key(tenant_id: uuid.UUID) -> int:
    """The advisory-lock key for one tenant's chain, derived from the tenant id.

    `SHA-256(uuid) % 2**31` keeps it inside the positive `int4` range and is stable across processes.
    It is a lock key, not a secret: the only thing it has to be is the same number for the same
    tenant in every writer.
    """
    digest = hashlib.sha256(str(tenant_id).encode("ascii")).digest()
    return int.from_bytes(digest[:4], "big") % (2**31)


def _session_setting(session: Session, key: str) -> str | None:
    """Read a `SET LOCAL` setting on the session's current transaction."""
    value = (
        session.connection()
        .execute(text("SELECT current_setting(:key, true)"), {"key": key})
        .scalar()
    )
    return None if value in (None, "") else str(value)


def tenant_of(session: Session) -> uuid.UUID:
    """The tenant `app.tenant_id` names on this session, or a refusal.

    Public because [`record`][app.modules.audit.service.record] is not the only function that has to
    read the tenant from the transaction rather than take it as a parameter: the read API and the
    export do too, and *"the tenant is resolved, never supplied"* (INV-1) has to hold for every one of
    them. Refuses rather than guessing.
    """
    raw = _session_setting(session, "app.tenant_id")
    if raw is None:
        raise AuditContextRequired(
            "no app.tenant_id on this session; use app.core.db.tenant_transaction"
        )
    return uuid.UUID(raw)


def _session_info(session: Session, key: str) -> str | None:
    """Read one request-scoped value the caller left on the session.

    `app.core.db.tenant_transaction` records the actor, the request and the correlation identifiers
    in `session.info`; the writer reads them from there rather than taking them as parameters, so a
    caller cannot describe an event as coming from somebody else.
    """
    value = session.info.get(key)
    return None if value is None else str(value)


def _entry(
    event: AuditEvent,
    *,
    event_id: uuid.UUID,
    timestamp: datetime,
    prev_hash: str,
    tenant_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    request_id: str,
    correlation_id: str | None,
) -> AuditLogEntry:
    """Assemble the row. `resource_type` comes from the catalogue, never from the caller."""
    return AuditLogEntry(
        event_id=event_id,
        timestamp=timestamp,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        action=event.action,
        resource_type=resource_type_for(event.action),
        resource_id=event.resource_id,
        result=event.result,
        reason=event.reason,
        source_ip=event.source_ip,
        request_id=request_id,
        correlation_id=correlation_id,
        prev_hash=prev_hash,
        hash="",
        payload=None if event.payload is None else dict(event.payload),
    )


def _validate(event: AuditEvent) -> None:
    """Refuse anything the catalogue or the envelope does not name, before a row is built.

    Deny by default: an action outside the closed catalogue is refused, and the payload allow-list for
    an action with no entry is the empty set, so a new action carries nothing until somebody adds a
    row and a test (T1-22).
    """
    if event.action not in ACTIONS:
        raise AuditWriteRefused(
            f"{PAYLOAD_REJECTED}: {event.action!r} is not in the action catalogue "
            "(docs/features/04-audit-log/05-data-and-audit.md, 'The action catalogue')"
        )
    if event.result not in RESULTS:
        raise AuditWriteRefused(
            f"{PAYLOAD_REJECTED}: result {event.result!r} is not one of {sorted(RESULTS)}"
        )
    supplied = set(event.payload or {})
    allowed = PAYLOAD_ALLOW_LIST.get(event.action, frozenset())
    unlisted = supplied - allowed
    if unlisted:
        raise AuditWriteRefused(
            f"{PAYLOAD_REJECTED}: {event.action} does not allow metadata key(s) "
            + ", ".join(sorted(unlisted))
            + f"; the allow-list is {sorted(allowed)}"
        )
    # A second lock on the same door, and the one that keeps the *allow-list* honest: a key nobody
    # may carry at all — a clinical value added to an action's row by mistake — is caught here.
    unknown = supplied - PAYLOAD_KEYS
    if unknown:
        raise AuditWriteRefused(
            f"{PAYLOAD_REJECTED}: metadata key(s) "
            + ", ".join(sorted(unknown))
            + " are not in the payload vocabulary at all"
        )


def record(session: Session, event: AuditEvent) -> AuditLogEntry:
    """Insert one audit event on the caller's transaction, chained to the tenant's previous hash.

    Returns the inserted entry with `hash` and `prev_hash` set, so a caller can report the head hash
    without a second query. Raises
    [`AuditWriteRefused`][app.modules.audit.service.AuditWriteRefused] for a payload or action the
    catalogue does not name, and lets a database error propagate untouched: the caller's transaction
    is the one that must fail (R4).
    """
    _validate(event)

    tenant_id = tenant_of(session)

    request_id = _session_info(session, "request_id") or "-"
    correlation_id = _session_info(session, "correlation_id")
    raw_actor = _session_info(session, "actor_id")
    actor_id = None if raw_actor is None else uuid.UUID(raw_actor)
    actor_role = _session_info(session, "actor_role")

    # Serialise every writer for this tenant before reading the head of its chain. Without this, two
    # concurrent writers read the same `prev_hash` and insert two rows chaining to the same
    # predecessor: a fork, which verification reports as a break even though nothing was tampered
    # with. The lock is `xact`-scoped, so `COMMIT`/`ROLLBACK` releases it.
    session.connection().execute(
        text("SELECT pg_advisory_xact_lock(:class_id, :key)"),
        {"class_id": _CHAIN_LOCK_CLASS, "key": _chain_lock_key(tenant_id)},
    )

    previous = session.exec(
        select(AuditLogEntry)
        .where(AuditLogEntry.tenant_id == tenant_id)
        .order_by(
            col(AuditLogEntry.timestamp).desc(), col(AuditLogEntry.event_id).desc()
        )
        .limit(1)
    ).first()
    prev_hash = GENESIS_HASH if previous is None else previous.hash

    entry = _entry(
        event,
        event_id=uuid.uuid4(),
        timestamp=datetime.now(UTC),
        prev_hash=prev_hash,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
        correlation_id=correlation_id,
    )
    entry.hash = compute_hash(entry)

    session.add(entry)
    # Flush rather than commit: the row reaches the database inside the caller's transaction, so a
    # constraint failure surfaces at the audit write rather than at the caller's commit.
    session.flush()
    return entry


def chain(session: Session, *, tenant_id: uuid.UUID) -> Iterator[AuditLogEntry]:
    """Every event in one tenant's chain, oldest first.

    The order is `(timestamp, event_id)`, which is the primary key and therefore total. One
    transaction, one consistent snapshot, so verification sees a chain rather than a moving target.
    """
    statement = (
        select(AuditLogEntry)
        .where(AuditLogEntry.tenant_id == tenant_id)
        .order_by(col(AuditLogEntry.timestamp), col(AuditLogEntry.event_id))
    )
    return iter(session.exec(statement).all())


def verify_chain(session: Session, *, tenant_id: uuid.UUID) -> ChainReport:
    """Walk one tenant's chain and report the first break, or the head hash.

    Three failures are detected, and each of them is a control the design names:

    - a **recomputed-hash mismatch** — a row whose stored `hash` is not what its own fields produce,
      which is what a mutated payload, reason or result looks like;
    - a **`prev_hash` mismatch** — a row that does not chain onto the row before it, which is what a
      deleted, re-linked or inserted row looks like;
    - a **sequence gap** — a row whose `prev_hash` is the genesis value but which is not the first
      event, which is what a truncated history looks like.

    Verification never repairs and never writes: a report is evidence, and a verifier that could
    rewrite the trail would be the vulnerability it exists to detect.
    """
    events: Sequence[AuditLogEntry] = list(chain(session, tenant_id=tenant_id))
    expected_prev = GENESIS_HASH
    for sequence, entry in enumerate(events, start=1):
        if not compare_digest(entry.prev_hash, expected_prev):
            return ChainReport(
                tenant_id=tenant_id,
                verified=False,
                events=len(events),
                head_hash=expected_prev,
                first_break=ChainBreak(
                    sequence=sequence,
                    event_id=entry.event_id,
                    timestamp=entry.timestamp,
                    reason="PREV_HASH_MISMATCH",
                    expected=expected_prev,
                    actual=entry.prev_hash,
                ),
            )
        recomputed = compute_hash(entry)
        if not compare_digest(recomputed, entry.hash):
            return ChainReport(
                tenant_id=tenant_id,
                verified=False,
                events=len(events),
                head_hash=expected_prev,
                first_break=ChainBreak(
                    sequence=sequence,
                    event_id=entry.event_id,
                    timestamp=entry.timestamp,
                    reason="HASH_MISMATCH",
                    expected=recomputed,
                    actual=entry.hash,
                ),
            )
        expected_prev = entry.hash

    return ChainReport(
        tenant_id=tenant_id,
        verified=True,
        events=len(events),
        head_hash=expected_prev,
        first_break=None,
    )


def tenant_ids(session: Session) -> Sequence[uuid.UUID]:
    """Every tenant with at least one audit event — the input to a full scheduled verification run.

    This is the one query in the module that crosses tenants, and it runs without an `app.tenant_id`.
    It is the *scheduler's* query and nothing else's: it returns identifiers only, never an event, and
    every subsequent read is scoped to one of the identifiers it returns.
    """
    rows = session.exec(
        select(col(AuditLogEntry.tenant_id))
        .where(col(AuditLogEntry.tenant_id).is_not(None))
        .distinct()
    ).all()
    return [row for row in rows if row is not None]


# --------------------------------------------------------------------------------------------
# The read path — keyset pagination, no offsets
# --------------------------------------------------------------------------------------------
#
# R12: *"Keyset on `(timestamp, event_id)`; default 50 max 200; unbounded scan `422`; range max 90
# days; cross-tenant id `404`; every call writes `audit.read`."*
#
# There is no `OFFSET` anywhere in this module, and that is a correctness decision rather than a
# performance one: an offset page silently skips or repeats rows when an event lands while a caller is
# paging, and an audit reader that can be made to miss events is worse than no reader. The cursor is
# the last row of the previous page, and it is HMAC-signed so a caller cannot forge a position.

# The cursor signature key is derived from the application secret rather than stored separately: the
# tenant is in the payload, the signature is what makes it unforgeable, and `SECRET_KEY` is the one
# secret the app already requires. A cursor carries no privilege of its own — a forged one could only
# name a different position in a trail the caller is already authorised to read, which is exactly why
# it still must not be forgeable.
_CURSOR_CONTEXT: Final[bytes] = b"clinos.audit.cursor.v1"

# R12's read range ceiling, in days. Declared here because the window rule is the service's: the
# schema imports this rather than the other way round, so there is one number and the service can be
# called without a request.
MAX_RANGE_DAYS: Final[int] = 90


class InvalidCursor(RuntimeError):
    """The cursor is malformed, truncated or not signed by this application.

    The router answers `422`: a cursor is an input, and an input that cannot be honoured is a client
    error rather than a silent restart at the beginning of the trail.
    """


class InvalidRange(ValueError):
    """The requested window is wider than 90 days, or runs backwards.

    R12 bounds the read range at 90 days. The check lives here rather than only in the schema so the
    service can be called directly — by the export path, by a script, by a test — and still refuse.
    """


def validate_window(
    *, from_timestamp: datetime | None, to_timestamp: datetime | None
) -> None:
    """Refuse a window wider than 90 days, or one that runs backwards.

    A half-supplied window is allowed here: [`bounded_window`][app.modules.audit.service.bounded_window]
    closes it at 90 days, because a single `from` with no `to` would otherwise be unbounded in the one
    direction that matters.
    """
    if from_timestamp is None or to_timestamp is None:
        return
    if to_timestamp < from_timestamp:
        raise InvalidRange("to must not be earlier than from")
    if to_timestamp - from_timestamp > timedelta(days=MAX_RANGE_DAYS):
        raise InvalidRange(
            f"the range may not exceed {MAX_RANGE_DAYS} days; narrow it or use the export path"
        )


def bounded_window(
    *, from_timestamp: datetime | None, to_timestamp: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """The effective window, with the 90-day ceiling applied even to a half-supplied range."""
    ceiling = timedelta(days=MAX_RANGE_DAYS)
    if from_timestamp is not None and to_timestamp is None:
        return from_timestamp, from_timestamp + ceiling
    if to_timestamp is not None and from_timestamp is None:
        return to_timestamp - ceiling, to_timestamp
    return from_timestamp, to_timestamp


@dataclass(frozen=True)
class AuditFilters:
    """The filter set the read path applies. Every field is optional; the router requires one."""

    action: str | None = None
    actor_id: uuid.UUID | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    result: str | None = None
    from_timestamp: datetime | None = None
    to_timestamp: datetime | None = None

    def as_payload(self) -> dict[str, Any]:
        """The filter set as the `audit.read` event's `query_filters`: names and values, no PHI.

        Only filters the caller actually supplied appear, so an event says what was asked for rather
        than what the defaults were. Every value here is an action name, a UUID, a result code or a
        timestamp — none of them is a clinical value, and there is no free-text field to leak one.
        """
        supplied: dict[str, Any] = {
            "action": self.action,
            "actor_id": None if self.actor_id is None else str(self.actor_id),
            "resource_type": self.resource_type,
            "resource_id": None if self.resource_id is None else str(self.resource_id),
            "result": self.result,
            "from": None
            if self.from_timestamp is None
            else self.from_timestamp.isoformat(),
            "to": None if self.to_timestamp is None else self.to_timestamp.isoformat(),
        }
        return {key: value for key, value in supplied.items() if value is not None}


@dataclass(frozen=True)
class AuditPage:
    """One keyset page, plus the cursor that continues it."""

    entries: Sequence[AuditLogEntry]
    next_cursor: str | None


def _cursor_secret() -> bytes:
    return str(settings.SECRET_KEY).encode("utf-8")


def _cursor_signature(payload: bytes) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(_CURSOR_CONTEXT + _cursor_secret() + payload).digest()[:16]
    ).decode("ascii")


def encode_cursor(entry: AuditLogEntry) -> str:
    """The opaque cursor that continues after `entry`.

    `(timestamp, event_id)` is the primary key, so the pair identifies one exact position in the
    trail — no tie can be skipped by a page boundary, and none can be visited twice.
    """
    payload = json.dumps(
        {"e": str(entry.event_id), "t": entry.timestamp.isoformat()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{body}.{_cursor_signature(payload)}"


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """The `(timestamp, event_id)` a cursor points at, or a refusal.

    Fails closed on every malformed input: wrong shape, bad base64, bad JSON, missing keys,
    unparseable values, and a signature that does not match. There is no partial trust here — the
    cursor is either the one this application issued or it is refused.
    """
    try:
        body, signature = cursor.split(".", 1)
        padding = "=" * (-len(body) % 4)
        payload = base64.urlsafe_b64decode(body + padding)
    except (ValueError, TypeError) as error:
        raise InvalidCursor("the cursor is not a cursor this API issued") from error

    if not compare_digest(signature, _cursor_signature(payload)):
        raise InvalidCursor("the cursor signature does not verify")

    try:
        decoded = json.loads(payload)
        timestamp = datetime.fromisoformat(str(decoded["t"]))
        event_id = uuid.UUID(str(decoded["e"]))
    except (ValueError, KeyError, TypeError) as error:
        raise InvalidCursor("the cursor does not name a position") from error
    return timestamp, event_id


def _read_statement(
    filters: AuditFilters, cursor: tuple[datetime, uuid.UUID] | None
) -> Any:
    """The keyset query for one page, newest first.

    Newest first because an audit reader almost always wants the most recent events, and the
    `(tenant_id, timestamp DESC)` index the migration creates serves exactly that order. The cursor
    predicate is the strict row comparison `(timestamp, event_id) < (cursor_timestamp,
    cursor_event_id)`, expanded because SQLAlchemy has no tuple-comparison shorthand that is portable.
    """
    statement = select(AuditLogEntry)
    conditions = []
    if filters.action is not None:
        conditions.append(AuditLogEntry.action == filters.action)
    if filters.actor_id is not None:
        conditions.append(AuditLogEntry.actor_id == filters.actor_id)
    if filters.resource_type is not None:
        conditions.append(AuditLogEntry.resource_type == filters.resource_type)
    if filters.resource_id is not None:
        conditions.append(AuditLogEntry.resource_id == filters.resource_id)
    if filters.result is not None:
        conditions.append(AuditLogEntry.result == filters.result)
    if filters.from_timestamp is not None:
        conditions.append(AuditLogEntry.timestamp >= filters.from_timestamp)
    if filters.to_timestamp is not None:
        conditions.append(AuditLogEntry.timestamp < filters.to_timestamp)
    if cursor is not None:
        cursor_timestamp, cursor_event_id = cursor
        conditions.append(
            or_(
                AuditLogEntry.timestamp < cursor_timestamp,
                and_(
                    AuditLogEntry.timestamp == cursor_timestamp,
                    AuditLogEntry.event_id < cursor_event_id,
                ),
            )
        )
    if conditions:
        statement = statement.where(*conditions)
    return statement.order_by(
        col(AuditLogEntry.timestamp).desc(), col(AuditLogEntry.event_id).desc()
    )


def read_page(
    session: Session,
    *,
    filters: AuditFilters,
    limit: int,
    cursor: str | None = None,
) -> AuditPage:
    """One page of the tenant's trail, and the cursor that continues it.

    The tenant comes from the session's `app.tenant_id`, so the query is scoped by the forced RLS
    policy as well as by the explicit predicate. A row from another tenant is not denied — it is
    simply not in the result set, which is what the test plan's S1 requires (*"no B row, not even as a
    count"*).

    One extra row is fetched to decide whether a next page exists and is then discarded: that is how
    the caller learns there is more without a second `COUNT` query the design does not authorise.
    """
    tenant_id = tenant_of(session)
    decoded = None if cursor is None else decode_cursor(cursor)
    statement = (
        _read_statement(filters, decoded)
        .where(AuditLogEntry.tenant_id == tenant_id)
        .limit(limit + 1)
    )
    rows: Sequence[AuditLogEntry] = session.exec(statement).all()
    page, overflow = rows[:limit], rows[limit:]
    next_cursor = None if not overflow else encode_cursor(page[-1])
    return AuditPage(entries=page, next_cursor=next_cursor)


def event_by_id(session: Session, *, event_id: uuid.UUID) -> AuditLogEntry | None:
    """One event of the caller's tenant, or `None` for absent **and** for another tenant's.

    `None` is the only not-found answer, so the router can answer `404` for both cases and never
    confirms that another tenant's event exists — S2: *"cross-tenant event id `404 Not Found`, never
    `403`"*.
    """
    tenant_id = tenant_of(session)
    statement = select(AuditLogEntry).where(
        AuditLogEntry.event_id == event_id,
        # Defence in depth, exactly as the patients service does it: RLS is the isolation boundary and
        # this predicate is the second line for a connection that bypasses the policy.
        AuditLogEntry.tenant_id == tenant_id,
    )
    return session.exec(statement).first()


@dataclass(frozen=True)
class SingleRead:
    """The answer to one event lookup: the event, or `None` and the reason it was refused.

    It exists so the **service** can answer without raising. An HTTP error raised inside the
    tenant-scoped `with` block would roll the transaction back — including the `audit.read` event
    recording the refusal — and the one read that most needs evidence (a cross-tenant attempt) would
    be the one that leaves none. The route raises after the block has committed.
    """

    entry: AuditLogEntry | None
    denial_reason: str | None

    @property
    def found(self) -> bool:
        return self.entry is not None


def read_event(session: Session, *, event_id: uuid.UUID) -> SingleRead:
    """One event of the caller's tenant, audited — including the not-found path.

    `None` is the only not-found answer, so the route answers `404` for "absent" and "another
    tenant's" alike and never confirms that a foreign event exists (S2). The refusal is recorded as
    `audit.read` with `result = DENIED` on this transaction, which then commits: US-6 requires the
    *attempted* cross-tenant read to be audited, and a rollback is exactly how that evidence would be
    lost.
    """
    entry = event_by_id(session, event_id=event_id)
    if entry is None:
        audit_read_denial(
            session,
            filters=AuditFilters(resource_id=event_id),
            reason="CROSS_TENANT",
        )
        return SingleRead(entry=None, denial_reason="CROSS_TENANT")
    record(
        session,
        AuditEvent(
            action="audit.read",
            result="SUCCESS",
            resource_id=entry.resource_id,
            payload={"query_filters": {"event_id": str(event_id)}, "result_count": 1},
        ),
    )
    return SingleRead(entry=entry, denial_reason=None)


def read_events(
    session: Session,
    *,
    filters: AuditFilters,
    limit: int,
    cursor: str | None = None,
) -> AuditPage:
    """Read one page, and audit the read itself on the same transaction.

    R12 and the test plan's F9: *"every call writes `audit.read`"*, **including an empty result** —
    that is the point of the control. The event is written on the caller's transaction, so a read that
    cannot be audited fails rather than quietly answering, and the event carries the filters and the
    result count.
    """
    page = read_page(session, filters=filters, limit=limit, cursor=cursor)
    record(
        session,
        AuditEvent(
            action="audit.read",
            result="SUCCESS",
            payload={
                "query_filters": filters.as_payload(),
                "result_count": len(page.entries),
            },
        ),
    )
    return page


def audit_read_denial(
    session: Session, *, filters: AuditFilters, reason: str
) -> AuditLogEntry:
    """Record a refused or empty audit read, including a cross-tenant identifier lookup.

    The design requires a denial to be audited with the same fidelity as a success (control 6, R7),
    and US-6 says the *attempted* cross-tenant read is itself audited with the actor and the filters.
    A `404` on a foreign event id is therefore still an event — otherwise the one read that most needs
    evidence would be the one that leaves none.
    """
    return record(
        session,
        AuditEvent(
            action="audit.read",
            result="DENIED",
            reason=reason,
            payload={
                "query_filters": filters.as_payload(),
                "result_count": 0,
            },
        ),
    )


# --------------------------------------------------------------------------------------------
# Compliance export — the immutable-export seam
# --------------------------------------------------------------------------------------------
#
# `04-design.md` §"Immutable export path" specifies outbox row → SQS → S3 Object Lock in
# `ap-southeast-2`, `COMPLIANCE` mode, written by a write-only role, with a bucket policy that denies
# `s3:DeleteObject` to everyone but an audited break-glass role. R10 and `07-definition-of-done.md`
# part 6 require it, and it needs a bucket, credentials and an Object Lock configuration this slice
# does not have.
#
# What is implemented here is the part that has to be correct before any of that exists: the
# **bundle**. A canonical JSONL stream of one tenant's chain, plus a manifest carrying the head hash
# and a digest of the bytes. Both are produced from a single consistent snapshot and both are
# verified before they are produced — a broken chain is refused rather than exported, which is what
# `04-design.md` means by *"a break stops the upload"*.
#
# The adapter seam is [`AuditArchiveSink`][app.modules.audit.service.AuditArchiveSink]: one method,
# one bundle. `S3ObjectLockSink` in `archive.py` is the documented wiring point and raises rather
# than pretending. Recorded as a gap, not as done.

EXPORT_FORMAT_VERSION: Final[str] = "clinos.audit.export/1"


@dataclass(frozen=True)
class ExportBundle:
    """One tenant's chain as bytes, with the manifest that proves what it is.

    `jsonl` is the payload an Object Lock object would carry; `manifest` is the sidecar a regulator
    checks it against. `manifest["head_hash"]` is the immutable-export seam's anchor: it is the value
    that has to match the bucket object's own record, and the value a later export must extend.
    """

    tenant_id: uuid.UUID
    jsonl: bytes
    manifest: Mapping[str, Any]


def export_chain(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    generated_at: datetime | None = None,
) -> ExportBundle:
    """Build the canonical JSONL bundle and its manifest for one tenant's chain.

    The range is half-open `[from, to)` on `timestamp`, applied **after** the chain is walked, so a
    range that starts in the middle of a chain still reports the linkage it inherited rather than
    pretending to be genesis. Verification runs over the whole chain, not the range: a break outside
    the exported window is still a break, and shipping a slice of a broken chain is what
    `04-design.md` forbids.

    Raises [`AuditWriteRefused`][app.modules.audit.service.AuditWriteRefused] when the chain does not
    verify. The refusal is not a repair path and not a partial export.
    """
    report = verify_chain(session, tenant_id=tenant_id)
    if report.first_break is not None:
        raise AuditWriteRefused(
            "refusing to export a broken chain: tenant "
            f"{tenant_id} breaks at sequence {report.first_break.sequence} "
            f"({report.first_break.reason})"
        )

    events = list(chain(session, tenant_id=tenant_id))
    exported = [
        entry
        for entry in events
        if (from_timestamp is None or entry.timestamp >= from_timestamp)
        and (to_timestamp is None or entry.timestamp < to_timestamp)
    ]

    lines = [
        canonical_json(canonical_payload(entry)).encode("utf-8") + b"\n"
        for entry in exported
    ]
    jsonl = b"".join(lines)
    moment = (generated_at or datetime.now(UTC)).astimezone(UTC)
    manifest: dict[str, Any] = {
        "format": EXPORT_FORMAT_VERSION,
        "tenant_id": str(tenant_id),
        "generated_at": _timestamp_form(moment) + "Z",
        "event_count": len(exported),
        "first_event_id": None if not exported else str(exported[0].event_id),
        "last_event_id": None if not exported else str(exported[-1].event_id),
        "first_timestamp": (
            None if not exported else _timestamp_form(exported[0].timestamp) + "Z"
        ),
        "last_timestamp": (
            None if not exported else _timestamp_form(exported[-1].timestamp) + "Z"
        ),
        # The head of the *whole* tenant chain, which is the value the next export has to extend.
        "head_hash": report.head_hash,
        # A digest of the bytes exactly as they will be stored, so the object's own integrity can be
        # checked without re-deriving the chain.
        "bundle_sha256": hashlib.sha256(jsonl).hexdigest(),
        # The genesis link of the exported window: `GENESIS_HASH` for a bundle that starts at the
        # beginning of the chain, otherwise the hash the window inherits from the event before it.
        "window_prev_hash": (GENESIS_HASH if not exported else exported[0].prev_hash),
        "chain_verified": True,
    }
    return ExportBundle(tenant_id=tenant_id, jsonl=jsonl, manifest=manifest)


def write_bundle(directory: str, bundle: ExportBundle) -> tuple[str, str]:
    """Write a bundle and its manifest to `directory`, returning both paths.

    This is the local delivery path — an operator's compliance export, and the artefact the tests
    assert against. The S3 Object Lock path is the same two files through
    [`AuditArchiveSink`][app.modules.audit.service.AuditArchiveSink].
    """
    from pathlib import Path

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    stem = (
        f"audit-{bundle.tenant_id}-{bundle.manifest['generated_at'].replace(':', '')}"
    )
    jsonl_path = target / f"{stem}.jsonl"
    manifest_path = target / f"{stem}.manifest.json"
    jsonl_path.write_bytes(bundle.jsonl)
    manifest_path.write_text(
        json.dumps(dict(bundle.manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(jsonl_path), str(manifest_path)


class AuditArchiveSink(Protocol):  # pragma: no cover - a seam, not an implementation
    """Where a finished bundle goes. One method, so the seam is one decision.

    `04-design.md` requires the implementation to be an S3 Object Lock bucket in `COMPLIANCE` mode,
    written by a write-only role, and to refuse to upload a bundle whose chain did not verify. The
    refusal is already enforced upstream by [`export_chain`][app.modules.audit.service.export_chain],
    so an implementation only has to be *write-only* and *immutable*.
    """

    def put(self, bundle: ExportBundle) -> str:
        """Store the bundle and return the object's URI. Never rewrites an existing object."""
        ...


def archive(sink: AuditArchiveSink, bundle: ExportBundle) -> str:
    """Hand a verified bundle to the sink. The one call the exporter makes."""
    return sink.put(bundle)


__all__ = [
    "EXPORT_FORMAT_VERSION",
    "AuditArchiveSink",
    "AuditContextRequired",
    "AuditEvent",
    "AuditFilters",
    "AuditPage",
    "AuditWriteRefused",
    "ChainBreak",
    "ChainReport",
    "ExportBundle",
    "InvalidCursor",
    "SingleRead",
    "archive",
    "audit_read_denial",
    "canonical_json",
    "canonical_payload",
    "chain",
    "compute_hash",
    "decode_cursor",
    "encode_cursor",
    "event_by_id",
    "export_chain",
    "read_events",
    "read_page",
    "record",
    "tenant_ids",
    "tenant_of",
    "verify_chain",
    "write_bundle",
]
