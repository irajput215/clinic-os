"""docs3 feature 01: the setup checklist and the practice settings. Denials first."""

from typing import Any

from app.core.config import settings
from tests.prescriptions.conftest import Clinic, RxApi

API = settings.API_V1_STR
SETUP = f"{API}/tenants/current/setup"
SETTINGS = f"{API}/tenants/current/settings"


def _steps(rx: RxApi, clinic: Clinic) -> dict[str, str]:
    response = rx.client.get(SETUP, headers=clinic.owner.headers)
    assert response.status_code == 200, response.text
    return {step["key"]: step["status"] for step in response.json()["steps"]}


def test_only_a_configurer_sees_the_checklist_or_changes_settings(
    rx: RxApi, clinic: Clinic
) -> None:
    nurse = rx.member(clinic, "NURSE")
    assert rx.client.get(SETUP, headers=nurse.headers).status_code == 403
    assert rx.client.get(SETUP, headers=clinic.verifier.headers).status_code == 403
    assert rx.client.get(SETTINGS, headers=nurse.headers).status_code == 403
    refused = rx.client.patch(
        SETTINGS,
        json={"draft_staging_roles": ["NURSE"], "adult_retention_years": 7},
        headers=clinic.verifier.headers,
    )
    assert refused.status_code == 403


def test_settings_refuse_what_the_practice_may_not_choose(
    rx: RxApi, clinic: Clinic
) -> None:
    for body in (
        {"draft_staging_roles": ["NURSE"], "adult_retention_years": 6},
        {"draft_staging_roles": ["DOCTOR"], "adult_retention_years": 7},
        {"draft_staging_roles": [], "adult_retention_years": 7},
        {"draft_staging_roles": ["NURSE", "PHARMACY"], "adult_retention_years": 7},
        {
            "draft_staging_roles": ["NURSE"],
            "adult_retention_years": 7,
            "tenant_id": str(clinic.owner.tenant_id),
        },
    ):
        response = rx.client.patch(SETTINGS, json=body, headers=clinic.owner.headers)
        assert response.status_code == 422, body


def test_settings_default_then_save_and_audit(rx: RxApi, clinic: Clinic) -> None:
    defaults = rx.client.get(SETTINGS, headers=clinic.owner.headers).json()
    assert defaults == {
        "draft_staging_roles": ["NURSE"],
        "adult_retention_years": 7,
        "updated_at": None,
    }
    saved = rx.client.patch(
        SETTINGS,
        json={"draft_staging_roles": ["DOCTOR", "NURSE"], "adult_retention_years": 10},
        headers=clinic.owner.headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft_staging_roles"] == ["NURSE", "DOCTOR"]
    assert saved.json()["adult_retention_years"] == 10
    assert saved.json()["updated_at"] is not None
    again = rx.client.patch(
        SETTINGS,
        json={"draft_staging_roles": ["NURSE", "DOCTOR"], "adult_retention_years": 12},
        headers=clinic.owner.headers,
    )
    assert again.json()["adult_retention_years"] == 12
    assert clinic.owner.tenant_id is not None
    events: list[dict[str, Any]] = rx.audit(
        clinic.owner.tenant_id, "tenant.config_changed"
    )
    assert [e["payload"]["changed_fields"] for e in events] == [
        ["draft_staging_roles", "adult_retention_years"],
        ["adult_retention_years"],
    ]


def test_every_step_is_derived_from_the_clinic(rx: RxApi) -> None:
    clinic = rx.clinic("Setup Clinic", ready=False)
    steps = _steps(rx, clinic)
    assert steps == {
        "clinic_name": "done",
        "hours": "todo",
        # The fixture adds a second doctor, so the team is invited.
        "team_invited": "done",
        "prescriber_ready": "todo",
        "workflow": "todo",
        "consents": "done",
        "permissions_reviewed": "optional",
        "booking_page": "optional",
        "integrations": "informational",
    }
    body = rx.client.get(SETUP, headers=clinic.owner.headers).json()
    assert (body["required_done"], body["required_total"], body["ready"]) == (
        3,
        6,
        False,
    )

    rx.make_ready(clinic.owner, clinic.verifier)
    rx.client.patch(
        SETTINGS,
        json={"draft_staging_roles": ["NURSE"], "adult_retention_years": 7},
        headers=clinic.owner.headers,
    )
    hours = rx.client.put(
        f"{API}/appointment-settings",
        json={
            "slot_minutes": 30,
            "hours": [
                {
                    "weekday": d,
                    "opens_at": "09:00" if d < 6 else None,
                    "closes_at": "17:00" if d < 6 else None,
                }
                for d in range(1, 8)
            ],
        },
        headers=clinic.owner.headers,
    )
    assert hours.status_code == 200, hours.text
    body = rx.client.get(SETUP, headers=clinic.owner.headers).json()
    assert body["ready"] is True, body
    assert (body["required_done"], body["required_total"]) == (6, 6)
