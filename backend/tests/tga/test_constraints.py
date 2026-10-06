"""The controls the database owns: the GiST exclusion constraint, the checks and the triggers.

F8, F10, S12a-S12d, R11, R12 and INV-2. Every case here provokes the database **directly** with raw
SQL, because the question is not whether the service refuses a bad input — it does, and
`test_lifecycle.py` proves it — but whether the invariant holds for a caller that never went through
the service at all. That is what "enforce it in the database, not only in Python" means.

The helper inserts with `INSERT ... RETURNING id` and never supplies `validity_interval`: the trigger
derives it, and a test that supplied it could not tell a derived column from a copied one.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import engine
from tests.tga.conftest import TenantWithPatient, TgaApi

# PostgreSQL's SQLSTATEs, asserted rather than "it raised": the difference between "the engine refused
# this" and "the statement was malformed" is the difference between a control and a typo.
EXCLUSION_VIOLATION = "23P01"
CHECK_VIOLATION = "23514"


def _sqlstate(error: DBAPIError) -> str | None:
    return str(getattr(error.orig, "sqlstate", "")) or None


def _execute(statement: str, params: dict[str, object]) -> None:
    """Run one statement on its own connection.

    The connection is opened *inside* this helper so a refused statement never leaves an aborted
    transaction for the caller's `engine.begin()` to commit: PostgreSQL aborts the transaction the
    moment a statement fails, and the commit that follows would raise `PendingRollbackError` — which
    would look like a failure of the test rather than the refusal being asserted.
    """
    with engine.begin() as conn:
        conn.execute(text(statement), params)


def test_two_overlapping_active_approvals_at_one_grain_are_refused(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F8, R11, T-04.4, Gate 2: the second live approval at the grain does not exist."""
    assert clinic.owner.tenant_id is not None
    first = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="ACTIVE",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
    )
    with pytest.raises(DBAPIError) as refused:
        api.insert_approval(
            tenant_id=clinic.owner.tenant_id,
            patient_id=clinic.patient_id,
            state="ACTIVE",
            approval_reference="TGA-RAW-000002",
            valid_from="2026-06-01",
            valid_to="2026-12-01",
        )
    assert _sqlstate(refused.value) == EXCLUSION_VIOLATION
    assert "no_overlapping_active_approvals" in str(refused.value)

    # The grain is a conjunction: changing any one dimension makes it a different grain, and a
    # different grain may hold a live approval at the same time. Asserted for the dosage form,
    # which is the dimension most easily forgotten.
    other_form = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="ACTIVE",
        dosage_form="SUBLINGUAL",
        approval_reference="TGA-RAW-000003",
        valid_from="2026-06-01",
        valid_to="2026-12-01",
    )
    assert api.row(str(first))["state"] == "ACTIVE"
    assert api.row(str(other_form))["state"] == "ACTIVE"


def test_adjacent_windows_do_not_overlap_because_the_boundary_is_half_open(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """D-006 §2 at the database: `[2026-01-01, 2026-07-01)` and `[2026-07-01, 2026-12-01)`.

    A half-open interval is what lets a renewal start on the day the previous one ends without the
    exclusion constraint refusing it. Under an inclusive reading the second insert would collide, so
    this test is the database's copy of the boundary decision.
    """
    assert clinic.owner.tenant_id is not None
    api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="ACTIVE",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
    )
    renewal = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="ACTIVE",
        approval_reference="TGA-RAW-000010",
        valid_from="2026-07-01",
        valid_to="2026-12-01",
    )
    assert api.row(str(renewal))["state"] == "ACTIVE"


