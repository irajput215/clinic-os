"""Patients service facade — the only place `patients` is queried.

Design: `docs/features/05-patients/03-design.md`, "Deny-by-default request path".
Environment: `docs/reference/database-conventions.md` ("Modules per domain") — a module owns
its tables and is reached only through its service facade.

Rules this module holds to:

- **Every query runs inside `app.core.db.tenant_transaction(...)`**, which sets
  `app.tenant_id` with `SET LOCAL` for the life of the transaction and refuses to open
  without a tenant. That is what activates the forced row-level security policy the
  migration creates.
- **Every query also carries `tenant_id = :tenant_id`.** That predicate is a second line of
  defence, not the isolation boundary: RLS is the boundary (INV-1, design "RLS"). The
  predicate is present because the deployment credential is currently the table owner (and
  a `BYPASSRLS` role), which bypasses the policy — recorded in `docs/progress.md` §4 and in
  the migration's docstring, and closed by task T1-11 (the database role split). Neither
  control is removed on the day the other starts working.
- **A missing tenant never reaches this module.** `tenant_transaction` raises before a
  transaction opens; the router turns that case into a denial first.
- **Nothing returns a raw ORM entity.** Rows are converted to `PatientRead` *inside* the
  transaction, before the session closes and expires its attributes, so a later attribute
  access cannot lazily re-query outside the tenant-scoped transaction.
- **A create and an update are audited on the same transaction (INV-4).** The event is written by
  `app.modules.audit.service` before the transaction commits, so a change that cannot be audited does
  not happen, and a rollback leaves neither the patient row nor the audit row. The payload carries
  field **names**, never values.

Treating `deleted_at` as "not readable": a soft-deleted record is excluded from read, list
and update. Nothing in this slice can set `deleted_at`, so the filter is currently
defensive; the retention and erasure schedule that decides *when* a record is soft-deleted
is open (feature 14, `docs/reference/open-questions.md`).

## Deferred, deliberately — not implemented in this slice

| Item | Why it is deferred |
|---|---|
| Merge and merge/reverse (`POST /patients/{id}/merge`, `.../merge/reverse`) | Reversal rules and step-up are unbuilt, and the merge endpoints sit behind `patient:merge`, which is not in the fixed permission list (`03-design.md`, open items) |
| Duplicate detection (`GET /patients/{id}/duplicates`) | Requires an exact two-identifier match, so it needs the same unbuilt blind-index key handling |
| Export | Requires step-up, a typed reason and a permission the app cannot yet check |
| Treating-relationship rule | `care_relationships` has no ERD table definition and no named owner — a blocked dependency (`03-design.md`, open items; `01-requirements.md` OPEN-4) |
| Permission / RBAC layer | Feature 03 (authentication and RBAC) is not started; the app has `is_superuser` and ordinary authenticated users only, so there is no central policy layer to call |
| Single-record read audit (`patient.read` on `GET /patients/{id}`) | The design attaches `care_relationship_id` and `purpose` to a direct read, and the treating-relationship call site that supplies them is not wired yet (T1-34). The list and search reads *are* audited (below) |
| Identifier search (Medicare, IHI) | Exact match on the keyed blind index only (R8), and no identifier is stored yet: the blind-index key has no custodian (`04-database-erd.md` open item 5) |
| Identifier validation algorithms | The Medicare check digit, IRN rule and IHI format are unspecified in the source (`01-requirements.md` OPEN-1, requires legal/regulatory validation) |
| Field-level encryption and blind-index key handling | Key custody and rotation are OPEN (`03-design.md`, open items), so no identifier is accepted or stored by this slice |
| Soft-delete and retention scheduling | A privacy decision, not an engineering one (feature 14; `database-conventions.md`, "Reconciled with the rest of this document set") |
| Identifier masking on output | Not applicable while no identifier is exposed; R9's mask applies when one is added |
| `Idempotency-Key`, the search rate-limit value | `Idempotency-Key` is a cross-cutting standard with no implementation in the app yet; the search limit's value is open (`04-threat-model.md`, "Rate-limit values for the search and duplicate-candidate routes"), so the router applies an interim value and says so |

## List and search (`docs2/sdlc/02-patients/api.md`, agreed 2026-10-07)

- **Keyset, never `OFFSET`**, on `(family_name, given_name, id)`: a patient registered while a
  clinician pages cannot make the next page skip or repeat a row, and `id` makes the order total.
- **The cursor names a row, not a value.** It is the boundary row's internal id, signed with an HMAC
  over the tenant, the request's scope (the list, or one normalised search) and the id, so it cannot be
  forged, replayed in another tenant (`definition-of-done.md` §4) or reused under a different search.
  The boundary's names are re-read from the row under the tenant's transaction, so no name ever
  travels in the cursor - which matters because the list's cursor is a URL query parameter.
- **Search is a body, not a URL** (R12). Each word must match: a date (`1980-03-14` or `14/03/1980`)
  matches the date of birth exactly; `PT-` and hex digits match the on-screen reference (the id's
  prefix); anything else is a case-insensitive *prefix* of the family, given or preferred name - the
  plaintext search keys of `03-design.md`. `%`, `_` and `\\` are escaped before binding (T-05.2).
- **Every list and search read is audited as `patient.read`** on the transaction that served it, with
  `result_count` and, for a search, the *kinds* of term used (`query_filters`) - never the term.
  Refusals (permission, malformed cursor) are audited `DENIED` with the same fidelity (R13).
"""

