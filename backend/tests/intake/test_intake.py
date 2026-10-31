"""Patient intake (docs3 feature 03; Platform Manual §5.1, §5.4, §8.1, §12.3). Denial paths first.

The public application rides on the booking (`POST /public/{slug}/bookings` with `application`), so the
patient, the held booking and the application commit together or not at all.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.modules.intake.consents import CURRENT_CONSENTS
from tests.appointments.conftest import API, AppointmentsApi, Clinic, code
from tests.observability.log_sinks import capture_logs

ANSWER_SENTINEL = "QZQZ-unusual-side-effect"


def _consents() -> list[dict[str, str]]:
    return [{"kind": k, "version": d.version} for k, d in CURRENT_CONSENTS.items()]


def _application(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "sex_at_birth": "FEMALE",
        "address_line": "14 Vulture St",
        "suburb": "West End",
        "state": "QLD",
        "postcode": "4101",
        "primary_condition": "CHRONIC_PAIN",
        "other_conditions": ["Insomnia"],
        "current_medicines": "Paracetamol",
        "safety": {
            "psychosis_history": False,
            "pregnant_or_breastfeeding": False,
            "heart_condition": True,
            "substance_dependence": False,
        },
        "tried_conventional": True,
        "conventional_detail": "Physio for a year",
        "cannabis_used_before": False,
        "cannabis_forms": [],
        "cannabis_duration": None,
        "side_effects": ANSWER_SENTINEL,
        "what_helped": "",
        "consents": _consents(),
        "own_pharmacy": {
            "name": "Corner Pharmacy",
            "suburb": "West End",
            "address": "1 Boundary St, West End QLD 4101",
            "email": "orders@corner.example.com",
            "phone": "07 3000 0000",
        },
        "declaration_name": "Nora Quinn",
    }
    body.update(overrides)
    return body


def _apply(
    api: AppointmentsApi, clinic: Clinic, *, email: str | None = None, **overrides: Any
) -> Any:
    slot = api.slots(clinic.slug, "NURSE_TRIAGE").json()[0]
    return api.public_book(
        clinic.slug,
        slot,
        email=email or f"nora-{uuid.uuid4().hex[:6]}@example.com",
        application=_application(**overrides),
    )


def _count(table: str, tenant_id: uuid.UUID) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                {"t": tenant_id},
            ).scalar_one()
        )


def _queue(
    api: AppointmentsApi, clinic: Clinic, status: str = "SUBMITTED"
) -> list[Any]:
    response = api.client.get(
        f"{API}/intake-applications",
        params={"status": status},
        headers=clinic.owner.headers,
    )
    assert response.status_code == 200, response.text
    return list(response.json())


# -- the public application: refusals leave nothing behind -------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"declaration_name": "Someone Else"}, "DECLARATION_MISMATCH"),
        (
            {"consents": [{"kind": "PRIVACY", "version": "2000-01"}]},
            "CONSENT_VERSION_STALE",
        ),
        (
            {"pharmacy_id": str(uuid.uuid4()), "own_pharmacy": None},
            "PHARMACY_NOT_FOUND",
        ),
    ],
)
def test_a_refused_application_stores_nothing(
    api: AppointmentsApi, clinic: Clinic, overrides: dict[str, Any], expected: str
) -> None:
    before = {t: _count(t, clinic.tenant_id) for t in ("patients", "appointments")}
    response = _apply(api, clinic, **overrides)
    assert response.status_code == 422, response.text
    assert code(response) == expected
    for table, count in before.items():
        assert _count(table, clinic.tenant_id) == count
    assert _count("intake_applications", clinic.tenant_id) == 0


def test_an_application_must_choose_exactly_one_pharmacy(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    assert _apply(api, clinic, own_pharmacy=None).status_code == 422


def test_another_clinics_partner_pharmacy_is_refused(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    other = api.clinic(name="Other Intake Clinic")
    partner = api.client.post(
        f"{API}/pharmacies",
        json={"name": "Elsewhere Chemist", "suburb": "Fitzroy", "is_partner": True},
        headers=other.owner.headers,
    ).json()
    response = _apply(api, clinic, pharmacy_id=partner["id"], own_pharmacy=None)
    assert code(response) == "PHARMACY_NOT_FOUND"


def test_the_form_offers_current_consents_and_only_partner_pharmacies(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    for name, partner in (("Partner Chemist", True), ("Private Chemist", False)):
        created = api.client.post(
            f"{API}/pharmacies",
            json={"name": name, "suburb": "West End", "is_partner": partner},
            headers=clinic.owner.headers,
        )
        assert created.status_code == 201, created.text
    form = api.client.get(f"{API}/public/{clinic.slug}/intake-form").json()
    assert {(c["kind"], c["version"]) for c in form["consents"]} == {
        (k, d.version) for k, d in CURRENT_CONSENTS.items()
    }
    assert [p["name"] for p in form["partner_pharmacies"]] == ["Partner Chemist"]
    assert set(form["partner_pharmacies"][0]) == {"id", "name", "suburb"}
    assert api.client.get(f"{API}/public/no-such-clinic/intake-form").status_code == 404


def test_an_application_holds_a_booking_and_waits_in_the_queue(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    with capture_logs(envelope_filter=False) as sink:
        response = _apply(api, clinic)
    assert response.status_code == 201, response.text
    assert ANSWER_SENTINEL not in sink.raw

    (card,) = _queue(api, clinic)
    assert card["patient_name"] == "Nora Quinn"
    assert card["matched_existing"] is False
    assert set(card["flags"]) == {"HEART_CONDITION", "CANNABIS_NAIVE"}
    assert card["appointment_starts_at"] is not None
    assert "answers" not in card
    patient = api.client.get(
        f"{API}/patients/{card['patient_id']}", headers=clinic.owner.headers
    ).json()
    assert patient["status"] == "REVIEW"
    # The answers are never audited.
    for event in api.audit(clinic.tenant_id, "intake.application_submit"):
        assert ANSWER_SENTINEL not in str(event)


# -- the queue ----------------------------------------------------------------------------------


def test_the_queue_needs_patient_read_and_decisions_need_patient_create(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    _apply(api, clinic)
    (card,) = _queue(api, clinic)
    nobody = api.staff(clinic.owner, None)
    assert (
        api.client.get(f"{API}/intake-applications", headers=nobody.headers).status_code
        == 403
    )
    pharmacy = api.staff(clinic.owner, "PHARMACY")
    for action in ("accept", "reject"):
        response = api.client.post(
            f"{API}/intake-applications/{card['id']}/{action}",
            json={"reason_code": "OTHER"} if action == "reject" else None,
            headers=pharmacy.headers,
        )
        assert response.status_code == 403, action
    assert _queue(api, clinic)[0]["status"] == "SUBMITTED"


def test_another_clinics_application_is_not_found(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    _apply(api, clinic)
    (card,) = _queue(api, clinic)
    other = api.clinic(name="Other Queue Clinic")
    for method, path in (
        ("GET", f"{API}/intake-applications/{card['id']}"),
        ("POST", f"{API}/intake-applications/{card['id']}/accept"),
    ):
        assert (
            api.client.request(method, path, headers=other.owner.headers).status_code
            == 404
        ), path
    assert _queue(api, other) == []


def test_accepting_files_consents_pharmacy_and_details(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    _apply(api, clinic)
    (card,) = _queue(api, clinic)
    detail = api.client.get(
        f"{API}/intake-applications/{card['id']}", headers=clinic.owner.headers
    ).json()
    assert detail["answers"]["primary_condition"] == "CHRONIC_PAIN"
    assert detail["pharmacy"]["kind"] == "OWN"

    accepted = api.client.post(
        f"{API}/intake-applications/{card['id']}/accept", headers=clinic.owner.headers
    )
    assert accepted.status_code == 200, accepted.text
    again = api.client.post(
        f"{API}/intake-applications/{card['id']}/accept", headers=clinic.owner.headers
    )
    assert again.status_code == 409

    patient = api.client.get(
        f"{API}/patients/{card['patient_id']}", headers=clinic.owner.headers
    ).json()
    assert patient["status"] == "CURRENT"
    assert (patient["sex_at_birth"], patient["postcode"]) == ("FEMALE", "4101")
    pharmacies = api.client.get(
        f"{API}/pharmacies", headers=clinic.owner.headers
    ).json()
    (own,) = [p for p in pharmacies if p["name"] == "Corner Pharmacy"]
    assert patient["preferred_pharmacy_id"] == own["id"]
    consents = api.client.get(
        f"{API}/patients/{card['patient_id']}/consents", headers=clinic.owner.headers
    ).json()
    assert {(c["kind"], c["current"]) for c in consents} == {
        ("PRIVACY", True),
        ("TELEHEALTH", True),
        ("TREATMENT", True),
    }
    assert _queue(api, clinic) == []
    assert [c["id"] for c in _queue(api, clinic, "ACCEPTED")] == [card["id"]]


def test_accepting_never_overwrites_a_matched_patients_details(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    email = "nora.existing@example.com"
    existing = api.client.post(
        f"{API}/patients",
        json={
            "given_name": "Nora",
            "family_name": "Quinn",
            "date_of_birth": "1990-03-21",
            "email": email,
            "postcode": "2000",
        },
        headers=clinic.owner.headers,
    ).json()
    _apply(api, clinic, email=email)
    (card,) = _queue(api, clinic)
    assert card["patient_id"] == existing["id"]
    assert card["matched_existing"] is True
    api.client.post(
        f"{API}/intake-applications/{card['id']}/accept", headers=clinic.owner.headers
    )
    patient = api.client.get(
        f"{API}/patients/{existing['id']}", headers=clinic.owner.headers
    ).json()
    assert patient["postcode"] == "2000"


def test_rejecting_cancels_the_booking_and_archives_the_new_record(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    _apply(api, clinic)
    (card,) = _queue(api, clinic)
    assert (
        api.client.post(
            f"{API}/intake-applications/{card['id']}/reject",
            json={"reason_code": "MADE_UP"},
            headers=clinic.owner.headers,
        ).status_code
        == 422
    )
    rejected = api.client.post(
        f"{API}/intake-applications/{card['id']}/reject",
        json={"reason_code": "NEEDS_IN_PERSON_REVIEW", "note": "Seen in clinic first"},
        headers=clinic.owner.headers,
    )
    assert rejected.status_code == 204, rejected.text
    patient = api.client.get(
        f"{API}/patients/{card['patient_id']}", headers=clinic.owner.headers
    ).json()
    assert patient["status"] == "ARCHIVED"
    bookings = api.client.get(
        f"{API}/patients/{card['patient_id']}/appointments",
        headers=clinic.owner.headers,
    ).json()
    assert [b["status"] for b in bookings] == ["CANCELLED"]
    assert (
        api.client.post(
            f"{API}/intake-applications/{card['id']}/reject",
            json={"reason_code": "OTHER"},
            headers=clinic.owner.headers,
        ).status_code
        == 409
    )


# -- on the patient record ----------------------------------------------------------------------


def test_the_briefing_follows_the_treating_relationship(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    _apply(api, clinic)
    (card,) = _queue(api, clinic)
    url = f"{API}/patients/{card['patient_id']}/intake-briefing"
    # A doctor's clinical read is relationship-bound (D-007): no care relationship, no briefing.
    assert api.client.get(url, headers=clinic.doctor.headers).status_code == 403
    owner_view = api.client.get(url, headers=clinic.owner.headers)
    assert owner_view.status_code == 200, owner_view.text
    briefing = owner_view.json()
    assert briefing["primary_condition"] == "CHRONIC_PAIN"
    assert briefing["safety_flags"] == ["HEART_CONDITION"]
    assert briefing["side_effects"] == ANSWER_SENTINEL
    none = api.client.get(
        f"{API}/patients/{clinic.patient_id}/intake-briefing",
        headers=clinic.owner.headers,
    )
    assert none.status_code == 200 and none.json() is None


def test_a_patients_pharmacy_must_be_from_the_clinics_directory(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    other = api.clinic(name="Other Pharmacy Clinic")
    theirs = api.client.post(
        f"{API}/pharmacies",
        json={"name": "Theirs", "suburb": "Carlton"},
        headers=other.owner.headers,
    ).json()
    url = f"{API}/patients/{clinic.patient_id}/pharmacy"
    assert (
        api.client.post(
            url, json={"pharmacy_id": theirs["id"]}, headers=clinic.owner.headers
        ).status_code
        == 422
    )
    mine = api.client.post(
        f"{API}/pharmacies",
        json={"name": "Mine", "suburb": "West End"},
        headers=clinic.owner.headers,
    ).json()
    changed = api.client.post(
        url, json={"pharmacy_id": mine["id"]}, headers=clinic.owner.headers
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["preferred_pharmacy_id"] == mine["id"]