def test_two_tenants_may_hold_the_same_grain(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """T2-3: the constraint is per tenant, so `tenant_id` leads it — a global collision would leak."""
    other = api.register(clinic_name="Synthetic Clinic B")
    assert clinic.owner.tenant_id is not None and other.tenant_id is not None
    other_patient = api.create_patient(other)

    for tenant_id, patient_id in (
        (clinic.owner.tenant_id, clinic.patient_id),
        (other.tenant_id, other_patient),
    ):
        api.insert_approval(
            tenant_id=tenant_id,
            patient_id=patient_id,
            state="ACTIVE",
            valid_from="2026-01-01",
            valid_to="2026-07-01",
        )


def test_a_superseded_row_does_not_collide_with_its_replacement(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """D-006 §1: the constraint is **partial** on `state = 'ACTIVE'`, which is what makes the
    supersede chain possible at all. A `SUPERSEDED` row and its replacement share a grain and a
    window, and both exist."""
    assert clinic.owner.tenant_id is not None
    replacement = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="ACTIVE",
        approval_reference="TGA-RAW-000020",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
    )
    predecessor = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="SUPERSEDED",
        approval_reference="TGA-RAW-000019",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
        superseded_by_id=replacement,
    )
    assert api.row(str(predecessor))["state"] == "SUPERSEDED"
    assert api.row(str(replacement))["state"] == "ACTIVE"

    # A `SUPERSEDED` row must name the grant that replaced it, or the history is not reconstructible.
    with pytest.raises(DBAPIError) as refused:
        api.insert_approval(
            tenant_id=clinic.owner.tenant_id,
            patient_id=clinic.patient_id,
            state="SUPERSEDED",
            approval_reference="TGA-RAW-000021",
            valid_from="2025-01-01",
            valid_to="2025-06-01",
        )
    assert _sqlstate(refused.value) == CHECK_VIOLATION
    assert "ck_tga_approvals_superseded_link" in str(refused.value)


