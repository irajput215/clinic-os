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
| Permission / RBAC layer | Feature 03 (authentication and RBAC) is not started; the app has `is_superuser` and ordinary authenticated users only, so there is no central policy layer to call |
| Identifier search (Medicare, IHI) | Exact match on the keyed blind index only (R8), and no identifier is stored yet: the blind-index key has no custodian (`04-database-erd.md` open item 5) |
| Identifier validation algorithms | The Medicare check digit, IRN rule and IHI format are unspecified in the source (`01-requirements.md` OPEN-1, requires legal/regulatory validation) |
| Field-level encryption and blind-index key handling | Key custody and rotation are OPEN (`03-design.md`, open items), so no identifier is accepted or stored by this slice |
| Soft-delete and retention scheduling | A privacy decision, not an engineering one (feature 14; `database-conventions.md`, "Reconciled with the rest of this document set") |
| Identifier masking on output | Not applicable while no identifier is exposed; R9's mask applies when one is added |
| `Idempotency-Key`, the search rate-limit value | `Idempotency-Key` is a cross-cutting standard with no implementation in the app yet; the search limit's value is open (`04-threat-model.md`, "Rate-limit values for the search and duplicate-candidate routes"), so the router applies an interim value and says so |

## The treating-relationship rule (T1-34, decision D-007)

