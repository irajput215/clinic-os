"""The TGA approvals service facade — the only place `tga_approvals` is queried.

Design: `docs/features/08-tga-approvals/03-design.md` ("Deny-by-default path for each request",
"Expiry handling", "Post-Verification Immutability Guard"). Requirements:
`docs/features/08-tga-approvals/01-requirements.md` R1-R13. Tasks T2-7 to T2-15.

Everything outside this module reaches the two tables through here (`docs/reference/build-contract.md`
§7). The rules this module holds to, in the order the design fixes them:

- **Every query runs inside `app.core.db.tenant_transaction(...)`**, which sets `app.tenant_id` with
  `SET LOCAL` and refuses to open without a tenant. That is what activates the forced row-level
  security policy. The tenant is an argument the session resolved — never a request value (INV-1).
- **Every query also carries `tenant_id = :tenant_id`.** RLS is the isolation boundary; the predicate
  is the second line of defence for a connection that currently bypasses the policy.
- **A refusal is returned, not raised, inside the transaction.** An exception raised inside the
  `with` block rolls the transaction back — including the `DENIED` audit event recording it — so
  every refusal a caller can provoke is a [`Refusal`][app.modules.tga_approvals.service.Refusal] value
  that the router turns into a status code *after* the block has committed. The same shape the audit
  read path uses, for the same reason.
- **Nothing returns a raw ORM entity.** Rows are converted inside the transaction, before the session
  closes and expires its attributes.
- **Every state change is audited on the same transaction (INV-4)** through
  `app.modules.audit.service.record`, and every state change also appends a
  `tga_approval_events` row. A change that cannot be audited does not happen: a failure propagates
  out of the `with` block and takes the row with it.

## Why the audit payload is empty, and where the state detail lives

The platform's audit action catalogue is **closed** (`app/modules/audit/actions.py`): an action
outside it is refused by the writer, and an action with no `PAYLOAD_ALLOW_LIST` row may carry no
metadata at all. The catalogue names four TGA approval actions — `tga_approval.create`,
`tga_approval.modify`, `tga_approval.state_change`, `tga_approval.match`, `tga_approval.verify` — and
the feature document's own `approval.created` / `approval.verified` names are **not** in it, so
emitting them would be refused at runtime by the writer rather than audited. This module emits the
catalogue's names, and the from-state/to-state detail the feature asks for is carried by
`tga_approval_events`, the append-only domain table the design also requires for exactly that purpose.
The reconciliation is recorded in the PR body: it is a defect in the document set (two closed
vocabularies that disagree), not a judgement call taken silently here.

The one exception is `tga_approval.read` (the feature's `approval.read`, registered 2026-10-07): a read
changes nothing, so there is no domain row to carry its detail, and the allow-list gives it
`patient_id`, `query_filters` and `result_count` - identifiers, codes and counts, never a value.

## The validity boundary is one function (D-006 §2)

[`within_validity_window`][app.modules.tga_approvals.service.within_validity_window] is the single
place the boundary is decided, so the Clinical Safety Officer's ruling lands in one place. It is
half-open `[valid_from, valid_to)` — D-006's interim fail-safe — and the match, the expiry sweep and
the reporting query all read it rather than re-deriving it. The decision is OPEN with the Clinical
Safety Officer; if the ruling is "inclusive", this one function changes and every caller follows.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from hmac import compare_digest
from typing import Final

from fastapi import status
from sqlalchemy import ColumnElement, and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select, text

from app.core.config import settings
from app.core.db import tenant_transaction

# The audit module is reached through its service facade (`docs/reference/build-contract.md` §7). The
# import is one-way — `audit` knows nothing about `tga_approvals` — so there is no cycle.
from app.modules.audit import service as audit
from app.modules.patients import service as patients_service
from app.modules.tga_approvals.models import (
    APPROVAL_STATES,
    LEGAL_TRANSITIONS,
    TgaApproval,
    TgaApprovalEvent,
)
from app.modules.tga_approvals.schemas import (
    SupersedeChainLink,
    TgaApprovalCreate,
    TgaApprovalDetail,
    TgaApprovalDigest,
    TgaApprovalRead,
    TgaApprovalRegister,
    TgaApprovalRegisterCounts,
    TgaApprovalRegisterRow,
    TgaApprovalsPublic,
    TgaApprovalSupersede,
    TgaMatchResponse,
    ValidityInterval,
)

__all__ = [
    "APPLICATION_NUMBER_MISMATCH",
    "APPROVAL_CREATE",
    "APPROVAL_MATCH",
    "APPROVAL_READ",
    "APPROVAL_STATE_CHANGE",
    "APPROVAL_VERIFY",
    "CROSS_TENANT",
    "DUPLICATE_APPROVAL_GRAIN",
    "ILLEGAL_STATE_TRANSITION",
    "NOT_FOUND",
    "OVERLAPPING_ACTIVE_APPROVAL",
    "SYDNEY_TIMEZONE",
    "VERIFIER_CANNOT_BE_CREATOR",
    "ApprovalNotFound",
    "InvalidCursor",
    "MatchReason",
    "Refusal",
    "audit_denial",
    "create_approval",
    "evaluate_match",
    "evaluated_timezone",
    "expire_due_approvals",
    "get_approval",
    "last_expiring_valid_to",
    "list_approvals",
    "list_register",
    "match_approval",
    "needs_action_digest",
    "revoke_approval",
    "service_date_today",
    "supersede_approval",
    "verify_approval",
    "within_validity_window",
]

# --------------------------------------------------------------------------------------------
# The catalogue's actions, and the reason codes the feature documents fix
# --------------------------------------------------------------------------------------------

APPROVAL_CREATE: Final[str] = "tga_approval.create"
APPROVAL_VERIFY: Final[str] = "tga_approval.verify"
APPROVAL_STATE_CHANGE: Final[str] = "tga_approval.state_change"
APPROVAL_MATCH: Final[str] = "tga_approval.match"
# `08-tga-approvals/05-data-and-audit.md`'s `approval.read`, registered in doc 07 section 1 under the
# catalogue's lowercase dotted form on 2026-10-07 (owner decision). One event per list page or detail
# read, never one per row (US-2), refusals included.
APPROVAL_READ: Final[str] = "tga_approval.read"

# The refusal codes. Each is the code a document names, and each maps to exactly one status:
# `01-requirements.md`'s negative decision matrix, T2-3, T2-8 and T2-13.
NOT_FOUND: Final[str] = "TGA_APPROVAL_NOT_FOUND"
CROSS_TENANT: Final[str] = "CROSS_TENANT"
ILLEGAL_STATE_TRANSITION: Final[str] = "ILLEGAL_STATE_TRANSITION"
DUPLICATE_APPROVAL_GRAIN: Final[str] = "DUPLICATE_APPROVAL_GRAIN"
OVERLAPPING_ACTIVE_APPROVAL: Final[str] = "TGA_OVERLAPPING_ACTIVE_APPROVAL"
VERIFIER_CANNOT_BE_CREATOR: Final[str] = "VERIFIER_CANNOT_BE_CREATOR"
APPLICATION_NUMBER_MISMATCH: Final[str] = "TGA_APPLICATION_NUMBER_MISMATCH"
CONSTRAINT_VIOLATION: Final[str] = "TGA_CONSTRAINT_VIOLATION"

# D-006 §2 fixes the zone the boundary is read in, and forbids the server's local zone. It is a
# constant here rather than a setting: a per-tenant timezone would be a different clinical decision.
SYDNEY_TIMEZONE: Final[str] = "Australia/Sydney"

# The read path's page ceiling (T-04.12: *"pagination ceiling (`limit <= 100`)"*).
MAX_PAGE_SIZE: Final[int] = 100
DEFAULT_PAGE_SIZE: Final[int] = 25

# The register's expiry window. 30 days is the register's "Needs action" window
# (`docs2/sdlc/05-approvals/requirements.md`); the ceiling is the longest window an approval can
# have (R3, two years), beyond which "expiring within" selects every active approval.
DEFAULT_EXPIRING_WITHIN_DAYS: Final[int] = 30
MAX_EXPIRING_WITHIN_DAYS: Final[int] = 731

# The reason a `tga_approval.read` event carries when the client sent a `tenant_id`: it is ignored,
# and the attempt is written down (INV-1). The code `users_roles` already audits for the same thing.
CLIENT_TENANT_ID_IGNORED: Final[str] = "CLIENT_TENANT_ID_IGNORED"

# The cursor is signed with the application secret, exactly as the audit read path's is: a cursor
# carries no privilege, but one that could be forged could name a position in a list the caller is
# not authorised to have asked for.
_CURSOR_CONTEXT: Final[bytes] = b"clinos.tga.approvals.cursor.v1"

# How far the supersede chain is walked. A chain longer than this is not a chain, it is a cycle or a
# corrupt history, and the walk stops rather than looping.
_MAX_CHAIN_HOPS: Final[int] = 32


class MatchReason(StrEnum):
    """The machine-readable gate reasons (`01-requirements.md`'s negative matrix, T2-28).

    `REJECTED` is the one code the matrix does not list and the state machine requires: a rejection
    is a terminal state a verifier can reach, so the gate has to be able to name it.
    """

    NOT_FOUND = "TGA_APPROVAL_NOT_FOUND"
    CATEGORY_MISMATCH = "TGA_CATEGORY_MISMATCH"
    DOSAGE_FORM_MISMATCH = "TGA_DOSAGE_FORM_MISMATCH"
    EXPIRED = "TGA_APPROVAL_EXPIRED"
    NOT_YET_EFFECTIVE = "TGA_APPROVAL_NOT_YET_EFFECTIVE"
    REVOKED = "TGA_APPROVAL_REVOKED"
    PENDING_VERIFICATION = "TGA_APPROVAL_PENDING_VERIFICATION"
    SUPERSEDED = "TGA_APPROVAL_SUPERSEDED"
    REJECTED = "TGA_APPROVAL_REJECTED"


# The reason a state is refused by the gate, before the window is even considered. A row that is not
# `ACTIVE` cannot authorise anything, whatever the dates say.
_STATE_REASONS: Final[dict[str, MatchReason]] = {
    "PENDING": MatchReason.PENDING_VERIFICATION,
    "REVOKED": MatchReason.REVOKED,
    "SUPERSEDED": MatchReason.SUPERSEDED,
    "REJECTED": MatchReason.REJECTED,
    "EXPIRED": MatchReason.EXPIRED,
}


@dataclass(frozen=True)
class Refusal:
    """A refused operation, with the code, the status and the sentence the client is shown.

    Returned rather than raised so the transaction that carries its `DENIED` audit event commits.
    The router raises it after the block (`docs/features/04-audit-log/03-design.md`, "the one read
    that most needs evidence must not be the one that leaves none").
    """

    code: str
    status_code: int
    message: str


def _refuse(code: str, status_code: int, message: str) -> Refusal:
    return Refusal(code=code, status_code=status_code, message=message)


class ApprovalNotFound(Exception):
    """Raised only by callers outside a request context that must fail hard."""


class InvalidCursor(RuntimeError):
    """The cursor is malformed, truncated or not signed by this application. The router answers `422`."""


# --------------------------------------------------------------------------------------------
# The validity boundary — D-006 §2, one function
# --------------------------------------------------------------------------------------------


def within_validity_window(
    *, valid_from: date, valid_to: date, date_of_service: date
) -> bool:
    """Is `date_of_service` inside `[valid_from, valid_to)`? The **only** place this is decided.

    D-006 §2 (*"Validity-window boundary — half-open `[valid_from, valid_to)` applies, as an interim
    fail-safe position only, pending Clinical Safety Officer sign-off"*). Until the Clinical Safety
    Officer rules, the implementation uses the narrower window, because the two failure modes are not
    symmetric: failing narrow refuses a prescription on the final day of a legitimate approval, and
    failing wide dispenses an unapproved therapeutic good outside its regulatory authorisation.

    The decision is OPEN (`docs/reference/decisions/D-006-approval-grain-and-validity-boundary.md`,
    open item 1). When it closes, **this function changes and nothing else does**: the match, the
    expiry sweep and any reporting query call it, and no caller re-derives the comparison.

    `date_of_service` is a `date`, and D-006 requires the boundary to be evaluated in
    `Australia/Sydney` rather than the server's local zone. A bare date has no zone to read, so the
    zone enters where a *service date* is derived from a clock —
    [`service_date_today`][app.modules.tga_approvals.service.service_date_today] — and the comparison
    itself is zone-free by construction, which is what makes it reproducible from stored values.
    """
    return valid_from <= date_of_service < valid_to


def last_expiring_valid_to(*, today: date, within_days: int) -> date:
    """The latest `valid_to` whose **last covered day** is at most `within_days` after `today`.

    "Expiring within N days" is a statement about the last day an approval still authorises, and
    which day that is depends on the same D-006 boundary
    [`within_validity_window`][app.modules.tga_approvals.service.within_validity_window] decides.
    Under the interim half-open `[valid_from, valid_to)` the last covered day is `valid_to - 1`, so
    the bound is `today + within_days + 1`. It sits beside the boundary function on purpose: if the
    Clinical Safety Officer rules the end date inclusive, both change together.
    """
    return today + timedelta(days=within_days + 1)


def evaluated_timezone() -> str:
    """The zone the boundary is read in — *"evaluate the boundary in a single named timezone
    (`Australia/Sydney`), never the server's local zone"* (D-006 §2)."""
    return SYDNEY_TIMEZONE


def service_date_today(session: Session) -> date:
    """Today's service date, from the **database** clock in `Australia/Sydney`.

    T2-10: *"application instances do not evaluate expiry from their own clocks"*. A fleet whose
    instances disagree — or a container in UTC during a Sydney evening — would otherwise expire a
    different set of rows depending on which worker ran.
    """
    value = (
        session.connection()
        .execute(
            text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE :zone)::date"),
            {"zone": SYDNEY_TIMEZONE},
        )
        .scalar_one()
    )
    assert isinstance(value, date), "the database clock must answer with a date"
    return value


# --------------------------------------------------------------------------------------------
# The audit seam
# --------------------------------------------------------------------------------------------


def _record(
    session: Session,
    *,
    action: str,
    resource_id: uuid.UUID | None,
    result: str = "SUCCESS",
    reason: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    """Write one platform audit event on the caller's transaction.

    The action catalogue allows no metadata for a TGA approval write (see the module docstring), so
    the envelope carries the whole record: actor, tenant, role, request and correlation identifiers,
    `resource_id`, `result` and `reason`. The domain detail is in `tga_approval_events`. Only
    `tga_approval.read` passes a `payload`, and the writer refuses any key its allow-list lacks.
    """
    audit.record(
        session,
        audit.AuditEvent(
            action=action,
            result=result,
            resource_id=resource_id,
            reason=reason,
            payload=payload,
        ),
    )


def _append_event(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    from_state: str | None,
    to_state: str,
    reason: str | None,
    actor_id: uuid.UUID | None,
    source: str,
) -> None:
    """Append one immutable lifecycle row (design §"Post-Verification Immutability Guard")."""
    session.add(
        TgaApprovalEvent(
            tenant_id=tenant_id,
            approval_id=approval_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor_id=actor_id,
            source=source,
        )
    )
    session.flush()


def audit_denial(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    action: str,
    reason: str,
) -> None:
    """Record a refusal the policy layer made, in its own transaction.

    The design's deny-by-default path step 4 is *"audit the decision, including refusals"*, and the
    policy layer refuses **before** any domain transaction opens, so this is where a
    `403 PERMISSION_NOT_HELD` or a `404 CROSS_TENANT` decision is written down. A failure here
    propagates: a refusal that cannot be audited fails closed.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        _record(
            session, action=action, resource_id=None, result="DENIED", reason=reason
        )


# --------------------------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------------------------


def _load(
    session: Session, *, tenant_id: uuid.UUID, approval_id: uuid.UUID
) -> TgaApproval | None:
    """One approval of this tenant, or `None` for absent **and** for another tenant's.

    `None` is the only not-found answer, so the router answers `404` for both and never confirms
    that another tenant's approval exists (R8, S1).
    """
    return session.exec(
        select(TgaApproval).where(
            TgaApproval.id == approval_id,
            TgaApproval.tenant_id == tenant_id,
        )
    ).first()


def _read(row: TgaApproval) -> TgaApprovalRead:
    return TgaApprovalRead.model_validate(row)


def _chain(
    session: Session, *, tenant_id: uuid.UUID, row: TgaApproval
) -> list[SupersedeChainLink]:
    """The supersede chain this approval belongs to, oldest first.

    Both directions are walked — `supersedes_id` forward in time, `superseded_by_id` back — because
    either link alone leaves a gap: a replacement names its predecessor, and a predecessor names its
    replacement. The walk is bounded, so a corrupt cycle terminates rather than hanging a request.
    """
    seen = {row.id}
    links: list[SupersedeChainLink] = [SupersedeChainLink.model_validate(row)]

    current = row
    for _ in range(_MAX_CHAIN_HOPS):
        if current.supersedes_id is None or current.supersedes_id in seen:
            break
        previous = _load(
            session, tenant_id=tenant_id, approval_id=current.supersedes_id
        )
        if previous is None:
            break
        seen.add(previous.id)
        links.append(SupersedeChainLink.model_validate(previous))
        current = previous

    current = row
    for _ in range(_MAX_CHAIN_HOPS):
        if current.superseded_by_id is None or current.superseded_by_id in seen:
            break
        following = _load(
            session, tenant_id=tenant_id, approval_id=current.superseded_by_id
        )
        if following is None:
            break
        seen.add(following.id)
        links.append(SupersedeChainLink.model_validate(following))
        current = following

    links.sort(key=lambda link: (link.valid_from, str(link.id)))
    return links


def get_approval(
    *,
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> TgaApprovalDetail | None:
    """One approval and its supersede chain, or `None` for absent/cross-tenant (T2-12).

    The read is audited on its own transaction (US-7, *"every auditor read is logged"*), and so is
    the `None`: absent and another tenant's are the same answer, and a substituted identifier is the
    attempt the trail exists to hold.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        row = _load(session, tenant_id=tenant_id, approval_id=approval_id)
        if row is None:
            _record(
                session,
                action=APPROVAL_READ,
                resource_id=approval_id,
                result="DENIED",
                reason=CROSS_TENANT,
            )
            return None
        detail = TgaApprovalDetail.model_validate(row)
        detail.supersede_chain = _chain(session, tenant_id=tenant_id, row=row)
        _record(
            session,
            action=APPROVAL_READ,
            resource_id=row.id,
            payload={"patient_id": str(row.patient_id), "result_count": 1},
        )
        return detail


def _cursor_signature(payload: bytes) -> str:
    secret = str(settings.SECRET_KEY).encode("utf-8")
    return base64.urlsafe_b64encode(
        hashlib.sha256(_CURSOR_CONTEXT + secret + payload).digest()[:16]
    ).decode("ascii")


def encode_cursor(row: TgaApproval) -> str:
    """The opaque cursor that continues after `row`, on the page order `(created_at, id)`."""
    payload = json.dumps(
        {"i": str(row.id), "t": row.created_at.isoformat()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{body}.{_cursor_signature(payload)}"


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """The `(created_at, id)` a cursor names, or a refusal. Fails closed on every malformed input."""
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
        created_at = datetime.fromisoformat(str(decoded["t"]))
        approval_id = uuid.UUID(str(decoded["i"]))
    except (ValueError, KeyError, TypeError) as error:
        raise InvalidCursor("the cursor does not name a position") from error
    return created_at, approval_id


def _check_limit(limit: int) -> None:
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")


def _keyset_page(
    session: Session,
    *,
    conditions: list[ColumnElement[bool]],
    limit: int,
    cursor: tuple[datetime, uuid.UUID] | None,
) -> tuple[Sequence[TgaApproval], str | None]:
    """One newest-first page on the `(created_at, id)` keyset, and the cursor that continues it.

    Keyset and never `OFFSET`: an approval landing while a clinician pages must not make the next
    page skip or repeat a row, and a skipped clinical record is the failure mode that matters. The
    page asks for one row more than the caller wanted; that row proves whether a next page exists.
    The patient list and the register share this, so the two cannot page differently.
    """
    if cursor is not None:
        created_at, approval_id = cursor
        conditions = [
            *conditions,
            or_(
                col(TgaApproval.created_at) < created_at,
                and_(
                    col(TgaApproval.created_at) == created_at,
                    col(TgaApproval.id) < approval_id,
                ),
            ),
        ]
    rows: Sequence[TgaApproval] = session.exec(
        select(TgaApproval)
        .where(*conditions)
        .order_by(col(TgaApproval.created_at).desc(), col(TgaApproval.id).desc())
        .limit(limit + 1)
    ).all()
    page, overflow = rows[:limit], rows[limit:]
    return page, None if not overflow else encode_cursor(page[-1])


def list_approvals(
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> TgaApprovalsPublic:
    """One keyset page of a patient's approvals, newest first, tenant-scoped by RLS (T2-12, F15).

    Audited as one `tga_approval.read` per page with the patient and the row count, never one per
    row (US-2: *"`approval.read` once per patient-level access, not per row"*).
    """
    _check_limit(limit)
    decoded = None if cursor is None else decode_cursor(cursor)
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        page, next_cursor = _keyset_page(
            session,
            conditions=[
                col(TgaApproval.tenant_id) == tenant_id,
                col(TgaApproval.patient_id) == patient_id,
            ],
            limit=limit,
            cursor=decoded,
        )
        data = [_read(row) for row in page]
        _record(
            session,
            action=APPROVAL_READ,
            resource_id=None,
            payload={"patient_id": str(patient_id), "result_count": len(data)},
        )
        return TgaApprovalsPublic(data=data, count=len(data), next_cursor=next_cursor)


def _expiring(bound: date) -> ColumnElement[bool]:
    """`ACTIVE` and lapsing on or before `bound` (see `last_expiring_valid_to`)."""
    return and_(
        col(TgaApproval.state) == "ACTIVE",
        col(TgaApproval.valid_to) <= bound,
    )


def list_register(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    states: Collection[str] = (),
    expiring_within_days: int | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    client_tenant_id_supplied: bool = False,
) -> TgaApprovalRegister:
    """One keyset page of the practice-wide register, with the practice's totals.

    The contract is `docs2/sdlc/05-approvals/api.md` (agreed 2026-10-07). Two selectors, and a row
    is listed when it matches **either**: `states` (the approval is in one of them) and
    `expiring_within_days` (the approval is `ACTIVE` and its last covered day is at most that many
    days from today, already-lapsed ones the expiry job has not reached included). Neither given
    lists every approval. The union is what lets the register's "Needs action" filter - pending, or
    active and expiring within 30 days - be one keyset over one query instead of two pages merged in
    the client.

    "Today" is the database clock in `Australia/Sydney` (T2-10, D-006 section 2), never the
    application's. Page order and cursor are the patient list's, so a cursor continues only the
    filter it was issued for; a cursor carries no privilege, and RLS and the tenant predicate still
    bound every row.

    One `tga_approval.read` event per page, with the filters (state codes and a day count, never a
    value from a record) and the row count. A `tenant_id` the client sent is ignored and written down
    on that same event as `CLIENT_TENANT_ID_IGNORED` (INV-1).

    Patient names come from the patients facade on the same transaction, so a page and its names are
    one snapshot: this module never reads the `patients` table itself
    (`docs/reference/build-contract.md` section 7).
    """
    _check_limit(limit)
    if expiring_within_days is not None and not (
        0 <= expiring_within_days <= MAX_EXPIRING_WITHIN_DAYS
    ):
        raise ValueError(
            f"expiring_within_days must be between 0 and {MAX_EXPIRING_WITHIN_DAYS}"
        )
    wanted_states = sorted(set(states))
    decoded = None if cursor is None else decode_cursor(cursor)
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        today = service_date_today(session)
        window = (
            DEFAULT_EXPIRING_WITHIN_DAYS
            if expiring_within_days is None
            else expiring_within_days
        )
        bound = last_expiring_valid_to(today=today, within_days=window)

        selectors: list[ColumnElement[bool]] = []
        if wanted_states:
            selectors.append(col(TgaApproval.state).in_(wanted_states))
        if expiring_within_days is not None:
            selectors.append(_expiring(bound))
        conditions: list[ColumnElement[bool]] = [
            col(TgaApproval.tenant_id) == tenant_id
        ]
        if selectors:
            conditions.append(or_(*selectors))
        page, next_cursor = _keyset_page(
            session, conditions=conditions, limit=limit, cursor=decoded
        )
        rows = [_read(row) for row in page]

        by_state = dict.fromkeys(APPROVAL_STATES, 0)
        for state, total in session.exec(
            select(col(TgaApproval.state), func.count())
            .where(col(TgaApproval.tenant_id) == tenant_id)
            .group_by(col(TgaApproval.state))
        ).all():
            by_state[state] = total
        expiring = session.exec(
            select(func.count())
            .select_from(TgaApproval)
            .where(col(TgaApproval.tenant_id) == tenant_id, _expiring(bound))
        ).one()

        query_filters: dict[str, object] = {}
        if wanted_states:
            query_filters["state"] = wanted_states
        if expiring_within_days is not None:
            query_filters["expiring_within_days"] = expiring_within_days
        if decoded is not None:
            query_filters["cursor"] = True
        _record(
            session,
            action=APPROVAL_READ,
            resource_id=None,
            reason=CLIENT_TENANT_ID_IGNORED if client_tenant_id_supplied else None,
            payload={"query_filters": query_filters, "result_count": len(rows)},
        )
        names = patients_service.display_names(
            session,
            tenant_id=tenant_id,
            patient_ids=[row.patient_id for row in rows],
        )

    return TgaApprovalRegister(
        data=[
            TgaApprovalRegisterRow(
                **row.model_dump(), patient_display_name=names.get(row.patient_id)
            )
            for row in rows
        ],
        count=len(rows),
        next_cursor=next_cursor,
        counts=TgaApprovalRegisterCounts.model_validate(
            {
                "by_state": by_state,
                "expiring": expiring,
                "expiring_within_days": window,
            }
        ),
    )


def needs_action_digest(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    limit: int,
    client_tenant_id_supplied: bool = False,
) -> TgaApprovalDigest:
    """The register's "Needs action" set at a glance, on the caller's transaction (Today page).

    Pending approvals (oldest first) and `ACTIVE` approvals lapsing within the register's default
    window (soonest first), each list at most `limit`, with the practice's two totals. "Today" is the
    database clock in `Australia/Sydney` (T2-10), and "expiring" is `last_expiring_valid_to`, the
    same D-006 bound the register uses, so the two screens can never disagree.

    Audited exactly as the register is: one `tga_approval.read` on this transaction, with the
    register filter it is equivalent to and the number of rows returned. A `tenant_id` the client
    sent is written down on that event as `CLIENT_TENANT_ID_IGNORED` (INV-1).
    """
    _check_limit(limit)
    window = DEFAULT_EXPIRING_WITHIN_DAYS
    bound = last_expiring_valid_to(
        today=service_date_today(session), within_days=window
    )
    tenant = col(TgaApproval.tenant_id) == tenant_id
    pending_only = col(TgaApproval.state) == "PENDING"

    def total(condition: ColumnElement[bool]) -> int:
        return session.exec(
            select(func.count()).select_from(TgaApproval).where(tenant, condition)
        ).one()

    pending = session.exec(
        select(TgaApproval)
        .where(tenant, pending_only)
        .order_by(col(TgaApproval.created_at), col(TgaApproval.id))
        .limit(limit)
    ).all()
    expiring = session.exec(
        select(TgaApproval)
        .where(tenant, _expiring(bound))
        .order_by(col(TgaApproval.valid_to), col(TgaApproval.id))
        .limit(limit)
    ).all()
    names = patients_service.display_names(
        session,
        tenant_id=tenant_id,
        patient_ids=[row.patient_id for row in (*pending, *expiring)],
    )

    def rows(found: Sequence[TgaApproval]) -> list[TgaApprovalRegisterRow]:
        return [
            TgaApprovalRegisterRow(
                **_read(row).model_dump(),
                patient_display_name=names.get(row.patient_id),
            )
            for row in found
        ]

    digest = TgaApprovalDigest(
        pending_verification=total(pending_only),
        expiring=total(_expiring(bound)),
        expiring_within_days=window,
        pending=rows(pending),
        expiring_soon=rows(expiring),
    )
    _record(
        session,
        action=APPROVAL_READ,
        resource_id=None,
        reason=CLIENT_TENANT_ID_IGNORED if client_tenant_id_supplied else None,
        payload={
            "query_filters": {"state": ["PENDING"], "expiring_within_days": window},
            "result_count": len(pending) + len(expiring),
        },
    )
    return digest


# --------------------------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------------------------


def _duplicate_grain(
    session: Session, *, tenant_id: uuid.UUID, approval_in: TgaApprovalCreate
) -> bool:
    """Is there already a live row for this exact grain and window? (T2-12's duplicate refusal.)

    "Live" means not terminal: a `REVOKED` or `SUPERSEDED` row is history, and re-entry of the same
    grant after a revocation is a legitimate correction.
    """
    existing = session.exec(
        select(TgaApproval).where(
            TgaApproval.tenant_id == tenant_id,
            TgaApproval.patient_id == approval_in.patient_id,
            TgaApproval.tga_category == approval_in.tga_category,
            TgaApproval.dosage_form == approval_in.dosage_form,
            TgaApproval.valid_from == approval_in.valid_from,
            TgaApproval.valid_to == approval_in.valid_to,
            col(TgaApproval.state).in_(("PENDING", "ACTIVE")),
        )
    ).first()
    return existing is not None


def _create_row(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    tga_category: str,
    dosage_form: str,
    approval_reference: str,
    valid_from: date,
    valid_to: date,
    creation_reason: str,
    created_by: uuid.UUID,
    supersedes_id: uuid.UUID | None = None,
) -> TgaApproval:
    row = TgaApproval(
        tenant_id=tenant_id,
        patient_id=patient_id,
        tga_category=tga_category,
        dosage_form=dosage_form,
        approval_reference=approval_reference,
        valid_from=valid_from,
        valid_to=valid_to,
        state="PENDING",
        source="MANUAL_ENTRY",
        creation_reason=creation_reason,
        created_by=created_by,
        supersedes_id=supersedes_id,
    )
    session.add(row)
    session.flush()
    _append_event(
        session,
        tenant_id=tenant_id,
        approval_id=row.id,
        from_state=None,
        to_state="PENDING",
        reason=creation_reason,
        actor_id=created_by,
        source="MANUAL_ENTRY",
    )
    _record(session, action=APPROVAL_CREATE, resource_id=row.id)
    session.refresh(row)
    return row


def create_approval(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    approval_in: TgaApprovalCreate,
    actor_role: str | None = None,
) -> TgaApprovalRead | Refusal:
    """Record a manual entry for the resolved tenant; it starts `PENDING` (R1, R5, US-1).

    The patient is not looked up here: the composite foreign key `(tenant_id, patient_id)` refuses a
    patient of another tenant at the database, and `patient_id` is opaque to this module. A patient
    that does not exist is therefore a `409`/`422` from the constraint rather than a silent success —
    and the route checks the patient through the patients module first, so the ordinary answer is a
    `404` before any row is attempted.
    """
    try:
        with tenant_transaction(
            tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
        ) as session:
            if _duplicate_grain(session, tenant_id=tenant_id, approval_in=approval_in):
                _record(
                    session,
                    action=APPROVAL_CREATE,
                    resource_id=None,
                    result="DENIED",
                    reason=DUPLICATE_APPROVAL_GRAIN,
                )
                return _refuse(
                    DUPLICATE_APPROVAL_GRAIN,
                    status.HTTP_409_CONFLICT,
                    "An approval already exists for this patient, category, dosage form and window",
                )
            row = _create_row(
                session,
                tenant_id=tenant_id,
                patient_id=approval_in.patient_id,
                tga_category=approval_in.tga_category,
                dosage_form=approval_in.dosage_form,
                approval_reference=approval_in.approval_reference,
                valid_from=approval_in.valid_from,
                valid_to=approval_in.valid_to,
                creation_reason=approval_in.creation_reason,
                created_by=actor_id,
            )
            return _read(row)
    except IntegrityError as error:
        # The database refused what the service allowed — a check constraint, the composite patient
        # key, or the exclusion constraint. The `with` block has rolled the transaction back by the
        # time this runs, so the mapping is a plain refusal and nothing is left half-written.
        return _constraint_refusal(error)


def supersede_approval(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    approval_id: uuid.UUID,
    approval_in: TgaApprovalSupersede,
    actor_role: str | None = None,
) -> TgaApprovalRead | Refusal:
    """Request the replacement grant for an approval (T2-9, design §2).

    The replacement is created `PENDING` and linked to its predecessor by `supersedes_id`. It is the
    **verification** of the replacement that supersedes the predecessor — atomically, in the
    transaction that activates it — because four-eyes forbids the actor who creates a grant from
    being the actor who activates it (R5, T-04.10). A supersede that activated its own replacement
    would be exactly the self-verification the rule exists to prevent.

    Extensions and dosage changes require a new grant (R12): the grain of a verified row is
    immutable in the database, so amending in place is not an option this API leaves open.
    """
    try:
        with tenant_transaction(
            tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
        ) as session:
            previous = _load(session, tenant_id=tenant_id, approval_id=approval_id)
            if previous is None:
                _record(
                    session,
                    action=APPROVAL_CREATE,
                    resource_id=None,
                    result="DENIED",
                    reason=CROSS_TENANT,
                )
                return _refuse(
                    NOT_FOUND, status.HTTP_404_NOT_FOUND, "TGA approval not found"
                )
            if previous.state not in ("PENDING", "ACTIVE"):
                _record(
                    session,
                    action=APPROVAL_CREATE,
                    resource_id=previous.id,
                    result="DENIED",
                    reason=ILLEGAL_STATE_TRANSITION,
                )
                return _refuse(
                    ILLEGAL_STATE_TRANSITION,
                    status.HTTP_409_CONFLICT,
                    f"A {previous.state} approval cannot be superseded",
                )
            row = _create_row(
                session,
                tenant_id=tenant_id,
                patient_id=previous.patient_id,
                tga_category=previous.tga_category,
                dosage_form=previous.dosage_form,
                approval_reference=approval_in.approval_reference,
                valid_from=approval_in.valid_from,
                valid_to=approval_in.valid_to,
                creation_reason=approval_in.creation_reason,
                created_by=actor_id,
                supersedes_id=previous.id,
            )
            return _read(row)
    except IntegrityError as error:
        return _constraint_refusal(error)


def _constraint_refusal(error: IntegrityError) -> Refusal:
    """Map a database refusal to a code, without echoing the database's own message.

    The exclusion violation is the one case a caller can provoke legitimately, and it is the
    database's own proof that INV-2 holds: two overlapping `ACTIVE` rows at one grain do not exist.
    Everything else is a control the service should already have applied, so it is reported as a
    validation refusal rather than as an internal error — and never with the SQL text attached.
    """
    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    if sqlstate == "23P01":
        return _refuse(
            OVERLAPPING_ACTIVE_APPROVAL,
            status.HTTP_409_CONFLICT,
            "Another active approval already covers this grain",
        )
    return _refuse(
        CONSTRAINT_VIOLATION,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The approval could not be stored: it violates a clinical constraint",
    )


# --------------------------------------------------------------------------------------------
# Transitions
# --------------------------------------------------------------------------------------------


def _transition(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    row: TgaApproval,
    to_state: str,
    reason: str | None,
    actor_id: uuid.UUID | None,
    action: str,
    verified_by: uuid.UUID | None = None,
    superseded_by: uuid.UUID | None = None,
) -> None:
    """Apply one legal transition, or refuse it with an audited `409`.

    The map is `models.LEGAL_TRANSITIONS`, which the database trigger also enforces. A transition the
    map does not name is refused here with the code the tasks file fixes (`ILLEGAL_STATE_TRANSITION`)
    and a `DENIED` event, and would be refused by the trigger as well if it ever got past this.

    Every field the new state requires is set **before** the flush, so the row is never written in a
    state its own check constraints do not yet describe: `state = 'ACTIVE'` implies `verified_at`, and
    `state = 'SUPERSEDED'` implies `superseded_by_id`. Two statements would leave a window in which
    the row is invalid, and the database would refuse the first of them — measured, not assumed: the
    check constraint fires on the `UPDATE` that sets the state, not at commit.
    """
    if to_state not in LEGAL_TRANSITIONS.get(row.state, frozenset()):
        _record(
            session,
            action=action,
            resource_id=row.id,
            result="DENIED",
            reason=ILLEGAL_STATE_TRANSITION,
        )
        raise IllegalTransition(row.state, to_state)

    previous_state = row.state
    row.state = to_state
    if verified_by is not None:
        row.verified_by = verified_by
        row.verified_at = datetime.now(UTC)
    if superseded_by is not None:
        row.superseded_by_id = superseded_by
    if to_state == "REVOKED":
        row.revoked_reason_code = reason
        row.revoked_by = actor_id
        row.revoked_at = datetime.now(UTC)
    session.add(row)
    session.flush()
    _append_event(
        session,
        tenant_id=tenant_id,
        approval_id=row.id,
        from_state=previous_state,
        to_state=to_state,
        reason=reason,
        actor_id=actor_id,
        source=row.source,
    )


class IllegalTransition(Exception):
    """A transition the state machine does not permit. The router answers `409`."""

    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(f"{from_state} -> {to_state} is not a permitted transition")
        self.from_state = from_state
        self.to_state = to_state


def verify_approval(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    approval_id: uuid.UUID,
    application_number: str,
    actor_role: str | None = None,
) -> TgaApprovalRead | Refusal:
    """Activate a `PENDING` approval on an independent verifier's decision (R5, T2-13, T2-15).

    Four controls run in this order, and the first three write a `DENIED` event:

    1. the approval must exist in the caller's tenant — otherwise `404`, never `403`;
    2. the verifier must differ from the creator (`403 VERIFIER_CANNOT_BE_CREATOR`), which is the
       four-eyes rule T-04.10 names and which the database also enforces with
       `ck_tga_approvals_four_eyes`;
    3. the application number the verifier re-entered must be the one on the record
       (`422 TGA_APPLICATION_NUMBER_MISMATCH`) — a verification that does not check the reference it
       is verifying is not a control (T-04.2);
    4. the transition must be legal for the row's current state.

    If the row was created by [`supersede_approval`][app.modules.tga_approvals.service.supersede_approval],
    its predecessor moves to `SUPERSEDED` in this same transaction, so the moment the replacement
    becomes live is the moment the old grant stops being live. Exactly one non-superseded record
    remains, and the exclusion constraint proves it. The predecessor is moved **first** — the
    constraint is checked per statement, not at commit — and control 4 is settled before either
    write, so a refusal can never commit a half-applied supersede.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        row = _load(session, tenant_id=tenant_id, approval_id=approval_id)
        if row is None:
            _record(
                session,
                action=APPROVAL_VERIFY,
                resource_id=None,
                result="DENIED",
                reason=CROSS_TENANT,
            )
            return _refuse(
                NOT_FOUND, status.HTTP_404_NOT_FOUND, "TGA approval not found"
            )

        if row.created_by == actor_id:
            _record(
                session,
                action=APPROVAL_VERIFY,
                resource_id=row.id,
                result="DENIED",
                reason=VERIFIER_CANNOT_BE_CREATOR,
            )
            return _refuse(
                VERIFIER_CANNOT_BE_CREATOR,
                status.HTTP_403_FORBIDDEN,
                "The clinician who entered an approval cannot verify it",
            )

        if application_number.strip().upper() != row.approval_reference.strip().upper():
            _record(
                session,
                action=APPROVAL_VERIFY,
                resource_id=row.id,
                result="DENIED",
                reason=APPLICATION_NUMBER_MISMATCH,
            )
            return _refuse(
                APPLICATION_NUMBER_MISMATCH,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "The application number does not match the record being verified",
            )

        predecessor = _predecessor_to_supersede(session, tenant_id=tenant_id, row=row)

        # The legality of the replacement's own transition is settled **before** anything is
        # written. A refusal is returned from inside the `with` block and the block commits — that is
        # the whole point of the `Refusal` shape — so if the predecessor were superseded first and
        # the replacement then turned out not to be activatable, the commit would leave the
        # organisation with no live grant at the grain and no replacement to show for it.
        if "ACTIVE" not in LEGAL_TRANSITIONS.get(row.state, frozenset()):
            _record(
                session,
                action=APPROVAL_VERIFY,
                resource_id=row.id,
                result="DENIED",
                reason=ILLEGAL_STATE_TRANSITION,
            )
            return _refuse(
                ILLEGAL_STATE_TRANSITION,
                status.HTTP_409_CONFLICT,
                f"A {row.state} approval cannot be verified",
            )

        # The predecessor leaves `ACTIVE` **before** the replacement enters it, and both statements
        # are in this one transaction. The order is not a preference: `no_overlapping_active_approvals`
        # is a partial exclusion constraint on `state = 'ACTIVE'` and PostgreSQL checks it per
        # statement rather than at commit, so activating the replacement first collides with the very
        # grant it replaces (measured — it raises `23P01` on the `UPDATE`). The grain is never
        # unguarded: nothing outside this transaction can observe the instant between the two
        # statements, and the exclusion constraint proves that the moment both are written.
        if predecessor is not None:
            _transition(
                session,
                tenant_id=tenant_id,
                row=predecessor,
                to_state="SUPERSEDED",
                reason=None,
                actor_id=actor_id,
                action=APPROVAL_STATE_CHANGE,
                superseded_by=row.id,
            )

        _transition(
            session,
            tenant_id=tenant_id,
            row=row,
            to_state="ACTIVE",
            reason=None,
            actor_id=actor_id,
            action=APPROVAL_VERIFY,
            verified_by=actor_id,
        )

        _record(session, action=APPROVAL_VERIFY, resource_id=row.id)

        session.refresh(row)
        return _read(row)


def _predecessor_to_supersede(
    session: Session, *, tenant_id: uuid.UUID, row: TgaApproval
) -> TgaApproval | None:
    """The live predecessor this row replaces, if the grain says there is one (T2-9).

    Two ways for a replacement to exist, and both are honoured:

    - the row names it explicitly (`supersedes_id`, set by the supersede route); or
    - the row was created plain, and an `ACTIVE` approval at the same grain overlaps its window —
      which is the case the exclusion constraint would refuse outright. The service resolves it by
      superseding rather than failing, because *"superseding replaces atomically"* is the design's
      answer to the same-grain case and a clinician entering a corrected window should not have to
      know to name the row first.

    A row that is not `ACTIVE` is never superseded by a pending one: only a live grant is replaced.
    """
    if row.supersedes_id is not None:
        named = _load(session, tenant_id=tenant_id, approval_id=row.supersedes_id)
        if named is not None and named.state == "ACTIVE":
            return named
        return None

    overlapping = session.exec(
        select(TgaApproval).where(
            TgaApproval.tenant_id == tenant_id,
            TgaApproval.patient_id == row.patient_id,
            TgaApproval.tga_category == row.tga_category,
            TgaApproval.dosage_form == row.dosage_form,
            TgaApproval.state == "ACTIVE",
            TgaApproval.id != row.id,
            # Half-open overlap, written as the two comparisons it is equivalent to:
            # `[a, b)` intersects `[c, d)` exactly when `a < d` and `c < b`. This is the same
            # predicate the exclusion constraint's `&&` applies, and expressing it in the dates
            # keeps the query independent of the derived range column's representation.
            TgaApproval.valid_from < row.valid_to,
            TgaApproval.valid_to > row.valid_from,
        )
    ).first()
    return overlapping


def revoke_approval(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    approval_id: uuid.UUID,
    reason_code: str,
    actor_role: str | None = None,
) -> TgaApprovalRead | Refusal:
    """Revoke a `PENDING` or `ACTIVE` approval with a mandatory reason code (R6, US-6, T2-14).

    A revoked approval authorises nothing from the moment this transaction commits: the gate reads
    `state` and the window, and a `REVOKED` row fails on `state` alone. The `CHECK` that a revocation
    carries a reason is in the database as well, so an un-reasoned revocation is not storable.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        row = _load(session, tenant_id=tenant_id, approval_id=approval_id)
        if row is None:
            _record(
                session,
                action=APPROVAL_STATE_CHANGE,
                resource_id=None,
                result="DENIED",
                reason=CROSS_TENANT,
            )
            return _refuse(
                NOT_FOUND, status.HTTP_404_NOT_FOUND, "TGA approval not found"
            )
        try:
            _transition(
                session,
                tenant_id=tenant_id,
                row=row,
                to_state="REVOKED",
                reason=reason_code,
                actor_id=actor_id,
                action=APPROVAL_STATE_CHANGE,
            )
        except IllegalTransition:
            return _refuse(
                ILLEGAL_STATE_TRANSITION,
                status.HTTP_409_CONFLICT,
                f"A {row.state} approval cannot be revoked",
            )
        _record(session, action=APPROVAL_STATE_CHANGE, resource_id=row.id)
        session.refresh(row)
        return _read(row)


def expire_due_approvals(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> int:
    """Move every `ACTIVE` approval whose window has closed to `EXPIRED`. Idempotent (T2-10, T2-11).

    Two deliberate properties:

    - **the database clock decides**, in `Australia/Sydney` (`service_date_today`), never an
      application instance's clock;
    - **the boundary is the one function**: a row is due when `valid_to <= today`, because
      `[valid_from, valid_to)` does not include `valid_to` — the literal `valid_to < CURRENT_DATE`
      T2-10 writes would leave a row that is already unusable by the gate looking `ACTIVE` for one
      more day. T2-11 requires the match, the sweep and reporting to apply the same boundary, and
      this is that boundary.

    A second run on the same day finds nothing, so re-running the job cannot rewrite history: the
    transition out of `ACTIVE` is legal exactly once and the trigger refuses the rest. Each row
    written emits one `tga_approval.state_change` event and one `tga_approval_events` row, in the
    transaction that moved it.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        today = service_date_today(session)
        due: Sequence[TgaApproval] = session.exec(
            select(TgaApproval).where(
                TgaApproval.tenant_id == tenant_id,
                TgaApproval.state == "ACTIVE",
                TgaApproval.valid_to <= today,
            )
        ).all()
        for row in due:
            _transition(
                session,
                tenant_id=tenant_id,
                row=row,
                to_state="EXPIRED",
                reason=None,
                actor_id=actor_id,
                action=APPROVAL_STATE_CHANGE,
            )
            _record(session, action=APPROVAL_STATE_CHANGE, resource_id=row.id)
        return len(due)


# --------------------------------------------------------------------------------------------
# The point-in-time match
# --------------------------------------------------------------------------------------------


def match_approval(
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    tga_category: str,
    dosage_form: str,
    date_of_service: date,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> TgaMatchResponse:
    """Does an active approval cover this patient, grain and **consultation date**? (T2-27, R10)

    Fails closed at every step. `date_of_service` is the caller's value and is never replaced by
    `now()`: that is what makes a late expiry sweep unable to allow an expired approval (design,
    "Expiry handling"). A missing tenant context cannot reach here — `tenant_transaction` refuses to
    open — and a lookup error propagates, so the gate's caller denies.

    The answer carries the reason, the state and the window even when it refuses, so the prescribing
    screen can explain the block instead of showing a bare denial.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        answer = evaluate_match(
            session,
            tenant_id=tenant_id,
            patient_id=patient_id,
            tga_category=tga_category,
            dosage_form=dosage_form,
            date_of_service=date_of_service,
        )
        _record(
            session,
            action=APPROVAL_MATCH,
            resource_id=answer.approval_id,
            reason=answer.reason_code,
        )
        return answer


def evaluate_match(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    tga_category: str,
    dosage_form: str,
    date_of_service: date,
    lock: bool = False,
) -> TgaMatchResponse:
    """The match, on the **caller's** transaction, with no audit event of its own.

    This is the facade the prescription safety gate reaches the approvals through
    (`app.modules.prescriptions.gate`): the gate's decision has to be taken inside the signing and
    dispatch transactions, against the approval rows as they are at that instant, so it cannot open a
    transaction of its own the way `match_approval` does. The caller records the decision in its own
    vocabulary (`prescription.sign`, `prescription.dispatch_blocked`), on the same transaction.

    `lock=True` reads every approval row of the patient `FOR UPDATE`
    (`docs/features/10-prescription-safety-gate/01-requirements.md` R16, T-10.13): a revocation,
    supersede or expiry that is updating one of those rows either commits **before** this read - and
    the read waits for it and then sees the new state, because PostgreSQL re-evaluates a locked row
    after the blocking transaction commits - or it waits until the caller's transaction ends. There is
    no third interleaving in which the caller decides on a row state that a concurrent revocation has
    already replaced. The lock is held until the caller's transaction ends, so the decision and the
    state change it authorises commit together. `FOR UPDATE` rather than the `FOR SHARE` the gate
    document names: it is the stronger lock (it conflicts with everything `FOR SHARE` conflicts with),
    and it also serialises two gate decisions on one patient, which costs nothing at clinic scale.

    `populate_existing` makes the locked read refresh any copy the session already holds, so the
    decision can never be taken on a stale in-memory row.
    """
    statement = (
        select(TgaApproval)
        .where(
            TgaApproval.tenant_id == tenant_id,
            TgaApproval.patient_id == patient_id,
        )
        .order_by(col(TgaApproval.created_at).desc(), col(TgaApproval.id).desc())
    )
    if lock:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    rows: Sequence[TgaApproval] = session.exec(statement).all()

    answer = _decide(
        rows,
        tga_category=tga_category,
        dosage_form=dosage_form,
        date_of_service=date_of_service,
    )
    row = answer.row
    return TgaMatchResponse(
        matched=answer.reason is None,
        reason_code=None if answer.reason is None else answer.reason.value,
        state=None if row is None else row.state,
        approval_id=None if row is None else row.id,
        validity_interval=None
        if row is None
        else ValidityInterval(valid_from=row.valid_from, valid_to=row.valid_to),
        date_of_service=date_of_service,
        evaluated_timezone=evaluated_timezone(),
    )


@dataclass(frozen=True)
class _Decision:
    """One gate answer: the row it was decided on, and why it refused (`None` reason allows)."""

    reason: MatchReason | None
    row: TgaApproval | None


def _decide(
    rows: Sequence[TgaApproval],
    *,
    tga_category: str,
    dosage_form: str,
    date_of_service: date,
) -> _Decision:
    """The negative decision matrix, in one place.

    The row that decides is the one whose window **contains `date_of_service`**, whatever its state:
    the gate is asked about *this* consultation date, so a row that covers it explains the answer
    better than a row that does not. An `ACTIVE` covering row allows; a covering row in any other
    state blocks for the reason its own state names — which is the matrix's *"Superseded Row — In
    window"* row, and the only reading under which `TGA_APPROVAL_SUPERSEDED` is reachable for a date
    an approval actually covered.

    Only when **no** row covers the date do the dates decide: an elapsed `ACTIVE` grant says
    `EXPIRED`, one that has not started says `NOT_YET_EFFECTIVE`, both measured against
    `date_of_service` through
    [`within_validity_window`][app.modules.tga_approvals.service.within_validity_window] and never
    against "now". With no live row at the grain at all, the most recent row's state is the reason.

    A row at a *different* grain is reported as a category or dosage-form mismatch rather than as
    "not found", because the two produce different clinical actions: a mismatch says the patient has
    an approval for something else, and not-found says there is none at all.
    """
    same_grain = [
        row
        for row in rows
        if row.tga_category == tga_category and row.dosage_form == dosage_form
    ]
    if not same_grain:
        same_category = any(row.tga_category == tga_category for row in rows)
        same_form = any(row.dosage_form == dosage_form for row in rows)
        if same_form and not same_category:
            return _Decision(reason=MatchReason.CATEGORY_MISMATCH, row=None)
        if same_category and not same_form:
            return _Decision(reason=MatchReason.DOSAGE_FORM_MISMATCH, row=None)
        return _Decision(reason=MatchReason.NOT_FOUND, row=None)

    # An `ACTIVE` row is the only row that can allow. The exclusion constraint guarantees at most one
    # per **overlapping** window at this grain, so a grain can legitimately hold several `ACTIVE` rows
    # whose windows do not overlap — a renewal starting the day the previous grant ends is exactly
    # that case, and it is legal. The row that decides is therefore the one whose window contains the
    # service date, not simply the first `ACTIVE` row found.
    covering = [
        row
        for row in same_grain
        if within_validity_window(
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            date_of_service=date_of_service,
        )
    ]
    live = [row for row in covering if row.state == "ACTIVE"]
    if live:
        return _Decision(reason=None, row=live[0])
    if covering:
        # A row covers the date and is not live. Its state is the reason, and the row is the one to
        # show: `REVOKED`, `SUPERSEDED`, `REJECTED`, `PENDING` and a stale `EXPIRED` each have their
        # own code in the matrix. `rows` arrives newest first, so the most recent covering row is
        # taken when a grain holds more than one.
        row = covering[0]
        return _Decision(reason=_STATE_REASONS[row.state], row=row)

    active = [row for row in same_grain if row.state == "ACTIVE"]
    if active:
        # Nothing covers the date. The reason is taken from the window that explains it: an elapsed
        # grant says `EXPIRED`, one that has not started says `NOT_YET_EFFECTIVE`. Both are decided
        # against `date_of_service` and neither is decided against "now".
        elapsed = [row for row in active if date_of_service >= row.valid_to]
        upcoming = [row for row in active if date_of_service < row.valid_from]
        row = (elapsed or upcoming or active)[0]
        if date_of_service < row.valid_from:
            return _Decision(reason=MatchReason.NOT_YET_EFFECTIVE, row=row)
        return _Decision(reason=MatchReason.EXPIRED, row=row)

    # No live row at this grain: the state of the most recent one is the reason.
    row = same_grain[0]
    return _Decision(reason=_STATE_REASONS[row.state], row=row)