import base64
import hashlib
import hmac
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from sqlalchemy import ColumnElement, literal, or_, tuple_
from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.core.db import tenant_transaction
from app.core.reads import Pending, ReadBatch

# The audit module is reached through its service facade (`docs/reference/build-contract.md` §7).
# The import is one-way — `audit` knows nothing about `patients` — so there is no cycle.
from app.modules.audit import service as audit
from app.modules.patients.models import Patient
from app.modules.patients.schemas import (
    PatientCreate,
    PatientRead,
    PatientsPublic,
    PatientUpdate,
)

# The two actions this module emits, named as doc 07 §1 names them — the closed catalogue
# `docs/features/04-audit-log/05-data-and-audit.md` makes normative. `05-patients/05-data-and-audit.md`
# writes `patient.created`/`patient.updated` in its own table and then says, in the same section,
# *"Action names use doc 07's lowercase dotted form"* — under which its two rows are the misspelling.
# The catalogue wins; the divergence is recorded in the PR.
PATIENT_CREATE: str = "patient.create"
PATIENT_UPDATE: str = "patient.update"
PATIENT_READ: str = "patient.read"

# The audit `reason` code for a refused cursor.
INVALID_CURSOR: Final[str] = "INVALID_CURSOR"


def _field_names(patient_in: PatientCreate | PatientUpdate) -> list[str]:
    """The names of the fields the client sent — never their values.

    `05-patients/05-data-and-audit.md` asks for `field_set` on create and `changed_fields` on update,
    both *"names only"*: the trail records **that** a name changed, which is what an access-accounting
    question needs, and never the name itself (INV-5, R11). Sorting makes the value stable, so two
    requests that set the same fields produce the same payload.
    """
    return sorted(set(patient_in.model_fields_set))


def _live_patient(
    session: Session, *, tenant_id: uuid.UUID, patient_id: uuid.UUID
) -> Patient | None:
    """Load one live patient for this tenant, or `None`.

    `None` is the only not-found answer: the caller cannot tell "another tenant's record"
    from "no such record", so the router can answer `404` for both (R6).
    """
    statement = select(Patient).where(
        Patient.id == patient_id,
        # Defence in depth. The RLS policy is the isolation boundary; this predicate keeps
        # the query scoped for the connection role that currently bypasses the policy.
        Patient.tenant_id == tenant_id,
        col(Patient.deleted_at).is_(None),
    )
    return session.exec(statement).first()