def test_the_two_year_ceiling_is_a_database_check(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """R3, F3: the schema refuses it *and* the row is not storable."""
    assert clinic.owner.tenant_id is not None
    with pytest.raises(DBAPIError) as refused:
        api.insert_approval(
            tenant_id=clinic.owner.tenant_id,
            patient_id=clinic.patient_id,
            valid_from="2026-01-01",
            valid_to="2028-01-02",
        )
    assert _sqlstate(refused.value) == CHECK_VIOLATION
    assert "ck_tga_approvals_max_duration" in str(refused.value)


def test_four_eyes_is_a_database_check(api: TgaApi, clinic: TenantWithPatient) -> None:
    """T-04.10: even a raw insert cannot make one actor both the creator and the verifier."""
    assert clinic.owner.tenant_id is not None
    actor = uuid.uuid4()
    with pytest.raises(DBAPIError) as refused:
        api.insert_approval(
            tenant_id=clinic.owner.tenant_id,
            patient_id=clinic.patient_id,
            state="ACTIVE",
            created_by=actor,
            verified_by=actor,
        )
    assert _sqlstate(refused.value) == CHECK_VIOLATION
    assert "ck_tga_approvals_four_eyes" in str(refused.value)


def test_an_active_row_must_carry_its_verification(
    clinic: TenantWithPatient,
) -> None:
    """T2-4: `state = 'ACTIVE'` implies `verified_at IS NOT NULL`."""
    assert clinic.owner.tenant_id is not None
    with pytest.raises(DBAPIError) as refused:
        _execute(
            "INSERT INTO tga_approvals (tenant_id, patient_id, tga_category,"
            " dosage_form, approval_reference, valid_from, valid_to, state, source,"
            " creation_reason, created_by, created_at, updated_at)"
            " VALUES (:tenant_id, :patient_id, 'CATEGORY_3', 'ORAL_OIL', 'TGA-RAW-X',"
            " '2026-01-01', '2026-07-01', 'ACTIVE', 'MANUAL_ENTRY', 'MANUAL_ENTRY',"
            " :created_by, now(), now())",
            {
                "tenant_id": clinic.owner.tenant_id,
                "patient_id": clinic.patient_id,
                "created_by": uuid.uuid4(),
            },
        )
    assert _sqlstate(refused.value) == CHECK_VIOLATION
    assert "ck_tga_approvals_active_verified" in str(refused.value)


def test_a_verified_approval_is_immutable(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F10, S12d, T-04.3: the trigger raises `VERIFIED_APPROVAL_IMMUTABLE` on the core fields."""
    assert clinic.owner.tenant_id is not None
    approval = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="ACTIVE",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
    )
    for statement in (
        "UPDATE tga_approvals SET valid_to = valid_to + interval '1 year' WHERE id = :id",
        "UPDATE tga_approvals SET dosage_form = 'INHALATION' WHERE id = :id",
        "UPDATE tga_approvals SET approval_reference = 'TGA-RAW-999999' WHERE id = :id",
        "UPDATE tga_approvals SET verified_by = NULL WHERE id = :id",
    ):
        with pytest.raises(DBAPIError) as refused:
            _execute(statement, {"id": approval})
        assert "VERIFIED_APPROVAL_IMMUTABLE" in str(refused.value), statement

    # The row is unchanged, and a lifecycle transition is still permitted — which is the whole point:
    # immutability of the *grain*, not of the state.
    row = api.row(str(approval))
    assert row["valid_to"].isoformat() == "2026-07-01"
    assert row["state"] == "ACTIVE"
    _execute(
        "UPDATE tga_approvals SET state = 'REVOKED',"
        " revoked_reason_code = 'CLINICAL_ERROR' WHERE id = :id",
        {"id": approval},
    )
    assert api.row(str(approval))["state"] == "REVOKED"


def test_a_terminal_approval_is_frozen(api: TgaApi, clinic: TenantWithPatient) -> None:
    """A `REVOKED`, `EXPIRED`, `REJECTED` or `SUPERSEDED` row may not change at all."""
    assert clinic.owner.tenant_id is not None
    approval = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="REVOKED",
        revoked_reason_code="CLINICAL_ERROR",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
    )
    with pytest.raises(DBAPIError) as refused:
        _execute(
            "UPDATE tga_approvals SET revoked_reason_code = 'OTHER' WHERE id = :id",
            {"id": approval},
        )
    assert "VERIFIED_APPROVAL_IMMUTABLE" in str(refused.value)


def test_the_trigger_refuses_an_illegal_transition(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """T2-8: the state machine is in the database too, so a caller that skips the service meets it."""
    assert clinic.owner.tenant_id is not None
    approval = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="PENDING",
    )
    for target in ("EXPIRED", "SUPERSEDED"):
        with pytest.raises(DBAPIError) as refused:
            _execute(
                "UPDATE tga_approvals SET state = :state WHERE id = :id",
                {"state": target, "id": approval},
            )
        assert "ILLEGAL_STATE_TRANSITION" in str(refused.value), target


def test_the_interval_is_derived_and_cannot_be_set_by_a_caller(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """The trigger owns `validity_interval`: even an explicit wrong value is overwritten.

    This is what makes the exclusion constraint's index key trustworthy — the column the constraint
    compares can only ever be the range the row's own dates describe.
    """
    assert clinic.owner.tenant_id is not None
    with engine.begin() as conn:
        approval = uuid.UUID(
            str(
                conn.execute(
                    text(
                        "INSERT INTO tga_approvals (tenant_id, patient_id, tga_category,"
                        " dosage_form, approval_reference, valid_from, valid_to,"
                        " validity_interval, state, source, creation_reason, created_by,"
                        " created_at, updated_at)"
                        " VALUES (:tenant_id, :patient_id, 'CATEGORY_3', 'ORAL_OIL',"
                        " 'TGA-RAW-DERIVED', '2026-01-01', '2026-07-01',"
                        " daterange('1999-01-01', '1999-02-01', '[)'), 'PENDING', 'MANUAL_ENTRY',"
                        " 'MANUAL_ENTRY', :created_by, now(), now()) RETURNING id"
                    ),
                    {
                        "tenant_id": clinic.owner.tenant_id,
                        "patient_id": clinic.patient_id,
                        "created_by": uuid.uuid4(),
                    },
                ).scalar_one()
            )
        )
    assert api.interval_is_derived(
        str(approval), valid_from="2026-01-01", valid_to="2026-07-01"
    )
