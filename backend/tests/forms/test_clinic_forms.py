"""Clinic-made forms (docs3 Phase 6 feature 05, R6): build, version, retire, record, protect."""

import uuid
from typing import Any

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings
from app.core.db import engine
from tests.forms.conftest import Clinic, FormsApi, code
from tests.utils.care import relate
from tests.utils.rbac import ActorSession

API = settings.API_V1_STR

FOLLOW_UP: dict[str, Any] = {
    "title": "Follow-up check-in",
    "description": "Between consultations.",
    "fields": [
        {
            "id": "sleep",
            "label": "Sleep quality",
            "type": "SCALE",
            "scale_min": 0,
            "scale_max": 10,
            "required": True,
        },
        {
            "id": "side_effects",
            "label": "Side effects",
            "type": "CHOICE",
            "options": ["None", "Mild", "Severe"],
            "required": True,
        },
        {"id": "notes", "label": "Anything else", "type": "LONG_TEXT"},
        {"id": "driving", "label": "Driving while impaired?", "type": "YES_NO"},
        {"id": "next_review", "label": "Next review", "type": "DATE"},
        {"id": "pharmacy", "label": "Pharmacy used", "type": "TEXT"},
    ],
}
GOOD = {
    "sleep": 6,
    "side_effects": "Mild",
    "notes": "Dry mouth.",
    "driving": False,
    "next_review": "2026-12-20",
    "pharmacy": "Corner",
}


def _create(
    forms: FormsApi, actor: ActorSession, body: dict[str, Any] | None = None
) -> Any:
    return forms.client.post(
        f"{API}/clinic-forms", json=body or FOLLOW_UP, headers=actor.headers
    )


def _respond(
    forms: FormsApi,
    actor: ActorSession,
    patient: uuid.UUID,
    version_id: str,
    answers: dict[str, Any],
    **extra: Any,
) -> Any:
    return forms.client.post(
        f"{API}/patients/{patient}/clinic-form-responses",
        json={"form_version_id": version_id, "answers": answers, **extra},
        headers=actor.headers,
    )


def test_a_form_is_built_listed_and_filled_in(forms: FormsApi, clinic: Clinic) -> None:
    created = _create(forms, clinic.owner)
    assert created.status_code == 201, created.text
    form = created.json()
    assert (form["version"], form["status"], len(form["fields"])) == (1, "ACTIVE", 6)
    doctor = forms.add(clinic.owner, "DOCTOR")
    listed = forms.client.get(f"{API}/clinic-forms", headers=doctor.headers).json()
    assert [f["id"] for f in listed] == [form["id"]]

    saved = _respond(forms, clinic.owner, clinic.patient_id, form["version_id"], GOOD)
    assert saved.status_code == 201, saved.text
    assert saved.json()["answers"] == GOOD
    history = forms.history(clinic.owner, clinic.patient_id).json()
    [response] = history["clinic_responses"]
    assert (response["title"], response["version"], response["answers"]) == (
        "Follow-up check-in",
        1,
        GOOD,
    )
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT answers FROM clinic_form_responses WHERE id = :i"),
            {"i": response["id"]},
        ).scalar_one()
    assert b"Dry mouth" not in bytes(stored)


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({**GOOD, "sleep": None}, "Sleep quality is required"),
        ({**GOOD, "sleep": 11}, "Sleep quality: a whole number from 0 to 10"),
        ({**GOOD, "sleep": True}, "Sleep quality: a whole number"),
        (
            {**GOOD, "side_effects": "Unbearable"},
            "Side effects: choose one of the options",
        ),
        ({**GOOD, "driving": "no"}, "Driving while impaired?: yes or no"),
        ({**GOOD, "next_review": "20/12/2026"}, "Next review: a date"),
        ({**GOOD, "pharmacy": "x" * 501}, "Pharmacy used: text of at most 500"),
        ({**GOOD, "blood_type": "O"}, "Unknown field: blood_type"),
    ],
)
def test_answers_are_checked_per_field_and_the_refusal_names_the_field(
    forms: FormsApi, clinic: Clinic, answers: dict[str, Any], message: str
) -> None:
    version_id = _create(forms, clinic.owner).json()["version_id"]
    refused = _respond(forms, clinic.owner, clinic.patient_id, version_id, answers)
    assert (refused.status_code, code(refused)) == (422, "INVALID_ANSWERS")
    assert refused.json()["detail"]["message"].startswith(message)


@pytest.mark.parametrize(
    "fields",
    [
        [{"id": "a", "label": "A", "type": "CHOICE", "options": ["Only"]}],
        [{"id": "a", "label": "A", "type": "CHOICE", "options": ["X", "X"]}],
        [{"id": "a", "label": "A", "type": "SCALE", "scale_min": 5, "scale_max": 5}],
        [{"id": "a", "label": "A", "type": "TEXT", "options": ["X", "Y"]}],
        [
            {"id": "a", "label": "A", "type": "TEXT"},
            {"id": "a", "label": "B", "type": "TEXT"},
        ],
        [{"id": "Bad Id", "label": "A", "type": "TEXT"}],
        [{"id": "a", "label": "A", "type": "SIGNATURE"}],
        [],
    ],
)
def test_a_malformed_form_is_refused(
    forms: FormsApi, clinic: Clinic, fields: list[dict[str, Any]]
) -> None:
    assert (
        _create(forms, clinic.owner, {"title": "Broken", "fields": fields}).status_code
        == 422
    )