def create_patient(
    *,
    tenant_id: uuid.UUID,
    patient_in: PatientCreate,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> PatientRead:
    """Insert one patient for the resolved tenant, and audit the create on the same transaction.

    The tenant is bound from the argument, never from the request body, so a caller cannot
    place a row in another tenant even if a future schema error let a `tenant_id` through.
    The RLS `WITH CHECK` clause refuses the insert independently.

    **The audit event is written on this transaction (INV-4).** A create that cannot be audited does
    not happen: `record` runs before the `with` block commits, and a refusal propagates out of it,
    rolling the patient row back with the audit row.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        patient = Patient(tenant_id=tenant_id, **patient_in.model_dump())
        session.add(patient)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_CREATE,
                result="SUCCESS",
                resource_id=patient.id,
                payload={"field_set": _field_names(patient_in)},
            ),
        )
        session.refresh(patient)
        return PatientRead.model_validate(patient)


@dataclass(frozen=True)
class ReadContext:
    """Who is reading, as the session resolved it. The audit envelope carries these."""

    actor_id: uuid.UUID
    actor_role: str | None = None
    source_ip: str | None = None


class InvalidCursor(ValueError):
    """The cursor is malformed, not signed by this application, or issued for another request.

    The message is a constant: it never echoes the cursor, and a search cursor's scope is the search
    term. The router answers `422 INVALID_CURSOR`.
    """


# ---------------------------------------------------------------------------------------------
# Search terms
# ---------------------------------------------------------------------------------------------

# The kinds of term, which are also the `query_filters` values the audit event records.
NAME_PREFIX: Final[str] = "name_prefix"
DATE_OF_BIRTH: Final[str] = "date_of_birth"
REFERENCE: Final[str] = "reference"

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_AU_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
# The on-screen reference is `PT-` and the first six hex digits of the id (`frontend/src/lib/format.ts`
# `patientRef`). Four to 32 digits are accepted, so a longer prefix narrows further.
_REFERENCE = re.compile(r"^pt-?([0-9a-f]{4,32})$")
_UUID_HEX_DIGITS = 32


@dataclass(frozen=True)
class SearchTerm:
    """One word of a search: its kind and the value it is compared with."""

    kind: str
    value: str | date | tuple[uuid.UUID, uuid.UUID]


def _as_date(word: str) -> date | None:
    """`1980-03-14` or `14/03/1980` (the Australian order), or `None`."""
    if match := _ISO_DATE.match(word):
        year, month, day = match.groups()
    elif match := _AU_DATE.match(word):
        day, month, year = match.groups()
    else:
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _escape_like(value: str) -> str:
    """Escape `LIKE`'s wildcards so a `%` or `_` in a name matches itself (T-05.2).

    PostgreSQL's default `LIKE` escape character is the backslash, so the pattern needs no `ESCAPE`
    clause - which also keeps it a plain constant the planner can turn into an index range.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_search(q: str) -> list[SearchTerm]:
    """Split a search into terms. Every term must match for a patient to be returned."""
    terms: list[SearchTerm] = []
    for word in q.lower().split():
        if (born := _as_date(word)) is not None:
            terms.append(SearchTerm(kind=DATE_OF_BIRTH, value=born))
        elif match := _REFERENCE.match(word):
            digits = match.group(1)
            padding = _UUID_HEX_DIGITS - len(digits)
            terms.append(
                SearchTerm(
                    kind=REFERENCE,
                    value=(
                        uuid.UUID(hex=digits + "0" * padding),
                        uuid.UUID(hex=digits + "f" * padding),
                    ),
                )
            )
        else:
            terms.append(SearchTerm(kind=NAME_PREFIX, value=_escape_like(word) + "%"))
    return terms


def _term_condition(term: SearchTerm) -> ColumnElement[bool]:
    """The SQL predicate for one term. Each one is served by an index (see the migration)."""
    if isinstance(term.value, date):
        return col(Patient.date_of_birth) == term.value
    if isinstance(term.value, tuple):
        low, high = term.value
        return col(Patient.id).between(low, high)
    pattern = term.value
    return or_(
        func.lower(col(Patient.family_name)).like(pattern),
        func.lower(col(Patient.given_name)).like(pattern),
        func.lower(col(Patient.preferred_name)).like(pattern),
    )


def _search_scope(q: str) -> str:
    """The cursor scope for one search: its words, lower-cased and single-spaced."""
    return "search:" + " ".join(q.lower().split())


_LIST_SCOPE: Final[str] = "list"


# ---------------------------------------------------------------------------------------------
# The keyset cursor
# ---------------------------------------------------------------------------------------------

_CURSOR_CONTEXT: Final[bytes] = b"clinos.patients.cursor.v1"
_UUID_BYTES = 16


def _cursor_signature(*, tenant_id: uuid.UUID, scope: str, payload: bytes) -> str:
    """An HMAC binding the boundary row to the tenant and to the request that paged it."""
    message = b"\0".join(
        (_CURSOR_CONTEXT, tenant_id.bytes, scope.encode("utf-8"), payload)
    )
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), message, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest[:16]).decode("ascii").rstrip("=")