`patient:read` and `patient:update` held only through a relationship-bound grant (a `DOCTOR` or
`NURSE`, the matrix's `cr`) reach a patient only through an active care relationship
(`03-design.md`, "Treating-relationship rule"). The relationship is resolved **in the statement that
loads the patient** (`care_relationships.service.relationship_id`), so it costs no round trip, runs
under the same transaction, tenant context and RLS policy as the read, and is never widened to the
tenant. Across a tenant boundary the answer stays `404` (the row is never found); inside the tenant
without a relationship it is `403 AUTHZ_CARE_RELATIONSHIP_DENIED`. Every direct read writes
`patient.read` with the relationship id and the purpose, and every refusal is audited `DENIED`. For a
relationship-bound reader the list and the search are filtered to the patients they have an active
relationship with (`03-design.md`, "Endpoints": "treating-relationship filtered"), and so is the total.

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
from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy import ColumnElement, literal, or_, tuple_
from sqlmodel import Session, col, func, select

from app.core import field_crypto
from app.core.config import settings
from app.core.db import tenant_transaction
from app.core.reads import Pending, ReadBatch

# The audit module is reached through its service facade (`docs/reference/build-contract.md` §7).
# The import is one-way — `audit` knows nothing about `patients` — so there is no cycle.
from app.modules.audit import service as audit
from app.modules.care_relationships import service as care
from app.modules.patients.models import (
    DEFAULT_TIMEZONE,
    INACTIVE_STATUSES,
    PATIENT_STATUSES,
    STATUSES_NEEDING_A_REASON,
    Patient,
    PatientAlert,
    PatientEmergencyContact,
)
from app.modules.patients.schemas import (
    AlertCreate,
    AlertRead,
    EmergencyContactCreate,
    EmergencyContactRead,
    EScriptReadiness,
    PatientCreate,
    PatientRead,
    PatientsPublic,
    PatientStatusChange,
    PatientUpdate,
)
from app.modules.users_roles.policy import Actor, Decision

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
# The audit `reason` for a direct read or update of a patient that is not the caller's own (absent, or
# another tenant's): the clinical-records trail's code for the same case.
NOT_FOUND: Final[str] = "AUTHZ_DENIED_CROSS_TENANT"

# The permissions the rule is evaluated for. Named here as well as in the catalogue so this module does
# not import the users-and-roles catalogue for two strings.
_READ: Final[str] = "patient:read"
_UPDATE: Final[str] = "patient:update"


def _field_names(patient_in: PatientCreate | PatientUpdate) -> list[str]:
    """The names of the fields the client sent — never their values.

    `05-patients/05-data-and-audit.md` asks for `field_set` on create and `changed_fields` on update,
    both *"names only"*: the trail records **that** a name changed, which is what an access-accounting
    question needs, and never the name itself (INV-5, R11). Sorting makes the value stable, so two
    requests that set the same fields produce the same payload.
    """
    return sorted(set(patient_in.model_fields_set))


# The identifier columns, by the name the API uses, and the `kind` the crypto binds them to.
_IDENTIFIERS: Final[dict[str, tuple[str, str]]] = {
    "medicare_number": ("medicare_number", "medicare_blind_index"),
    "ihi": ("ihi", "ihi_blind_index"),
}


def _set_identifiers(
    patient: Patient, values: dict[str, object], *, tenant_id: uuid.UUID
) -> None:
    """Encrypt and index each identifier in `values` onto `patient`; an explicit `None` clears it.

    The plaintext never reaches the row, a log or the audit payload (R8, INV-5).
    """
    for name, (column, index_column) in _IDENTIFIERS.items():
        if name not in values:
            continue
        value = values.pop(name)
        if value is None:
            setattr(patient, column, None)
            setattr(patient, index_column, None)
            continue
        assert isinstance(value, str)
        setattr(
            patient,
            column,
            field_crypto.encrypt(value, tenant_id=tenant_id, kind=name),
        )
        setattr(
            patient,
            index_column,
            field_crypto.blind_index(value, tenant_id=tenant_id, kind=name),
        )


def escript_readiness(patient: Patient) -> EScriptReadiness:
    """Manual §3.4: an eScript needs a verified IHI, the sex HI matching uses, and a full address."""
    missing: list[str] = []
    if not patient.ihi:
        missing.append("IHI")
    if patient.sex_at_birth in (None, "UNKNOWN"):
        missing.append("SEX")
    if not all((patient.address_line, patient.suburb, patient.state, patient.postcode)):
        missing.append("ADDRESS")
    return EScriptReadiness(ready=not missing, missing=missing)


def to_read(patient: Patient) -> PatientRead:
    """The patient as the API answers it: identifiers masked, readiness computed."""
    return PatientRead(
        id=patient.id,
        given_name=patient.given_name,
        family_name=patient.family_name,
        preferred_name=patient.preferred_name,
        date_of_birth=patient.date_of_birth,
        sex_at_birth=patient.sex_at_birth,
        gender_identity=patient.gender_identity,
        address_line=patient.address_line,
        suburb=patient.suburb,
        state=patient.state,
        postcode=patient.postcode,
        phone=patient.phone,
        email=patient.email,
        deceased_at=patient.deceased_at,
        status=patient.status,
        status_reason=patient.status_reason,
        medicare_masked=field_crypto.mask(
            field_crypto.decrypt(
                patient.medicare_number,
                tenant_id=patient.tenant_id,
                kind="medicare_number",
            )
        ),
        medicare_irn=patient.medicare_irn,
        ihi_masked=field_crypto.mask(
            field_crypto.decrypt(patient.ihi, tenant_id=patient.tenant_id, kind="ihi")
        ),
        receives_communications=patient.receives_communications,
        timezone=patient.timezone,
        preferred_pharmacy_id=patient.preferred_pharmacy_id,
        escript_ready=escript_readiness(patient),
        created_at=patient.created_at,
        updated_at=patient.updated_at,
    )


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
        values = patient_in.model_dump()
        values["timezone"] = values.get("timezone") or DEFAULT_TIMEZONE
        identifiers = {name: values.pop(name) for name in _IDENTIFIERS}
        patient = Patient(tenant_id=tenant_id, **values)
        _set_identifiers(patient, identifiers, tenant_id=tenant_id)
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
        return to_read(patient)


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
MEDICARE: Final[str] = "medicare_number"
IHI: Final[str] = "ihi"
_MEDICARE_WORD = re.compile(r"^\d{10}$")
_IHI_WORD = re.compile(r"^800360\d{10}$")

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
        elif _MEDICARE_WORD.match(word):
            # Exact match through the blind index: the number is never compared in plaintext.
            terms.append(SearchTerm(kind=MEDICARE, value=word))
        elif _IHI_WORD.match(word):
            terms.append(SearchTerm(kind=IHI, value=word))
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


def _term_condition(term: SearchTerm, *, tenant_id: uuid.UUID) -> ColumnElement[bool]:
    """The SQL predicate for one term. Each one is served by an index (see the migration)."""
    if term.kind in (MEDICARE, IHI):
        assert isinstance(term.value, str)
        index = field_crypto.blind_index(
            term.value, tenant_id=tenant_id, kind=term.kind
        )
        column = (
            Patient.medicare_blind_index
            if term.kind == MEDICARE
            else Patient.ihi_blind_index
        )
        return col(column) == index
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
        data=[to_read(patient) for patient in page],
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
    care_scope: uuid.UUID | None,
) -> PatientsPublic:
    """Serve one list or search page and audit it on the same transaction (INV-4).

    `care_scope` is the relationship-bound reader's own id: the page and its total are then the
    patients that reader has an active care relationship with, and the purpose is `TREATMENT`.

    A cursor that does not verify, or names a row this tenant cannot see, is audited `DENIED` with
    the same envelope as a success (R13), committed, and then refused with `InvalidCursor`.
    """
    payload: dict[str, object] = {
        "purpose": care.PRACTICE_ADMINISTRATION
        if care_scope is None
        else care.TREATMENT
    }
    if query_filters is not None:
        payload["query_filters"] = query_filters
    if care_scope is not None:
        conditions = [
            *conditions,
            col(Patient.id).in_(
                care.related_patient_ids(
                    tenant_id=tenant_id, practitioner_id=care_scope
                )
            ),
        ]
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
    care_scope: uuid.UUID | None = None,
    statuses: Sequence[str] | None = None,
) -> PatientsPublic:
    """One keyset page of the caller's live patients, by family name, given name, id. Audited.

    Without `statuses` the list holds the active patients: archived, discharged and deceased records
    are kept but leave the list (manual §3.2). Search still finds every status.
    """
    chosen = (
        sorted(set(statuses))
        if statuses
        else [s for s in PATIENT_STATUSES if s not in INACTIVE_STATUSES]
    )
    return _read(
        tenant_id=tenant_id,
        context=context,
        scope=_LIST_SCOPE if not statuses else f"{_LIST_SCOPE}:{','.join(chosen)}",
        conditions=[col(Patient.status).in_(chosen)],
        limit=limit,
        cursor=cursor,
        query_filters=["status"] if statuses else None,
        care_scope=care_scope,
    )


