"""The controls that live in the database: overlap exclusion, derived range, status guard, RLS, grants.

Raw SQL on purpose: these must hold for a caller that bypasses the service entirely.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.db import engine
from app.modules.appointments.models import LEGAL_TRANSITIONS
from tests.appointments.conftest import AppointmentsApi, Clinic

_INSERT = text(
    "INSERT INTO appointments (tenant_id, patient_id, practitioner_id, type, status, source,"
    " starts_at, ends_at, created_at, updated_at)"
    " VALUES (:tenant_id, :patient_id, :practitioner_id, :type, :status, 'STAFF',"
    " :starts_at, :ends_at, now(), now()) RETURNING id"
)


def _insert(clinic: Clinic, **overrides: object) -> uuid.UUID:
    params: dict[str, object] = {
        "tenant_id": clinic.tenant_id,
        "patient_id": clinic.patient_id,
        "practitioner_id": clinic.doctor.user_id,
        "type": "FOLLOW_UP",
        "status": "BOOKED",
        "starts_at": "2031-01-06T09:00:00+11:00",
        "ends_at": "2031-01-06T09:15:00+11:00",
        **overrides,
    }
    with engine.begin() as conn:
        return uuid.UUID(str(conn.execute(_INSERT, params).scalar_one()))


def test_the_exclusion_constraint_refuses_an_overlap_without_the_service(
    clinic: Clinic,
) -> None:
    _insert(clinic)
    with pytest.raises(IntegrityError) as refused:
        _insert(
            clinic,
            starts_at="2031-01-06T09:10:00+11:00",
            ends_at="2031-01-06T09:25:00+11:00",
        )
    assert refused.value.orig is not None
    assert refused.value.orig.diag.constraint_name == "no_overlapping_appointments"
    # Partial: a released booking does not hold the slot.
    _insert(clinic, status="CANCELLED")
    # The constraint is per practitioner and per tenant.
    _insert(clinic, practitioner_id=clinic.nurse.user_id, type="NURSE_TRIAGE")


def test_the_range_is_derived_and_the_duration_is_the_types(clinic: Clinic) -> None:
    appointment_id = _insert(clinic)
    with engine.connect() as conn:
        derived = conn.execute(
            text(
                "SELECT during = tstzrange(starts_at, ends_at, '[)') FROM appointments"
                " WHERE id = :id"
            ),
            {"id": appointment_id},
        ).scalar_one()
    assert derived is True
    with pytest.raises(IntegrityError):
        _insert(
            clinic,
            starts_at="2031-01-07T09:00:00+11:00",
            ends_at="2031-01-07T10:00:00+11:00",
        )


def test_the_trigger_holds_the_status_machine_and_the_booking_immutable(
    clinic: Clinic,
) -> None:
    appointment_id = _insert(clinic, status="COMPLETED")
    for statement in (
        "UPDATE appointments SET status = 'BOOKED' WHERE id = :id",
        "UPDATE appointments SET starts_at = starts_at + interval '1 hour',"
        " ends_at = ends_at + interval '1 hour' WHERE id = :id",
    ):
        with pytest.raises(DBAPIError) as refused:
            with engine.begin() as conn:
                conn.execute(text(statement), {"id": appointment_id})
        assert getattr(refused.value.orig, "sqlstate", "") == "23514"


def test_the_trigger_and_the_service_agree_on_the_machine(clinic: Clinic) -> None:
    for start, targets in LEGAL_TRANSITIONS.items():
        for target in (
            "BOOKED",
            "CONFIRMED",
            "ARRIVED",
            "COMPLETED",
            "CANCELLED",
            "NO_SHOW",
        ):
            if target == start:
                continue
            appointment_id = _insert(clinic, status=start)
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text("UPDATE appointments SET status = :s WHERE id = :id"),
                        {"s": target, "id": appointment_id},
                    )
                allowed = True
            except DBAPIError:
                allowed = False
            assert allowed == (target in targets), (start, target)
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM appointments WHERE id = :id"),
                    {"id": appointment_id},
                )


def _as_app(tenant_id: str, statement: str, params: dict[str, object]) -> object:
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE clinos_app"))
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        return conn.execute(text(statement), params).scalar_one()


def test_rls_isolates_appointments_and_fails_closed(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    other = api.clinic()
    appointment_id = _insert(clinic)
    count = "SELECT count(*) FROM appointments WHERE id = :id"
    assert _as_app(str(clinic.tenant_id), count, {"id": appointment_id}) == 1
    assert _as_app(str(other.tenant_id), count, {"id": appointment_id}) == 0
    assert _as_app("", count, {"id": appointment_id}) == 0
    assert _as_app("", "SELECT count(*) FROM appointment_settings", {}) == 0


def test_the_app_role_cannot_delete_a_booking_or_edit_the_settings(
    clinic: Clinic,
) -> None:
    appointment_id = _insert(clinic)
    for statement in (
        "DELETE FROM appointments WHERE id = :id RETURNING 1",
        "INSERT INTO appointment_settings (tenant_id, opens_at, closes_at, working_days,"
        " created_at, updated_at) VALUES (:tenant, '08:00', '18:00', '{1}', now(), now())"
        " RETURNING 1",
    ):
        with pytest.raises(DBAPIError) as refused:
            _as_app(
                str(clinic.tenant_id),
                statement,
                {"id": appointment_id, "tenant": clinic.tenant_id},
            )
        assert getattr(refused.value.orig, "sqlstate", "") == "42501"
