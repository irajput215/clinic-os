"""Database controls that hold even if the service is bypassed (FEAT-11 S1, S6-S9; FEAT-10 T-10.4)."""

import ast
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import engine
from app.modules.prescriptions.models import LEGAL_TRANSITIONS
from tests.prescriptions.conftest import Clinic, RxApi

_MIGRATION = next(
    Path(__file__).parents[2].glob("app/alembic/versions/44c34ed0d6b2_*.py")
)


def _raw(statement: str, params: dict[str, object]) -> None:
    with engine.begin() as conn:
        conn.execute(text(statement), params)


def _signed(rx: RxApi, clinic: Clinic) -> str:
    rx.approve(clinic)
    staged = rx.stage(clinic)
    assert rx.sign_raw(clinic.owner, staged["id"]).status_code == 200
    return str(staged["id"])


def test_the_trigger_and_the_service_share_one_state_machine() -> None:
    """The migration's literal transition list equals `LEGAL_TRANSITIONS` - one machine, two layers."""
    tree = ast.parse(_MIGRATION.read_text())
    literal = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "_PRESCRIPTION_TRANSITIONS"
    )
    pairs = set(ast.literal_eval(literal))
    expected = {(a, b) for a, targets in LEGAL_TRANSITIONS.items() for b in targets}
    assert pairs == expected


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("medicine_name", "Something else"),
        ("quantity", 99),
        ("repeats", 5),
        ("dose_instruction", "Double it"),
        ("date_of_service", "2026-06-02"),
        ("signed_by", None),
    ],
)
def test_a_signed_prescription_is_immutable(
    rx: RxApi, clinic: Clinic, column: str, value: object
) -> None:
    prescription_id = _signed(rx, clinic)
    with pytest.raises(DBAPIError, match="SIGNED_IS_IMMUTABLE"):
        _raw(
            f"UPDATE prescriptions SET {column} = :value WHERE id = :id",
            {"value": value, "id": uuid.UUID(prescription_id)},
        )


@pytest.mark.parametrize("target", ["DISPATCHED", "DRAFT", "REVERSED"])
def test_an_illegal_transition_is_refused_by_the_database(
    rx: RxApi, clinic: Clinic, target: str
) -> None:
    prescription_id = _signed(rx, clinic)
    with pytest.raises(DBAPIError, match="INVALID_STATE_TRANSITION"):
        _raw(
            "UPDATE prescriptions SET state = :state WHERE id = :id",
            {"state": target, "id": uuid.UUID(prescription_id)},
        )


def test_only_the_prescriber_of_record_can_be_the_signer(
    rx: RxApi, clinic: Clinic
) -> None:
    staged = rx.stage(clinic)
    with pytest.raises(DBAPIError, match="signer_is_prescriber"):
        _raw(
            "UPDATE prescriptions SET signed_by = :other WHERE id = :id",
            {"other": uuid.uuid4(), "id": uuid.UUID(staged["id"])},
        )


def test_a_queued_attempt_cannot_be_marked_dispatched_without_confirmation(
    rx: RxApi, clinic: Clinic
) -> None:
    """No path - not even a hand-written UPDATE - reports a send that was not confirmed."""
    prescription_id = _signed(rx, clinic)
    assert rx.dispatch_raw(clinic.owner, prescription_id).status_code == 202
    with pytest.raises(DBAPIError, match="dispatched_confirmed"):
        _raw(
            "UPDATE dispatch_attempts SET state = 'DISPATCHED' WHERE prescription_id = :id",
            {"id": uuid.UUID(prescription_id)},
        )
    with pytest.raises(DBAPIError, match="IDENTITY_IMMUTABLE"):
        _raw(
            "UPDATE dispatch_attempts SET idempotency_key = repeat('b', 64)"
            " WHERE prescription_id = :id",
            {"id": uuid.UUID(prescription_id)},
        )


def _as_app(statement: str, tenant_id: str) -> int | str:
    """Run as `clinos_app` with a tenant set; the row count, or the SQLSTATE that refused it."""
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE clinos_app"))
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id}
        )
        try:
            return conn.execute(text(statement)).rowcount
        except DBAPIError as error:
            return str(getattr(error.orig, "sqlstate", ""))


def test_history_is_append_only_and_nothing_is_hard_deleted(
    rx: RxApi, clinic: Clinic
) -> None:
    prescription_id = _signed(rx, clinic)
    tenant = str(clinic.owner.tenant_id)
    assert _as_app("UPDATE prescription_events SET reason = 'X'", tenant) == "42501"
    assert _as_app("DELETE FROM prescription_events", tenant) == "42501"
    assert _as_app("DELETE FROM prescriptions", tenant) == "42501"
    assert _as_app("DELETE FROM dispatch_attempts", tenant) == "42501"
    assert _as_app("TRUNCATE prescriptions", tenant) == "42501"
    assert rx.row(prescription_id)["state"] == "SIGNED"


def test_rls_scopes_every_table_and_an_unset_tenant_sees_nothing(
    rx: RxApi, clinic: Clinic
) -> None:
    _signed(rx, clinic)
    other = rx.clinic("Other Clinic")
    for table in ("prescriptions", "prescription_events", "step_up_grants"):
        assert _as_app(f"SELECT 1 FROM {table}", str(clinic.owner.tenant_id)) >= 1  # type: ignore[operator]
        assert _as_app(f"SELECT 1 FROM {table}", str(other.owner.tenant_id)) == 0
        assert _as_app(f"SELECT 1 FROM {table}", "") == 0