def search_patients(
    *,
    tenant_id: uuid.UUID,
    context: ReadContext,
    q: str,
    limit: int,
    cursor: str | None = None,
    care_scope: uuid.UUID | None = None,
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
        conditions=[_term_condition(term, tenant_id=tenant_id) for term in terms],
        limit=limit,
        cursor=cursor,
        query_filters=sorted({term.kind for term in terms}),
        care_scope=care_scope,
    )


def record_read_denial(
    *,
    tenant_id: uuid.UUID,
    context: ReadContext,
    reason: str,
    action: str = PATIENT_READ,
    resource_id: uuid.UUID | None = None,
) -> None:
    """Audit a request the policy layer refused, before any patient row is read (R13)."""
    with tenant_transaction(
        tenant_id=tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        source_ip=context.source_ip,
    ) as session:
        audit.record(
            session,
            audit.AuditEvent(
                action=action,
                result="DENIED",
                resource_id=resource_id,
                reason=reason,
                source_ip=context.source_ip,
            ),
        )


@dataclass(frozen=True)
class PatientRefusal:
    """A decided, already-audited refusal of a direct read or update. The router raises it."""

    status_code: int
    decision: Decision | None = None


def _patient_and_relationship(
    session: Session, *, actor: Actor, patient_id: uuid.UUID, lock: bool = False
) -> tuple[Patient, uuid.UUID | None] | None:
    """One live patient of the actor's tenant and the actor's active relationship with it, in one
    statement; `None` for absent and another tenant's alike (R6)."""
    statement = select(
        Patient, care.actor_relationship_id(actor, col(Patient.id))
    ).where(
        Patient.id == patient_id,
        # Defence in depth beside RLS, exactly as `_live_patient`.
        Patient.tenant_id == actor.tenant_id,
        col(Patient.deleted_at).is_(None),
    )
    if lock:
        statement = statement.with_for_update(of=Patient)
    row = session.exec(statement).first()
    return None if row is None else (row[0], row[1])


