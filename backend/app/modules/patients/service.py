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

Treating `deleted_at` as "not readable": a soft-deleted record is excluded from read, list
and update. Nothing in this slice can set `deleted_at`, so the filter is currently
defensive; the retention and erasure schedule that decides *when* a record is soft-deleted
is open (feature 14, `docs/reference/open-questions.md`).

## Deferred, deliberately — not implemented in this slice

| Item | Why it is deferred |
|---|---|
| Merge and merge/reverse (`POST /patients/{id}/merge`, `.../merge/reverse`) | Reversal rules and step-up are unbuilt, and the merge endpoints sit behind `patient:merge`, which is not in the fixed permission list (`03-design.md`, open items) |
| Search (`POST /api/v1/patients/search`) | Needs the blind-index key, which has no custodian (`04-database-erd.md` open item 5), and the "no search term in a URL" decision (R12) is a separate route |
| Duplicate detection (`GET /patients/{id}/duplicates`) | Requires an exact two-identifier match, so it needs the same unbuilt blind-index key handling |
| Export | Requires step-up, a typed reason and a permission the app cannot yet check |
| Treating-relationship rule | `care_relationships` has no ERD table definition and no named owner — a blocked dependency (`03-design.md`, open items; `01-requirements.md` OPEN-4) |
| Permission / RBAC layer | Feature 03 (authentication and RBAC) is not started; the app has `is_superuser` and ordinary authenticated users only, so there is no central policy layer to call |
| Audit events | Feature 04 is not built and the required action names are not registered anywhere — writing one would mean inventing an action name |
| Identifier validation algorithms | The Medicare check digit, IRN rule and IHI format are unspecified in the source (`01-requirements.md` OPEN-1, requires legal/regulatory validation) |
| Field-level encryption and blind-index key handling | Key custody and rotation are OPEN (`03-design.md`, open items), so no identifier is accepted or stored by this slice |
| Soft-delete and retention scheduling | A privacy decision, not an engineering one (feature 14; `database-conventions.md`, "Reconciled with the rest of this document set") |
| Identifier masking on output | Not applicable while no identifier is exposed; R9's mask applies when one is added |
| Cursor pagination, `Idempotency-Key`, rate limits, the shared error envelope | Cross-cutting API standards (`definition-of-done.md` §4) with no implementation anywhere in the app yet; this slice bounds the list with a server maximum instead |
"""

import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, func, select

from app.core.db import tenant_transaction
from app.modules.patients.models import Patient
from app.modules.patients.schemas import (
    PatientCreate,
    PatientRead,
    PatientsPublic,
    PatientUpdate,
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
) -> PatientRead:
    """Insert one patient for the resolved tenant.

    The tenant is bound from the argument, never from the request body, so a caller cannot
    place a row in another tenant even if a future schema error let a `tenant_id` through.
    The RLS `WITH CHECK` clause refuses the insert independently.
    """
    with tenant_transaction(tenant_id=tenant_id, actor_id=actor_id) as session:
        patient = Patient(tenant_id=tenant_id, **patient_in.model_dump())
        session.add(patient)
        session.flush()
        session.refresh(patient)
        return PatientRead.model_validate(patient)


def list_patients(*, tenant_id: uuid.UUID, limit: int) -> PatientsPublic:
    """The caller's patients, ordered by family name, given name, id, bounded by `limit`.

    `count` is the tenant's live total, which the router's `limit` does not change; cursor
    pagination is deferred (see the module docstring).
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        scope = (Patient.tenant_id == tenant_id, col(Patient.deleted_at).is_(None))
        count = session.exec(
            select(func.count()).select_from(Patient).where(*scope)
        ).one()
        statement = (
            select(Patient)
            .where(*scope)
            .order_by(
                col(Patient.family_name), col(Patient.given_name), col(Patient.id)
            )
            .limit(limit)
        )
        patients: Sequence[Patient] = session.exec(statement).all()
        return PatientsPublic(
            data=[PatientRead.model_validate(patient) for patient in patients],
            count=count,
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
) -> PatientRead | None:
    """Apply a partial update to one live patient for this tenant, or `None`.

    Only the fields the client sent are touched (`exclude_unset`), so an omitted field is
    never overwritten with a default and a `PATCH` cannot clear a NOT NULL column.
    """
    with tenant_transaction(tenant_id=tenant_id, actor_id=actor_id) as session:
        patient = _live_patient(session, tenant_id=tenant_id, patient_id=patient_id)
        if patient is None:
            return None
        patient.sqlmodel_update(patient_in.model_dump(exclude_unset=True))
        session.add(patient)
        session.flush()
        session.refresh(patient)
        return PatientRead.model_validate(patient)
