"""The point-in-time match: the grain, the consultation date, and D-006's boundary.

F11-F14, R10, T2-27 and T2-28. One function decides the boundary —
`service.within_validity_window` — and the first test in this file is that function on its own,
because the Clinical Safety Officer's ruling has to land in one place and nowhere else.
"""

from datetime import date, timedelta

from app.modules.tga_approvals import service
from app.modules.tga_approvals.service import MatchReason, within_validity_window
from tests.tga.conftest import TenantWithPatient, TgaApi


def test_the_boundary_is_half_open_and_lives_in_one_function() -> None:
    """D-006 §2: `valid_from <= date_of_service < valid_to`.

    The last day of the window is *outside* it. That is the interim fail-safe position, and this test
    is the tripwire for the day the Clinical Safety Officer rules the other way: exactly one
    assertion changes, and the change cannot be made anywhere but here.
    """
    valid_from = date(2026, 1, 1)
    valid_to = date(2026, 7, 1)

    assert within_validity_window(
        valid_from=valid_from, valid_to=valid_to, date_of_service=valid_from
    )
    assert within_validity_window(
        valid_from=valid_from,
        valid_to=valid_to,
        date_of_service=valid_to - timedelta(days=1),
    )
    assert not within_validity_window(
        valid_from=valid_from, valid_to=valid_to, date_of_service=valid_to
    )
    assert not within_validity_window(
        valid_from=valid_from,
        valid_to=valid_to,
        date_of_service=valid_from - timedelta(days=1),
    )
    assert service.evaluated_timezone() == "Australia/Sydney"