def read_patient(
    *, actor: Actor, patient_id: uuid.UUID, context: ReadContext
) -> PatientRead | PatientRefusal:
    """Read one patient under the treating-relationship rule, auditing the read (T1-34, R7, R13).

    One flight loads the patient and the relationship; the decision follows; the event is written on
    the same transaction: `SUCCESS` with `care_relationship_id` and `purpose`, or `DENIED` with the
    reason. `404` for a patient that is not the caller's own, `403 AUTHZ_CARE_RELATIONSHIP_DENIED` for
    one of the caller's own without the relationship a bound grant needs.
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        source_ip=context.source_ip,
    ) as session:
        found = _patient_and_relationship(session, actor=actor, patient_id=patient_id)
        if found is None:
            audit.record(
                session,
                audit.AuditEvent(
                    action=PATIENT_READ,
                    result="DENIED",
                    resource_id=patient_id,
                    reason=NOT_FOUND,
                    source_ip=context.source_ip,
                ),
            )
            return PatientRefusal(status_code=404)
        patient, relationship = found
        access = care.patient_access(
            actor, _READ, patient_id=patient.id, care_relationship_id=relationship
        )
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_READ,
                result="SUCCESS" if access.allowed else "DENIED",
                resource_id=patient.id,
                reason=None if access.allowed else access.reason,
                source_ip=context.source_ip,
                payload=access.audit_payload() if access.allowed else None,
            ),
        )
        if not access.allowed:
            return PatientRefusal(
                status_code=access.decision.status_code, decision=access.decision
            )
        return to_read(patient)


@dataclass(frozen=True)
class PatientAccessResult:
    """A patient of the caller's tenant (or `None`) and the actor's access to it, for a module that
    acts on a patient through this facade (staging a script, writing a consult note)."""

    patient: PatientRead | None
    access: care.PatientAccess | None


def patient_access(
    *, actor: Actor, patient_id: uuid.UUID, permission: str = _READ
) -> PatientAccessResult:
    """Resolve one patient and the actor's access to it in one statement, without auditing.

    The caller audits on its own transaction, with its own action: a refused staging is a
    `prescription.create` refusal, not a patient read.
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id
    ) as session:
        found = _patient_and_relationship(session, actor=actor, patient_id=patient_id)
        if found is None:
            return PatientAccessResult(patient=None, access=None)
        patient, relationship = found
        return PatientAccessResult(
            patient=to_read(patient),
            access=care.patient_access(
                actor,
                permission,
                patient_id=patient.id,
                care_relationship_id=relationship,
            ),
        )


def get_patient(*, tenant_id: uuid.UUID, patient_id: uuid.UUID) -> PatientRead | None:
    """One live patient for this tenant, or `None`."""
    with tenant_transaction(tenant_id=tenant_id) as session:
        patient = _live_patient(session, tenant_id=tenant_id, patient_id=patient_id)
        if patient is None:
            return None
        return to_read(patient)