def test_a_new_version_makes_the_old_one_unfillable_and_keeps_old_answers_readable(
    forms: FormsApi, clinic: Clinic
) -> None:
    v1 = _create(forms, clinic.owner).json()
    _respond(forms, clinic.owner, clinic.patient_id, v1["version_id"], GOOD)
    revised = {
        **FOLLOW_UP,
        "title": "Follow-up check-in (revised)",
        "fields": FOLLOW_UP["fields"][:2],
    }
    v2 = forms.client.post(
        f"{API}/clinic-forms/{v1['id']}/versions",
        json=revised,
        headers=clinic.owner.headers,
    ).json()
    assert (v2["id"], v2["version"]) == (v1["id"], 2)
    stale = _respond(forms, clinic.owner, clinic.patient_id, v1["version_id"], GOOD)
    assert (stale.status_code, code(stale)) == (409, "FORM_VERSION_STALE")
    [old] = forms.history(clinic.owner, clinic.patient_id).json()["clinic_responses"]
    assert (old["version"], len(old["fields"]), old["answers"]["notes"]) == (
        1,
        6,
        "Dry mouth.",
    )


def test_a_retired_form_is_hidden_unfillable_and_uneditable(
    forms: FormsApi, clinic: Clinic
) -> None:
    form = _create(forms, clinic.owner).json()
    retired = forms.client.post(
        f"{API}/clinic-forms/{form['id']}/retire", headers=clinic.owner.headers
    )
    assert retired.json()["status"] == "RETIRED"
    assert (
        forms.client.get(f"{API}/clinic-forms", headers=clinic.owner.headers).json()
        == []
    )
    with_retired = forms.client.get(
        f"{API}/clinic-forms?include_retired=true", headers=clinic.owner.headers
    ).json()
    assert [f["status"] for f in with_retired] == ["RETIRED"]
    assert (
        code(_respond(forms, clinic.owner, clinic.patient_id, form["version_id"], GOOD))
        == "FORM_VERSION_STALE"
    )
    edit = forms.client.post(
        f"{API}/clinic-forms/{form['id']}/versions",
        json=FOLLOW_UP,
        headers=clinic.owner.headers,
    )
    assert (edit.status_code, code(edit)) == (409, "FORM_RETIRED")


def test_only_tenant_configure_builds_forms(forms: FormsApi, clinic: Clinic) -> None:
    doctor = forms.add(clinic.owner, "DOCTOR")
    assert _create(forms, doctor).status_code == 403
    assert (
        forms.client.get(
            f"{API}/clinic-forms?include_retired=true", headers=doctor.headers
        ).status_code
        == 403
    )
    denied = [
        e
        for e in forms.audit(clinic.tenant_id, "form.publish")
        if e["result"] == "DENIED"
    ]
    assert denied and denied[0]["reason"] == "PERMISSION_NOT_HELD"


def test_clinic_and_care_relationship_boundaries(
    forms: FormsApi, clinic: Clinic
) -> None:
    form = _create(forms, clinic.owner).json()
    stranger = forms.register()
    stranger_patient = forms.patient(stranger)
    assert (
        _respond(
            forms, stranger, clinic.patient_id, form["version_id"], GOOD
        ).status_code
        == 404
    )
    # Another clinic's form version cannot be used, even for the stranger's own patient.
    assert (
        code(_respond(forms, stranger, stranger_patient, form["version_id"], GOOD))
        == "FORM_NOT_FOUND"
    )
    assert (
        forms.client.post(
            f"{API}/clinic-forms/{form['id']}/retire", headers=stranger.headers
        ).status_code
        == 404
    )
    assert (
        forms.client.get(f"{API}/clinic-forms", headers=stranger.headers).json() == []
    )
    nurse = forms.add(clinic.owner, "NURSE")
    assert (
        _respond(forms, nurse, clinic.patient_id, form["version_id"], GOOD).status_code
        == 403
    )
    relate(
        forms.client,
        clinic.owner.headers,
        patient_id=clinic.patient_id,
        practitioner_id=nurse.user_id,
    )
    assert (
        _respond(forms, nurse, clinic.patient_id, form["version_id"], GOOD).status_code
        == 201
    )


def test_audit_carries_versions_and_patients_never_answers(
    forms: FormsApi, clinic: Clinic
) -> None:
    form = _create(forms, clinic.owner).json()
    _respond(forms, clinic.owner, clinic.patient_id, form["version_id"], GOOD)
    forms.client.post(
        f"{API}/clinic-forms/{form['id']}/retire", headers=clinic.owner.headers
    )
    [published] = forms.audit(clinic.tenant_id, "form.publish")
    assert published["payload"] == {"version": "1"}
    [created] = forms.audit(clinic.tenant_id, "form_response.create")
    assert created["payload"] == {"patient_id": str(clinic.patient_id)}
    assert len(forms.audit(clinic.tenant_id, "form.retire")) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE clinic_form_versions SET title = 'x'",
        "DELETE FROM clinic_form_versions",
        "UPDATE clinic_form_responses SET corrects_id = NULL",
        "DELETE FROM clinic_form_responses",
        "UPDATE clinic_forms SET created_by = NULL",
        "DELETE FROM clinic_forms",
    ],
)
def test_published_forms_and_responses_cannot_be_rewritten(statement: str) -> None:
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE clinos_app"))
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(uuid.uuid4())},
        )
        with pytest.raises(ProgrammingError) as refused:
            conn.execute(text(statement))
        assert isinstance(refused.value.orig, InsufficientPrivilege)
