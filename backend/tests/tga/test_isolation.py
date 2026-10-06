"""Tenant isolation and the append-only grants: S1-S4 and S12a-S12c.

Every case here is measured, not inherited from a document. `SET LOCAL ROLE clinos_app` is how the
row-level security policy and the grants are provoked: `clinos_app` is created `NOLOGIN PASSWORD NULL`
(a credential does not belong in a migration), so a test cannot connect as it, and `SET ROLE` assumes
it inside an existing session — which is exactly what PostgreSQL checks privileges and policies
against. Rows are asserted on the **owner** connection when the question is "does this row exist",
because the owner bypasses RLS and can therefore answer it.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.db import engine
from tests.tga.conftest import TenantWithPatient, TgaApi, problem_code

INSUFFICIENT_PRIVILEGE = "42501"


def _statement_as_clinos_app(statement: str, params: dict[str, object]) -> str | None:
    """Run one statement as `clinos_app` and return the SQLSTATE that refused it.

    `None` means it was **allowed**, which is the failure the caller asserts on. Each statement gets
    its own connection: PostgreSQL aborts a transaction on the first failed statement, so a shared
    connection would poison every case after it.
    """
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": params.get("tenant_id", "")},
            )
            try:
                conn.execute(text(statement), params)
            except ProgrammingError as error:
                if error.orig is None:
                    return None
                return str(getattr(error.orig, "sqlstate", ""))
    return None


def test_a_cross_tenant_read_is_404_and_not_403(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """S1, R8: a `403` would confirm that the record exists."""
    intruder = api.register(clinic_name="Synthetic Clinic B")
    approval = api.create(clinic.owner, clinic.patient_id)

    for response in (
        api.read(intruder, approval["id"]),
        api.revoke(intruder, approval["id"]),
        api.client.post(
            f"/api/v1/tga-approvals/{approval['id']}/verify",
            json={"tga_application_number": approval["approval_reference"]},
            headers=intruder.headers,
        ),
    ):
        assert response.status_code == 404, response.text
        # The refusal carries no identifier and no existence signal.
        assert approval["id"] not in response.text

    # The intruder cannot even name the patient, which is the same rule one level up.
    assert api.list_for_patient(intruder, clinic.patient_id).status_code == 404


def test_the_match_route_does_not_answer_for_another_tenants_patient(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """A cross-tenant lookup discloses nothing: no approval, and the same answer as "none exists"."""
    intruder = api.register(clinic_name="Synthetic Clinic B")
    verifier = api.second_clinician(owner=clinic.owner)
    approval = api.create(clinic.owner, clinic.patient_id)
    assert api.activate(clinic.owner, approval, verifier=verifier).status_code == 200

    response = api.match(intruder, clinic.patient_id, date_of_service="2026-06-01")
    assert response.status_code == 200, response.text
    assert response.json()["matched"] is False
    # `NOT_FOUND`, not a mismatch: which grain the other tenant holds is not disclosed either.
    assert response.json()["reason_code"] == "TGA_APPROVAL_NOT_FOUND"
    assert response.json()["approval_id"] is None


def test_the_app_role_sees_zero_foreign_rows(api: TgaApi, clinic: TenantWithPatient) -> None:
    """S2, S3: raw SQL as `clinos_app`, with no application filter, and with no tenant at all."""
    intruder = api.register(clinic_name="Synthetic Clinic B")
    approval = api.create(clinic.owner, clinic.patient_id)
    assert clinic.owner.tenant_id is not None and intruder.tenant_id is not None

    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            # Tenant A's context: the foreign row is simply not in the result set.
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(intruder.tenant_id)},
            )
            visible = conn.execute(
                text("SELECT count(*) FROM tga_approvals WHERE id = :id"),
                {"id": uuid.UUID(approval["id"])},
            ).scalar_one()
            assert int(visible) == 0

            # No tenant context at all: `NULLIF(..., '')::uuid` is NULL, `tenant_id = NULL` matches
            # nothing, so the fail-closed answer is zero rows rather than every row.
            conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            total = conn.execute(text("SELECT count(*) FROM tga_approvals")).scalar_one()
            assert int(total) == 0


def test_an_insert_that_forges_another_tenants_key_is_refused(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """T2-2: the `WITH CHECK` clause, not just `USING`, is what makes a forged key impossible."""
    intruder = api.register(clinic_name="Synthetic Clinic B")
    assert clinic.owner.tenant_id is not None and intruder.tenant_id is not None

    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(intruder.tenant_id)},
            )
            with pytest.raises(ProgrammingError) as refused:
                conn.execute(
                    text(
                        "INSERT INTO tga_approvals (tenant_id, patient_id, tga_category,"
                        " dosage_form, approval_reference, valid_from, valid_to, state,"
                        " source, creation_reason, created_by, created_at, updated_at)"
                        " VALUES (:tenant_id, :patient_id, 'CATEGORY_3', 'ORAL_OIL',"
                        " 'TGA-FORGED', '2026-01-01', '2026-07-01', 'PENDING', 'MANUAL_ENTRY',"
                        " 'MANUAL_ENTRY', :created_by, now(), now())"
                    ),
                    {
                        "tenant_id": clinic.owner.tenant_id,
                        "patient_id": clinic.patient_id,
                        "created_by": uuid.uuid4(),
                    },
                )
    assert str(getattr(refused.value.orig, "sqlstate", "")) == "42501"


def test_the_app_role_cannot_delete_or_truncate_an_approval() -> None:
    """S12c, R13: hard deletion is refused by **privilege**, not by convention."""
    for statement in ("DELETE FROM tga_approvals", "TRUNCATE tga_approvals"):
        assert _statement_as_clinos_app(statement, {}) == INSUFFICIENT_PRIVILEGE, statement


def test_the_event_log_is_append_only_by_grant() -> None:
    """S12a, S12b, design §"SQL Grants by Table": `SELECT, INSERT` and nothing else."""
    assert (
        _statement_as_clinos_app(
            "UPDATE tga_approval_events SET reason = 'TAMPERED'", {}
        )
        == INSUFFICIENT_PRIVILEGE
    )
    assert (
        _statement_as_clinos_app("DELETE FROM tga_approval_events", {})
        == INSUFFICIENT_PRIVILEGE
    )
    assert (
        _statement_as_clinos_app("TRUNCATE tga_approval_events", {})
        == INSUFFICIENT_PRIVILEGE
    )

    with engine.connect() as conn:
        grants = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants"
                    " WHERE grantee = 'clinos_app'"
                    " AND table_name IN ('tga_approvals', 'tga_approval_events')"
                )
            )
        }
        events = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants"
                    " WHERE grantee = 'clinos_app' AND table_name = 'tga_approval_events'"
                )
            )
        }
        approvals = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants"
                    " WHERE grantee = 'clinos_app' AND table_name = 'tga_approvals'"
                )
            )
        }
        roles = conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'clinos_app'"
            )
        ).one()
        owner = conn.execute(
            text(
                "SELECT r.rolname FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner"
                " WHERE c.relname = 'tga_approvals'"
            )
        ).scalar_one()

    assert grants == {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"} - {
        "DELETE",
        "TRUNCATE",
    }
    assert events == {"SELECT", "INSERT"}
    assert "DELETE" not in approvals and "TRUNCATE" not in approvals
    assert owner != "clinos_app", "the application role must not own the table"
    assert roles[0] is False and roles[1] is False, "no SUPERUSER, no BYPASSRLS"


def test_a_patient_from_another_tenant_cannot_be_named(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """The composite foreign key, not a service check: `(tenant_id, patient_id)` is a pair."""
    intruder = api.register(clinic_name="Synthetic Clinic B")
    assert clinic.owner.tenant_id is not None and intruder.tenant_id is not None

    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(intruder.tenant_id)},
            )
            with pytest.raises(ProgrammingError) as refused:
                conn.execute(
                    text(
                        "INSERT INTO tga_approvals (tenant_id, patient_id, tga_category,"
                        " dosage_form, approval_reference, valid_from, valid_to, state,"
                        " source, creation_reason, created_by, created_at, updated_at)"
                        " VALUES (:tenant_id, :patient_id, 'CATEGORY_3', 'ORAL_OIL',"
                        " 'TGA-CROSS-PATIENT', '2026-01-01', '2026-07-01', 'PENDING',"
                        " 'MANUAL_ENTRY', 'MANUAL_ENTRY', :created_by, now(), now())"
                    ),
                    {
                        "tenant_id": intruder.tenant_id,
                        "patient_id": clinic.patient_id,
                        "created_by": uuid.uuid4(),
                    },
                )
    assert str(getattr(refused.value.orig, "sqlstate", "")) == "23503"