def _patient_to_change(
    session: Session, *, actor: Actor, patient_id: uuid.UUID
) -> Patient | PatientRefusal:
    """The live patient, locked, if the actor may change it; else an audited refusal.

    A patient that is not the caller's own (absent, or another tenant's) is `404`; one a
    relationship-bound grant cannot reach is the policy's `403` (T1-34). Both are audited
    `patient.update` `DENIED` on this transaction.
    """
    found = _patient_and_relationship(
        session, actor=actor, patient_id=patient_id, lock=True
    )
    access = (
        None
        if found is None
        else care.patient_access(
            actor, _UPDATE, patient_id=patient_id, care_relationship_id=found[1]
        )
    )
    if found is None or access is None or not access.allowed:
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_UPDATE,
                result="DENIED",
                resource_id=patient_id,
                reason=NOT_FOUND if access is None else access.reason,
            ),
        )
        if access is None:
            return PatientRefusal(status_code=404)
        return PatientRefusal(
            status_code=access.decision.status_code, decision=access.decision
        )
    return found[0]


def update_patient(
    *,
    actor: Actor,
    patient_id: uuid.UUID,
    patient_in: PatientUpdate,
) -> PatientRead | PatientRefusal:
    """Apply a partial update to one live patient for this tenant, or `None`.

    Only the fields the client sent are touched (`exclude_unset`), so an omitted field is
    never overwritten with a default and a `PATCH` cannot clear a NOT NULL column.

    **The audit event is written on this transaction (INV-4)**, and it carries the *names* of the
    fields the client sent - never their values. A patient that is not the caller's own (absent, or
    another tenant's) is `404` and audited `DENIED`; one of the caller's own that a relationship-bound
    grant cannot reach is `403 AUTHZ_CARE_RELATIONSHIP_DENIED`, audited the same way, and no row is
    touched in either case (T1-34).
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        patient = _patient_to_change(session, actor=actor, patient_id=patient_id)
        if isinstance(patient, PatientRefusal):
            return patient
        values = patient_in.model_dump(exclude_unset=True)
        _set_identifiers(patient, values, tenant_id=actor.tenant_id)
        patient.sqlmodel_update(values)
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
        return to_read(patient)


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


def contact_emails(
    session: Session, *, tenant_id: uuid.UUID, patient_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """`{id: email}` for the **live** patients among `patient_ids` that have an email address.

    For the booking emails (`app.modules.appointments.notifications`), on the caller's tenant
    transaction. An absent, soft-deleted, other tenant's or address-less patient is simply missing,
    and the caller skips that email. The address is used to send and is never logged.
    """
    if not patient_ids:
        return {}
    rows = session.exec(
        select(col(Patient.id), col(Patient.email)).where(
            Patient.tenant_id == tenant_id,
            col(Patient.id).in_(sorted(set(patient_ids))),
            col(Patient.deleted_at).is_(None),
            col(Patient.email).is_not(None),
        )
    ).all()
    return {patient_id: email for patient_id, email in rows if email}


def opted_out_ids(
    session: Session, *, tenant_id: uuid.UUID, patient_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """The patients among `patient_ids` who opted out of communications (manual §3.4).

    Reminders, recalls and campaigns skip them; transactional messages (a booking confirmation, a
    script notice) still send.
    """
    if not patient_ids:
        return set()
    return set(
        session.exec(
            select(Patient.id).where(
                col(Patient.tenant_id) == tenant_id,
                col(Patient.id).in_(sorted(set(patient_ids))),
                col(Patient.receives_communications).is_(False),
            )
        ).all()
    )


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
    """`match_or_create_patient` for a plain booking: the patient's id only."""
    patient_id, _created = match_or_create_patient(
        session,
        tenant_id=tenant_id,
        given_name=given_name,
        family_name=family_name,
        date_of_birth=date_of_birth,
        email=email,
        phone=phone,
        source_ip=source_ip,
    )
    return patient_id