def encode_cursor(*, tenant_id: uuid.UUID, scope: str, patient_id: uuid.UUID) -> str:
    """The opaque cursor that continues after `patient_id` in this tenant and scope."""
    payload = patient_id.bytes
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = _cursor_signature(tenant_id=tenant_id, scope=scope, payload=payload)
    return f"{body}.{signature}"


def decode_cursor(cursor: str, *, tenant_id: uuid.UUID, scope: str) -> uuid.UUID:
    """The boundary row a cursor names, or `InvalidCursor`. Fails closed on every malformed input."""
    try:
        body, signature = cursor.split(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except ValueError as error:
        raise InvalidCursor("the cursor is not one this API issued") from error
    expected = _cursor_signature(tenant_id=tenant_id, scope=scope, payload=payload)
    if len(payload) != _UUID_BYTES or not hmac.compare_digest(signature, expected):
        raise InvalidCursor("the cursor is not one this API issued")
    return uuid.UUID(bytes=payload)


# ---------------------------------------------------------------------------------------------
# List and search
# ---------------------------------------------------------------------------------------------


def _page(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    scope: str,
    conditions: Sequence[ColumnElement[bool]],
    limit: int,
    boundary_id: uuid.UUID | None,
) -> PatientsPublic | None:
    """One keyset page on the caller's transaction, or `None` if the boundary row is not visible."""
    live = [
        # Defence in depth beside RLS, exactly as `_live_patient`.
        col(Patient.tenant_id) == tenant_id,
        col(Patient.deleted_at).is_(None),
        *conditions,
    ]
    after: list[ColumnElement[bool]] = []
    if boundary_id is not None:
        # The boundary's sort key is read from the row, so the cursor carries no name. A soft-deleted
        # boundary still positions the page; a row this tenant cannot see does not.
        boundary = session.exec(
            select(Patient.family_name, Patient.given_name).where(
                col(Patient.id) == boundary_id, col(Patient.tenant_id) == tenant_id
            )
        ).first()
        if boundary is None:
            return None
        family_name, given_name = boundary
        after.append(
            tuple_(col(Patient.family_name), col(Patient.given_name), col(Patient.id))
            > tuple_(literal(family_name), literal(given_name), literal(boundary_id))
        )

    # The page and the total in one statement: every row carries the total as a scalar subquery
    # (`docs/reference/performance.md`). Only an empty page after a cursor, which has no row to carry
    # it, counts on its own; an empty first page means nothing matches at all.
    counted = select(func.count()).select_from(Patient).where(*live)
    rows = session.exec(
        select(Patient, counted.scalar_subquery())
        .where(*live, *after)
        .order_by(col(Patient.family_name), col(Patient.given_name), col(Patient.id))
        .limit(limit + 1)
    ).all()
    if rows:
        count = rows[0][1]
    elif boundary_id is None:
        count = 0
    else:
        count = session.exec(counted).one()
    page, overflow = [patient for patient, _ in rows[:limit]], rows[limit:]
    return PatientsPublic(
        data=[PatientRead.model_validate(patient) for patient in page],
        count=count,
        next_cursor=(
            encode_cursor(tenant_id=tenant_id, scope=scope, patient_id=page[-1].id)
            if overflow
            else None
        ),
    )


def _read(
    *,
    tenant_id: uuid.UUID,
    context: ReadContext,
    scope: str,
    conditions: Sequence[ColumnElement[bool]],
    limit: int,
    cursor: str | None,
    query_filters: list[str] | None,
) -> PatientsPublic:
    """Serve one list or search page and audit it on the same transaction (INV-4).

    A cursor that does not verify, or names a row this tenant cannot see, is audited `DENIED` with
    the same envelope as a success (R13), committed, and then refused with `InvalidCursor`.
    """
    payload: dict[str, object] = {}
    if query_filters is not None:
        payload["query_filters"] = query_filters
    result: PatientsPublic | None = None
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        source_ip=context.source_ip,
    ) as session:
        try:
            boundary_id = (
                None
                if cursor is None
                else decode_cursor(cursor, tenant_id=tenant_id, scope=scope)
            )
        except InvalidCursor:
            pass
        else:
            result = _page(
                session,
                tenant_id=tenant_id,
                scope=scope,
                conditions=conditions,
                limit=limit,
                boundary_id=boundary_id,
            )
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_READ,
                result="DENIED" if result is None else "SUCCESS",
                reason=INVALID_CURSOR if result is None else None,
                source_ip=context.source_ip,
                payload=(
                    (payload or None)
                    if result is None
                    else {**payload, "result_count": len(result.data)}
                ),
            ),
        )
    if result is None:
        raise InvalidCursor("the cursor is not one this API issued")
    return result


