"""Clinics service facade — the only place `clinics` is queried.

Design: `docs/features/01-tenancy-and-clinics/03-design.md`, "Table: `clinics` (tenant-scoped)" and
"RLS policy". Environment: `docs/reference/database-conventions.md` ("Modules per domain") — a module
owns its tables and is reached only through its service facade.

Rules this module holds to, the same four the patients service states and for the same reasons:

- **Every query runs inside `app.core.db.tenant_transaction(...)`**, which sets `app.tenant_id` with
  `SET LOCAL` for the life of the transaction and refuses to open without a tenant. That is what
  activates the forced row-level security policy the migration creates.
- **Every query also carries `tenant_id = :tenant_id`.** That predicate is a second line of defence,
  not the isolation boundary: RLS is the boundary (INV-1). It is present because the deployment
  credential is currently the table owner (with `BYPASSRLS`), which bypasses the policy — recorded in
  the `clinics` migration's docstring. Neither control is removed on the day the other starts working.
- **A missing tenant never reaches this module.** `tenant_transaction` raises before a transaction
  opens.
- **Nothing returns a raw ORM entity.** Rows are converted to `ClinicRead` inside the transaction,
  before the session closes and expires its attributes.

## Read-only in this slice, deliberately

The design's clinic endpoints are not implemented here: the Feature 01 backlog
(`docs/to-be-completed.md`) names the `clinics` table and the two `tenants/current` routes, not the
clinic CRUD routes in `03-design.md` "Endpoints", and those routes require `clinic:read` and
`clinic:manage`, which `01-requirements.md` OPEN-2 records as absent from the fixed 19-permission
catalogue. The isolation proof for the table — cross-tenant absence and a `404` for another tenant's
clinic — needs a read path, and that is what these two functions are. `POST`/`PATCH` arrive with the
catalogue reconciliation, and the table already carries the uniqueness rule (`uq_clinics_tenant_id_name`)
that makes a rename collision a `422` rather than a `500` (R11, test F7).

`list_clinics` is bounded by the caller's `limit`; the design says "cursor-paginated; bounded `limit`"
and cursor pagination is not built anywhere in the app yet, so the bound is the control this slice can
honestly claim.
"""

import uuid
from collections.abc import Sequence

from sqlmodel import col, func, select

from app.core.db import tenant_transaction
from app.modules.clinics.models import Clinic
from app.modules.clinics.schemas import ClinicRead, ClinicsPublic


def list_clinics(*, tenant_id: uuid.UUID, limit: int) -> ClinicsPublic:
    """The caller's clinics, ordered by name then id, bounded by `limit`.

    `count` is the tenant's total, which the router's `limit` does not change.
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        scope = (Clinic.tenant_id == tenant_id,)
        count = session.exec(
            select(func.count()).select_from(Clinic).where(*scope)
        ).one()
        statement = (
            select(Clinic)
            .where(*scope)
            .order_by(col(Clinic.name), col(Clinic.id))
            .limit(limit)
        )
        clinics: Sequence[Clinic] = session.exec(statement).all()
        return ClinicsPublic(
            data=[ClinicRead.model_validate(clinic) for clinic in clinics],
            count=count,
        )


def get_clinic(*, tenant_id: uuid.UUID, clinic_id: uuid.UUID) -> ClinicRead | None:
    """One clinic for this tenant, or `None`.

    `None` is the only not-found answer: the caller cannot tell "another tenant's clinic" from "no
    such clinic", so a route answers `404` for both and never `403` (R9/F9 — a `403` would confirm the
    record exists across the tenant boundary).
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        statement = select(Clinic).where(
            Clinic.id == clinic_id,
            # Defence in depth, as above: RLS is the boundary, this predicate keeps the query scoped
            # for the connection role that currently bypasses the policy.
            Clinic.tenant_id == tenant_id,
        )
        clinic = session.exec(statement).first()
        if clinic is None:
            return None
        return ClinicRead.model_validate(clinic)