def match_or_create_patient(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    given_name: str,
    family_name: str,
    date_of_birth: date,
    email: str,
    phone: str,
    source_ip: str | None = None,
    new_status: str = "CURRENT",
) -> tuple[uuid.UUID, bool]:
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
        return existing, False
    patient = Patient(
        tenant_id=tenant_id,
        given_name=given_name,
        family_name=family_name,
        date_of_birth=date_of_birth,
        email=email,
        phone=phone,
        status=new_status,
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
    return patient.id, True


# ---------------------------------------------------------------------------------------------
# Status, alerts and emergency contacts (docs3 feature 04; manual §3.2, §3.4)
# ---------------------------------------------------------------------------------------------


class StatusReasonRequired(ValueError):
    """`BLOCKED`, `ARCHIVED` and `DISCHARGED` record why; `DECEASED` records when."""


def change_status(
    *, actor: Actor, patient_id: uuid.UUID, change: PatientStatusChange
) -> PatientRead | PatientRefusal:
    """Move a patient to another lifecycle status, with its reason, audited on this transaction.

    The audit carries the field names and the new status code - never the free-text reason, which
    can name a person or a condition.
    """
    if change.status in STATUSES_NEEDING_A_REASON and not change.reason:
        raise StatusReasonRequired("a reason is required for this status")
    if change.status == "DECEASED" and change.deceased_at is None:
        raise StatusReasonRequired("the date of death is required")
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        patient = _patient_to_change(session, actor=actor, patient_id=patient_id)
        if isinstance(patient, PatientRefusal):
            return patient
        patient.status = change.status
        patient.status_reason = change.reason
        patient.status_changed_at = datetime.now(UTC)
        if change.status == "DECEASED":
            patient.deceased_at = change.deceased_at
        session.add(patient)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_UPDATE,
                result="SUCCESS",
                resource_id=patient.id,
                reason=f"STATUS_{change.status}",
                payload={"changed_fields": ["status", "status_reason"]},
            ),
        )
        session.refresh(patient)
        return to_read(patient)


def blocked_patient_ids(
    session: Session, *, tenant_id: uuid.UUID, patient_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """The `BLOCKED` patients among `patient_ids`, on the caller's transaction (manual §3.2).

    A blocked patient takes no new booking and no new script until the block is lifted.
    """
    if not patient_ids:
        return set()
    return set(
        session.exec(
            select(Patient.id).where(
                col(Patient.tenant_id) == tenant_id,
                col(Patient.id).in_(list(patient_ids)),
                col(Patient.status) == "BLOCKED",
            )
        ).all()
    )


def _active_alerts(session: Session, *, patient_id: uuid.UUID) -> list[AlertRead]:
    rows = session.exec(
        select(PatientAlert)
        .where(
            col(PatientAlert.patient_id) == patient_id,
            col(PatientAlert.removed_at).is_(None),
        )
        .order_by(col(PatientAlert.created_at))
    ).all()
    return [AlertRead.model_validate(row) for row in rows]


def _active_contacts(
    session: Session, *, patient_id: uuid.UUID
) -> list[EmergencyContactRead]:
    rows = session.exec(
        select(PatientEmergencyContact)
        .where(
            col(PatientEmergencyContact.patient_id) == patient_id,
            col(PatientEmergencyContact.removed_at).is_(None),
        )
        .order_by(col(PatientEmergencyContact.created_at))
    ).all()
    return [EmergencyContactRead.model_validate(row) for row in rows]


def _readable(
    session: Session, *, actor: Actor, patient_id: uuid.UUID
) -> PatientRefusal | None:
    """`None` when the actor may read this patient; else the refusal, audited as a read."""
    found = _patient_and_relationship(session, actor=actor, patient_id=patient_id)
    access = (
        None
        if found is None
        else care.patient_access(
            actor, _READ, patient_id=patient_id, care_relationship_id=found[1]
        )
    )
    if found is None or access is None or not access.allowed:
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_READ,
                result="DENIED",
                resource_id=patient_id,
                reason=NOT_FOUND if access is None else access.reason,
            ),
        )
        if access is None:
            return PatientRefusal(status_code=404)
        return PatientRefusal(
            status_code=access.decision.status_code, decision=access.decision
        )
    return None