def list_patients(
    *,
    tenant_id: uuid.UUID,
    context: ReadContext,
    limit: int,
    cursor: str | None = None,
) -> PatientsPublic:
    """One keyset page of the caller's live patients, by family name, given name, id. Audited."""
    return _read(
        tenant_id=tenant_id,
        context=context,
        scope=_LIST_SCOPE,
        conditions=(),
        limit=limit,
        cursor=cursor,
        query_filters=None,
    )


def search_patients(
    *,
    tenant_id: uuid.UUID,
    context: ReadContext,
    q: str,
    limit: int,
    cursor: str | None = None,
) -> PatientsPublic:
    """One keyset page of the caller's live patients matching every term of `q`. Audited.

    The audit payload records which kinds of term were used, sorted and de-duplicated, and never the
    term (US-7). Nothing here logs `q`.
    """
    terms = parse_search(q)
    return _read(
        tenant_id=tenant_id,
        context=context,
        scope=_search_scope(q),
        conditions=[_term_condition(term) for term in terms],
        limit=limit,
        cursor=cursor,
        query_filters=sorted({term.kind for term in terms}),
    )


def record_read_denial(
    *, tenant_id: uuid.UUID, context: ReadContext, reason: str
) -> None:
    """Audit a list or search the policy layer refused, before any patient row is read (R13)."""
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        source_ip=context.source_ip,
    ) as session:
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_READ,
                result="DENIED",
                reason=reason,
                source_ip=context.source_ip,
            ),
        )


def get_patient(*, tenant_id: uuid.UUID, patient_id: uuid.UUID) -> PatientRead | None:
    """One live patient for this tenant, or `None`."""
    with tenant_transaction(tenant_id=tenant_id) as session:
        patient = _live_patient(session, tenant_id=tenant_id, patient_id=patient_id)
        if patient is None:
            return None
        return PatientRead.model_validate(patient)


