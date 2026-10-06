"""F13, S7-S11, R12-R14 — immutability at both database layers.

Design: `docs/features/06-clinical-records/03-design.md` §"Immutability mechanism at two layers";
requirements R12, R13, R14; threat T-CLIN-03/T-CLIN-04.

*"Enforcement is by grant, not by convention. A convention is bypassed by a determined developer; a
missing privilege is not."* These cases read the grant listing back out of PostgreSQL and then try
the statements anyway — as the application role, as the migration role and as the table owner.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import engine
from tests.clinical_records.conftest import (
    CLINICAL_URL,
    ClinicalApi,
    ClinicalTenant,
    created_record,
)

CLINICAL_TABLES = ("clinical_records", "clinical_record_versions")

_MUTATIONS = (
    "UPDATE clinical_record_versions SET body = 'tampered' WHERE id = :id",
    "DELETE FROM clinical_record_versions WHERE id = :id",
)


def _table_grants(table: str) -> set[str]:
    with engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants"
                    " WHERE grantee = 'clinos_app' AND table_name = :table"
                ),
                {"table": table},
            )
        }


def _column_grants(table: str) -> set[str]:
    with engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.column_privileges"
                    " WHERE grantee = 'clinos_app' AND table_name = :table"
                    " AND privilege_type = 'UPDATE'"
                ),
                {"table": table},
            )
        }


def test_role_table_grants_exact() -> None:
    """S11 / R13: versions grant exactly `{SELECT, INSERT}`; records cannot be deleted or truncated."""
    version_privileges = _table_grants("clinical_record_versions")
    record_privileges = _table_grants("clinical_records")

    assert version_privileges == {"SELECT", "INSERT"}, version_privileges
    assert record_privileges == {"SELECT", "INSERT"}, record_privileges
    assert "DELETE" not in record_privileges and "TRUNCATE" not in record_privileges
    # The one UPDATE the design grants on the parent is column-scoped, which is why it does not
    # appear in the table-level listing above.
    assert _column_grants("clinical_records") == {
        "current_version",
        "signed_at",
        "deleted_at",
    }
    assert _column_grants("clinical_record_versions") == set()


def test_app_role_cannot_mutate_versions(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """S7 / S8 / R13: the primary layer — the grant denies the statement (`42501`)."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    version_id = record["versions"][0]["id"]

    for statement in _MUTATIONS:
        # A failed statement aborts its transaction, so each attempt gets a fresh one.
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            with pytest.raises(DBAPIError) as refusal:
                conn.execute(text(statement), {"id": version_id})
        message = str(refusal.value).lower()
        assert "42501" in str(refusal.value) or "permission denied" in message, (
            statement
        )

    # The version is still exactly what it was.
    assert (
        clinical.version_rows(tenant.tenant_id, record["id"])[0]["body"]
        == (record["versions"][0]["body"])
    )


def test_app_role_cannot_rewrite_attribution_columns(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R13: the column-scoped grant keeps `tenant_id`, `patient_id` and `author_id` un-rewritable."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))

    for column in ("tenant_id", "patient_id", "author_id", "record_type"):
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            with pytest.raises(DBAPIError) as refusal:
                conn.execute(
                    text(
                        f"UPDATE clinical_records SET {column} = :value WHERE id = :id"
                    ),
                    {"id": record["id"], "value": tenant.owner.user_id},
                )
        assert "permission denied" in str(refusal.value).lower(), column


def test_trigger_blocks_the_owner(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """S9 / S10 / R14: defence in depth — a `BEFORE UPDATE OR DELETE` trigger with no role exemption.

    The connection here is `postgres`, which owns both tables and is a superuser: the grant layer
    does not bind it, and the trigger does.
    """
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    version_id = record["versions"][0]["id"]

    for statement in _MUTATIONS:
        with engine.begin() as conn:
            with pytest.raises(DBAPIError) as refusal:
                conn.execute(text(statement), {"id": version_id})
        assert "CLINICAL_RECORD_VERSION_IMMUTABLE" in str(refusal.value), statement

    assert (
        clinical.version_rows(tenant.tenant_id, record["id"])[0]["body"]
        == (record["versions"][0]["body"])
    )


def test_migration_role_cannot_mutate_versions(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R14: the migration role is refused too — by the trigger, or by the grant that precedes it.

    `clinos_migrator` owns nothing and holds no table privilege on this table, so its statement is
    denied before the trigger is reached. Both refusals are the control working; what must not happen
    is the statement succeeding.
    """
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    version_id = record["versions"][0]["id"]

    for statement in _MUTATIONS:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL ROLE clinos_migrator"))
            with pytest.raises(DBAPIError) as refusal:
                conn.execute(text(statement), {"id": version_id})
        assert "permission denied" in str(refusal.value).lower(), statement


def test_no_delete_route_exists(clinical: ClinicalApi, tenant: ClinicalTenant) -> None:
    """F13 / R12: there is no delete path, and no `TRUNCATE` privilege for the application role."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))

    deleted = clinical.client.delete(
        f"{CLINICAL_URL}/{record['id']}", headers=tenant.owner.headers
    )
    assert deleted.status_code == 405, deleted.text
    assert "TRUNCATE" not in _table_grants("clinical_records")
    assert "TRUNCATE" not in _table_grants("clinical_record_versions")


def test_soft_delete_via_restricted_columns_is_the_only_mutation_left(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R12: the parent may be soft-deleted (`deleted_at`), and its versions stay intact."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))

    with engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE clinos_app"))
        # A tenant context is what makes the caller's own row visible to the forced policy; without
        # it the policy matches nothing and the statement would silently affect zero rows.
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant.tenant_id)},
        )
        conn.execute(
            text("UPDATE clinical_records SET deleted_at = now() WHERE id = :id"),
            {"id": record["id"]},
        )

    assert clinical.read_record(tenant.owner, record["id"]).status_code == 404
    assert len(clinical.version_rows(tenant.tenant_id, record["id"])) == 1