def list_alerts(
    *, actor: Actor, patient_id: uuid.UUID
) -> list[AlertRead] | PatientRefusal:
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        refusal = _readable(session, actor=actor, patient_id=patient_id)
        return refusal or _active_alerts(session, patient_id=patient_id)


def add_alert(
    *, actor: Actor, patient_id: uuid.UUID, alert_in: AlertCreate
) -> list[AlertRead] | PatientRefusal:
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        patient = _patient_to_change(session, actor=actor, patient_id=patient_id)
        if isinstance(patient, PatientRefusal):
            return patient
        session.add(
            PatientAlert(
                tenant_id=actor.tenant_id,
                patient_id=patient.id,
                text=alert_in.text,
                tone=alert_in.tone,
                created_by=actor.user_id,
            )
        )
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_UPDATE,
                result="SUCCESS",
                resource_id=patient.id,
                payload={"changed_fields": ["alerts"]},
            ),
        )
        return _active_alerts(session, patient_id=patient.id)


def remove_alert(
    *, actor: Actor, patient_id: uuid.UUID, alert_id: uuid.UUID
) -> list[AlertRead] | PatientRefusal:
    """Hide an alert (`removed_at`); the row and who added and removed it stay."""
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        patient = _patient_to_change(session, actor=actor, patient_id=patient_id)
        if isinstance(patient, PatientRefusal):
            return patient
        alert = session.exec(
            select(PatientAlert).where(
                col(PatientAlert.id) == alert_id,
                col(PatientAlert.patient_id) == patient.id,
                col(PatientAlert.removed_at).is_(None),
            )
        ).first()
        if alert is None:
            return PatientRefusal(status_code=404)
        alert.removed_at = datetime.now(UTC)
        alert.removed_by = actor.user_id
        session.add(alert)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_UPDATE,
                result="SUCCESS",
                resource_id=patient.id,
                payload={"changed_fields": ["alerts"]},
            ),
        )
        return _active_alerts(session, patient_id=patient.id)


def list_emergency_contacts(
    *, actor: Actor, patient_id: uuid.UUID
) -> list[EmergencyContactRead] | PatientRefusal:
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        refusal = _readable(session, actor=actor, patient_id=patient_id)
        return refusal or _active_contacts(session, patient_id=patient_id)


def add_emergency_contact(
    *, actor: Actor, patient_id: uuid.UUID, contact_in: EmergencyContactCreate
) -> list[EmergencyContactRead] | PatientRefusal:
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        patient = _patient_to_change(session, actor=actor, patient_id=patient_id)
        if isinstance(patient, PatientRefusal):
            return patient
        session.add(
            PatientEmergencyContact(
                tenant_id=actor.tenant_id,
                patient_id=patient.id,
                name=contact_in.name,
                relationship=contact_in.relationship,
                phone=contact_in.phone,
                created_by=actor.user_id,
            )
        )
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_UPDATE,
                result="SUCCESS",
                resource_id=patient.id,
                payload={"changed_fields": ["emergency_contacts"]},
            ),
        )
        return _active_contacts(session, patient_id=patient.id)


def remove_emergency_contact(
    *, actor: Actor, patient_id: uuid.UUID, contact_id: uuid.UUID
) -> list[EmergencyContactRead] | PatientRefusal:
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        patient = _patient_to_change(session, actor=actor, patient_id=patient_id)
        if isinstance(patient, PatientRefusal):
            return patient
        contact = session.exec(
            select(PatientEmergencyContact).where(
                col(PatientEmergencyContact.id) == contact_id,
                col(PatientEmergencyContact.patient_id) == patient.id,
                col(PatientEmergencyContact.removed_at).is_(None),
            )
        ).first()
        if contact is None:
            return PatientRefusal(status_code=404)
        contact.removed_at = datetime.now(UTC)
        contact.removed_by = actor.user_id
        session.add(contact)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_UPDATE,
                result="SUCCESS",
                resource_id=patient.id,
                payload={"changed_fields": ["emergency_contacts"]},
            ),
        )
        return _active_contacts(session, patient_id=patient.id)