def update_patient(
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    patient_in: PatientUpdate,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> PatientRead | None:
    """Apply a partial update to one live patient for this tenant, or `None`.

    Only the fields the client sent are touched (`exclude_unset`), so an omitted field is
    never overwritten with a default and a `PATCH` cannot clear a NOT NULL column.

    **The audit event is written on this transaction (INV-4)**, and it carries the *names* of the
    fields the client sent — never their values. A `None` answer (absent, or another tenant's record)
    writes nothing: no row was touched, so there is no change to account for, and the router's `404`
    discloses nothing.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        patient = _live_patient(session, tenant_id=tenant_id, patient_id=patient_id)
        if patient is None:
            return None
        patient.sqlmodel_update(patient_in.model_dump(exclude_unset=True))
        session.add(patient)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_UPDATE,
                result="SUCCESS",
                resource_id=patient.id,
                payload={"changed_fields": _field_names(patient_in)},
            ),
        )
        session.refresh(patient)
        return PatientRead.model_validate(patient)


def display_names(
    session: Session, *, tenant_id: uuid.UUID, patient_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """`{id: "Preferred-or-given Family"}` for the **live** patients among `patient_ids`.

    Runs on the caller's tenant transaction (the appointments module names the patient on each
    booking it returns). An id that is absent, soft-deleted or another tenant's is simply missing from
    the answer, so a caller cannot tell those apart.
    """
    if not patient_ids:
        return {}
    rows: Sequence[Patient] = session.exec(
        select(Patient).where(
            Patient.tenant_id == tenant_id,
            col(Patient.id).in_(list(set(patient_ids))),
            col(Patient.deleted_at).is_(None),
        )
    ).all()
    return {
        patient.id: f"{patient.preferred_name or patient.given_name} {patient.family_name}"
        for patient in rows
    }


def queue_display_names(
    batch: ReadBatch, *, tenant_id: uuid.UUID, patient_ids: Sequence[uuid.UUID]
) -> Pending[dict[uuid.UUID, str]]:
    """`display_names`, queued on the caller's batch so it travels with the caller's other reads.

    Same answer, same transaction (`app.core.reads`): an id that is absent, soft-deleted or another
    tenant's is simply missing. No ids, no statement.
    """
    wanted = sorted(set(patient_ids))
    if not wanted:
        return Pending.ready({})
    rows = batch.rows(
        select(
            col(Patient.id),
            col(Patient.given_name),
            col(Patient.preferred_name),
            col(Patient.family_name),
        ).where(
            col(Patient.tenant_id) == tenant_id,
            col(Patient.id).in_(wanted),
            col(Patient.deleted_at).is_(None),
        )
    )
    return rows.then(
        lambda found: {
            patient_id: f"{preferred or given} {family}"
            for patient_id, given, preferred, family in found
        }
    )


def match_or_create_for_booking(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    given_name: str,
    family_name: str,
    date_of_birth: date,
    email: str,
    phone: str,
    source_ip: str | None = None,
) -> uuid.UUID:
    """The patient a public booking is for: an exact existing match, or a new record.

    Runs on the caller's tenant transaction, so the patient, the booking and both audit events commit
    or roll back together. A match needs **all four** of given name, family name, date of birth and
    email to agree (case-insensitively for the text), so a booking never attaches itself to somebody
    else's record on a shared email or a common name. A matched record is never changed: an anonymous
    form is not a source of truth for an existing patient's details. The caller answers the same way
    in both cases, so the response cannot be used to learn whether a person is a patient here.

    A new record is audited as `patient.create` with its field names only, exactly as a staff create
    is (INV-4); the envelope carries no actor, because nobody signed in.
    """
    existing = session.exec(
        select(Patient.id).where(
            Patient.tenant_id == tenant_id,
            col(Patient.deleted_at).is_(None),
            func.lower(col(Patient.given_name)) == given_name.lower(),
            func.lower(col(Patient.family_name)) == family_name.lower(),
            Patient.date_of_birth == date_of_birth,
            func.lower(col(Patient.email)) == email.lower(),
        )
    ).first()
    if existing is not None:
        return existing
    patient = Patient(
        tenant_id=tenant_id,
        given_name=given_name,
        family_name=family_name,
        date_of_birth=date_of_birth,
        email=email,
        phone=phone,
    )
    session.add(patient)
    session.flush()
    audit.record(
        session,
        audit.AuditEvent(
            action=PATIENT_CREATE,
            result="SUCCESS",
            resource_id=patient.id,
            source_ip=source_ip,
            payload={
                "field_set": [
                    "date_of_birth",
                    "email",
                    "family_name",
                    "given_name",
                    "phone",
                ]
            },
        ),
    )
    return patient.id
