"""Test-only row seeding for the tenancy tables.

The isolation and policy tests need rows that no route can create in this slice: `clinics` has no
create route yet (the Feature 01 backlog names the table and the two `tenants/current` routes only) and
`care_relationships` has none at all (no document names one). These helpers insert **as the owner
connection**, which is the table owner and holds `BYPASSRLS`.

That is deliberate, and it is why the seed is not the test: rows written as the owner are exactly the
rows the controls must hide imperfectly from nobody, so the assertions are about what `clinos_app` or the
service facade can reach, never about what the owner wrote. `tests/isolation/test_patients_isolation.py`
states the same rule for its own fixture.

Cleanup runs in foreign-key order (RESTRICT throughout): relationships, then clinics, then patients,
then accounts, then the tenant. `tests/conftest.py` deletes every account at session teardown, so a
fixture that leaves a relationship behind would fail the whole run rather than one test.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.sql.elements import TextClause

_INSERT_TENANT = sa.text(
    "INSERT INTO tenants (id, slug, legal_name, status, data_region, retention_profile,"
    " created_at, updated_at)"
    " VALUES (:id, :slug, :legal_name, 'ACTIVE', 'ap-southeast-2', 'default', now(), now())"
)
_INSERT_CLINIC = sa.text(
    "INSERT INTO clinics (id, tenant_id, name, address, phone, created_at, updated_at)"
    " VALUES (gen_random_uuid(), :tenant_id, :name, :address, :phone, now(), now())"
    " RETURNING id"
)
_INSERT_PATIENT = sa.text(
    "INSERT INTO patients (id, tenant_id, given_name, family_name, date_of_birth, created_at,"
    " updated_at)"
    " VALUES (gen_random_uuid(), :tenant_id, :given_name, 'Isolation', '1990-01-01', now(), now())"
    " RETURNING id"
)
_INSERT_PRACTITIONER = sa.text(
    'INSERT INTO "user" (id, email, hashed_password, is_active, is_superuser, full_name, tenant_id,'
    " created_at)"
    " VALUES (gen_random_uuid(), :email, 'not-a-real-hash', true, false, 'Synthetic Practitioner',"
    " :tenant_id, now())"
    " RETURNING id"
)
_INSERT_RELATIONSHIP = sa.text(
    "INSERT INTO care_relationships (id, tenant_id, practitioner_id, patient_id, clinic_id,"
    " active_from, active_to, source, created_at, updated_at)"
    " VALUES (gen_random_uuid(), :tenant_id, :practitioner_id, :patient_id, :clinic_id,"
    " :active_from, :active_to, :source, now(), now())"
    " RETURNING id"
)

# FK order, children first. `user_roles` is not touched: these helpers never create a grant, and the
# RBAC fixtures clean their own up.
_DELETE_ORDER = (
    "DELETE FROM care_relationships WHERE tenant_id = ANY(:tenant_ids)",
    "DELETE FROM clinics WHERE tenant_id = ANY(:tenant_ids)",
    "DELETE FROM patients WHERE tenant_id = ANY(:tenant_ids)",
    'DELETE FROM "user" WHERE tenant_id = ANY(:tenant_ids)',
    "DELETE FROM tenants WHERE id = ANY(:tenant_ids)",
)


def _scalar(
    conn: Connection, statement: TextClause, params: dict[str, object]
) -> uuid.UUID:
    return uuid.UUID(str(conn.execute(statement, params).scalar_one()))


def create_tenant(conn: Connection, *, name: str) -> uuid.UUID:
    """One ACTIVE tenant in the Australian region, with a unique slug."""
    tenant_id = uuid.uuid4()
    conn.execute(
        _INSERT_TENANT,
        {
            "id": tenant_id,
            "slug": f"iso-{tenant_id.hex[:20]}",
            "legal_name": name,
        },
    )
    return tenant_id


def create_clinic(
    conn: Connection,
    *,
    tenant_id: uuid.UUID,
    name: str,
    address: str | None = "1 Synthetic Street",
    phone: str | None = "0000 000 000",
) -> uuid.UUID:
    return _scalar(
        conn,
        _INSERT_CLINIC,
        {
            "tenant_id": tenant_id,
            "name": name,
            "address": address,
            "phone": phone,
        },
    )


def create_patient(
    conn: Connection, *, tenant_id: uuid.UUID, given_name: str
) -> uuid.UUID:
    return _scalar(
        conn, _INSERT_PATIENT, {"tenant_id": tenant_id, "given_name": given_name}
    )


def create_practitioner(conn: Connection, *, tenant_id: uuid.UUID) -> uuid.UUID:
    """One account of this tenant — the design's `practitioner_id` referent."""
    return _scalar(
        conn,
        _INSERT_PRACTITIONER,
        {"tenant_id": tenant_id, "email": f"practitioner-{uuid.uuid4()}@example.com"},
    )


def create_relationship(
    conn: Connection,
    *,
    tenant_id: uuid.UUID,
    practitioner_id: uuid.UUID,
    patient_id: uuid.UUID,
    clinic_id: uuid.UUID | None = None,
    source: str = "SYNTHETIC_TEST",
    active_from: datetime | None = None,
    active_to: datetime | None = None,
) -> uuid.UUID:
    """One treating relationship. Defaults to an open-ended interval starting now."""
    return _scalar(
        conn,
        _INSERT_RELATIONSHIP,
        {
            "tenant_id": tenant_id,
            "practitioner_id": practitioner_id,
            "patient_id": patient_id,
            "clinic_id": clinic_id,
            "active_from": active_from or datetime.now(UTC),
            "active_to": active_to,
            "source": source,
        },
    )


def delete_tenancy_rows(conn: Connection, *tenant_ids: uuid.UUID) -> None:
    """Remove everything these helpers create for the named tenants, in foreign-key order."""
    params = {"tenant_ids": list(tenant_ids)}
    for statement in _DELETE_ORDER:
        conn.execute(sa.text(statement), params)