def _active_approval(
    api: TgaApi, clinic: TenantWithPatient, *, valid_from: str, valid_to: str, reference: str
) -> dict[str, object]:
    verifier = api.second_clinician(owner=clinic.owner)
    approval = api.create(
        clinic.owner,
        clinic.patient_id,
        approval_reference=reference,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    activated = api.activate(clinic.owner, approval, verifier=verifier)
    assert activated.status_code == 200, activated.text
    return approval


def test_a_live_approval_at_the_grain_allows_the_service_date(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F11: all four grain dimensions match at `date_of_service`."""
    _active_approval(
        api,
        clinic,
        valid_from="2026-01-01",
        valid_to="2026-07-01",
        reference="TGA-2026-000201",
    )
    response = api.match(clinic.owner, clinic.patient_id, date_of_service="2026-06-01")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matched"] is True
    assert body["reason_code"] is None
    assert body["state"] == "ACTIVE"
    assert body["date_of_service"] == "2026-06-01"
    assert body["evaluated_timezone"] == "Australia/Sydney"
    assert body["validity_interval"] == {
        "valid_from": "2026-01-01",
        "valid_to": "2026-07-01",
        "bounds": "[)",
    }
    # A match is audited, so a dispense can be reconstructed (D-006 §2's last bullet).
    events = api.audit_events(
        tenant_id=clinic.owner.tenant_id, action="tga_approval.match"
    )
    assert len(events) == 1


def test_the_two_dates_around_the_boundary_decide_it(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F14: the day before `valid_to` allows; `valid_to` itself blocks with `TGA_APPROVAL_EXPIRED`.

    The gate is never asked "is it still valid *now*" — it is asked about the consultation date, so a
    late expiry sweep cannot change the answer for a service already delivered.
    """
    _active_approval(
        api,
        clinic,
        valid_from="2026-01-01",
        valid_to="2026-07-01",
        reference="TGA-2026-000202",
    )
    inside = api.match(clinic.owner, clinic.patient_id, date_of_service="2026-06-30")
    assert inside.json()["matched"] is True

    boundary = api.match(clinic.owner, clinic.patient_id, date_of_service="2026-07-01")
    assert boundary.status_code == 200, boundary.text
    assert boundary.json()["matched"] is False
    assert boundary.json()["reason_code"] == MatchReason.EXPIRED.value

    before = api.match(clinic.owner, clinic.patient_id, date_of_service="2025-12-31")
    assert before.json()["reason_code"] == MatchReason.NOT_YET_EFFECTIVE.value


def test_no_row_at_the_grain_is_not_found(api: TgaApi, clinic: TenantWithPatient) -> None:
    """The negative matrix's first row: no approval for the patient at all."""
    response = api.match(clinic.owner, clinic.patient_id)
    assert response.status_code == 200, response.text
    assert response.json()["matched"] is False
    assert response.json()["reason_code"] == MatchReason.NOT_FOUND.value
    assert response.json()["approval_id"] is None


def test_a_category_or_dosage_form_mismatch_names_the_dimension(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F12, T2-28: *"wrong category"* and *"wrong dosage form"* are different clinical actions."""
    _active_approval(
        api,
        clinic,
        valid_from="2026-01-01",
        valid_to="2026-07-01",
        reference="TGA-2026-000203",
    )
    wrong_category = api.match(
        clinic.owner, clinic.patient_id, tga_category="CATEGORY_5"
    )
    assert wrong_category.json()["reason_code"] == MatchReason.CATEGORY_MISMATCH.value

    wrong_form = api.match(clinic.owner, clinic.patient_id, dosage_form="INHALATION")
    assert wrong_form.json()["reason_code"] == MatchReason.DOSAGE_FORM_MISMATCH.value


def test_every_non_active_state_blocks_with_its_own_reason(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F13, T2-28: `PENDING`, `REVOKED`, `SUPERSEDED`, `REJECTED` and `EXPIRED` each have a code."""
    assert clinic.owner.tenant_id is not None
    expected = {
        "PENDING": MatchReason.PENDING_VERIFICATION,
        "REVOKED": MatchReason.REVOKED,
        "SUPERSEDED": MatchReason.SUPERSEDED,
        "REJECTED": MatchReason.REJECTED,
        "EXPIRED": MatchReason.EXPIRED,
    }
    for index, (state, reason) in enumerate(expected.items()):
        patient = api.create_patient(
            clinic.owner, family_name=f"Synthetic{index}"
        )
        api.insert_approval(
            tenant_id=clinic.owner.tenant_id,
            patient_id=patient,
            state=state,
            approval_reference=f"TGA-RAW-0003{index:02d}",
            valid_from="2026-01-01",
            valid_to="2026-07-01",
            revoked_reason_code="CLINICAL_ERROR" if state == "REVOKED" else None,
            superseded_by_id=api.insert_approval(
                tenant_id=clinic.owner.tenant_id,
                patient_id=patient,
                state="ACTIVE",
                approval_reference=f"TGA-RAW-0004{index:02d}",
                valid_from="2027-01-01",
                valid_to="2027-07-01",
            )
            if state == "SUPERSEDED"
            else None,
        )
        response = api.match(clinic.owner, patient, date_of_service="2026-06-01")
        assert response.json()["matched"] is False, state
        assert response.json()["reason_code"] == reason.value, state


def test_the_exclusion_constraint_is_what_makes_the_answer_unambiguous(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """R10/R11: exactly one `ACTIVE` row can exist for an overlapping window, so "the" answer is one.

    Two adjacent (non-overlapping) grants at the same grain are both legal, and the match must pick
    the one whose window contains the service date rather than the first row it finds.
    """
    assert clinic.owner.tenant_id is not None
    verifier = api.second_clinician(owner=clinic.owner)
    first = api.create(
        clinic.owner,
        clinic.patient_id,
        approval_reference="TGA-2026-000301",
        valid_from="2026-01-01",
        valid_to="2026-07-01",
    )
    assert api.activate(clinic.owner, first, verifier=verifier).status_code == 200
    second = api.create(
        clinic.owner,
        clinic.patient_id,
        approval_reference="TGA-2026-000302",
        valid_from="2026-07-01",
        valid_to="2026-12-01",
    )
    assert api.activate(clinic.owner, second, verifier=verifier).status_code == 200

    in_first = api.match(clinic.owner, clinic.patient_id, date_of_service="2026-03-01")
    assert in_first.json()["approval_id"] == first["id"]
    in_second = api.match(clinic.owner, clinic.patient_id, date_of_service="2026-09-01")
    assert in_second.json()["approval_id"] == second["id"]