# ---------------------------------------------------------------------------------------------
# For patient intake (docs3 feature 03): on the caller's transaction, through this facade
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PatientSummary:
    """Who an application is for, as the queue shows it."""

    name: str
    date_of_birth: date
    status: str


def summaries(
    session: Session, *, tenant_id: uuid.UUID, patient_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, PatientSummary]:
    if not patient_ids:
        return {}
    rows = session.exec(
        select(Patient).where(
            col(Patient.tenant_id) == tenant_id,
            col(Patient.id).in_(sorted(set(patient_ids))),
        )
    ).all()
    return {
        p.id: PatientSummary(
            name=f"{p.preferred_name or p.given_name} {p.family_name}",
            date_of_birth=p.date_of_birth,
            status=p.status,
        )
        for p in rows
    }


def accept_applicant(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    created_by_application: bool,
    details: dict[str, str],
    pharmacy_id: uuid.UUID | None,
) -> None:
    """File an accepted application onto its patient (manual §5.4), on the caller's transaction.

    A record the application created gets the submitted sex and address and becomes `CURRENT`. A
    matched record keeps its own details: a public form is never a source of truth for them. Either
    way the chosen pharmacy becomes the default for future scripts. Audited `patient.update` with the
    field names only.
    """
    patient = _live_patient(session, tenant_id=tenant_id, patient_id=patient_id)
    if patient is None:
        return
    changed = ["preferred_pharmacy_id"]
    patient.preferred_pharmacy_id = pharmacy_id
    if created_by_application:
        patient.sqlmodel_update(details)
        changed.extend(sorted(details))
        if patient.status == "REVIEW":
            patient.status = "CURRENT"
            patient.status_changed_at = datetime.now(UTC)
            changed.append("status")
    session.add(patient)
    session.flush()
    audit.record(
        session,
        audit.AuditEvent(
            action=PATIENT_UPDATE,
            result="SUCCESS",
            resource_id=patient.id,
            reason="INTAKE_ACCEPTED",
            payload={"changed_fields": changed},
        ),
    )


def archive_rejected_applicant(
    session: Session, *, tenant_id: uuid.UUID, patient_id: uuid.UUID
) -> None:
    """A record a rejected application created leaves the active lists (`ARCHIVED`), never deleted."""
    patient = _live_patient(session, tenant_id=tenant_id, patient_id=patient_id)
    if patient is None or patient.status != "REVIEW":
        return
    patient.status = "ARCHIVED"
    patient.status_reason = "Online application not accepted"
    patient.status_changed_at = datetime.now(UTC)
    session.add(patient)
    session.flush()
    audit.record(
        session,
        audit.AuditEvent(
            action=PATIENT_UPDATE,
            result="SUCCESS",
            resource_id=patient.id,
            reason="STATUS_ARCHIVED",
            payload={"changed_fields": ["status", "status_reason"]},
        ),
    )


def set_preferred_pharmacy(
    *, actor: Actor, patient_id: uuid.UUID, pharmacy_id: uuid.UUID | None
) -> PatientRead | PatientRefusal:
    """Change the patient's pharmacy (manual §3.5). The FK keeps it inside the tenant's directory."""
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        patient = _patient_to_change(session, actor=actor, patient_id=patient_id)
        if isinstance(patient, PatientRefusal):
            return patient
        patient.preferred_pharmacy_id = pharmacy_id
        session.add(patient)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_UPDATE,
                result="SUCCESS",
                resource_id=patient.id,
                payload={"changed_fields": ["preferred_pharmacy_id"]},
            ),
        )
        session.refresh(patient)
        return to_read(patient)
