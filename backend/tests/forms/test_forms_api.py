"""Questionnaire routes: record, history, safety flags, access and audit (Phase 6 feature 05)."""

import uuid

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings
from app.core.db import engine
from tests.forms.conftest import Clinic, FormsApi, code
from tests.utils.care import relate

API = settings.API_V1_STR


def test_the_catalogue_lists_three_instruments_and_the_actions(
    forms: FormsApi, clinic: Clinic
) -> None:
    body = forms.client.get(
        f"{API}/forms/instruments", headers=clinic.owner.headers
    ).json()
    assert [i["code"] for i in body["instruments"]] == ["PHQ9", "GAD7", "K10"]
    assert len(body["instruments"][0]["items"]) == 9
    assert {a["code"] for a in body["acknowledge_actions"]} >= {"SAFETY_PLAN_AGREED"}


def test_a_response_is_scored_stored_and_listed(
    forms: FormsApi, clinic: Clinic
) -> None:
    response = forms.record(
        clinic.owner,
        clinic.patient_id,
        answers=[2, 2, 2, 2, 2, 0, 0, 0, 0],
        difficulty=1,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["total_score"], body["band"], body["band_label"]) == (
        10,
        "MODERATE",
        "Moderate",
    )
    assert body["flags"] == [] and body["difficulty"] == 1
    history = forms.history(clinic.owner, clinic.patient_id).json()
    assert [r["id"] for r in history["responses"]] == [body["id"]]
    assert history["responses"][0]["answers"] == [2, 2, 2, 2, 2, 0, 0, 0, 0]
    assert history["open_flags"] == []


def test_answers_are_encrypted_at_rest(forms: FormsApi, clinic: Clinic) -> None:
    rid = forms.record(clinic.owner, clinic.patient_id, answers=[3] * 9).json()["id"]
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT answers FROM form_responses WHERE id = :i"), {"i": rid}
        ).scalar_one()
    assert b"answers" not in bytes(stored) and b"[3, 3" not in bytes(stored)


def test_item_9_raises_a_flag_in_the_same_transaction_and_it_needs_an_action(
    forms: FormsApi, clinic: Clinic
) -> None:
    body = forms.record(clinic.owner, clinic.patient_id, answers=[0] * 8 + [2]).json()
    [flag] = body["flags"]
    assert (flag["rule_code"], flag["status"]) == ("PHQ9_ITEM9_POSITIVE", "OPEN")
    assert [
        f["id"]
        for f in forms.history(clinic.owner, clinic.patient_id).json()["open_flags"]
    ] == [flag["id"]]

    assert forms.acknowledge(clinic.owner, flag["id"], "free text!").status_code == 422
    assert (
        code(forms.acknowledge(clinic.owner, flag["id"], "NOT_A_LISTED_ACTION"))
        == "UNKNOWN_ACTION"
    )
    done = forms.acknowledge(clinic.owner, flag["id"], "SAFETY_PLAN_AGREED")
    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["action_code"]) == (
        "ACKNOWLEDGED",
        "SAFETY_PLAN_AGREED",
    )
    again = forms.acknowledge(clinic.owner, flag["id"])
    assert (again.status_code, code(again)) == (409, "FLAG_ALREADY_ACKNOWLEDGED")
    assert forms.history(clinic.owner, clinic.patient_id).json()["open_flags"] == []


def test_audit_carries_the_patient_and_nothing_clinical(
    forms: FormsApi, clinic: Clinic
) -> None:
    flag_id = forms.record(
        clinic.owner, clinic.patient_id, answers=[0] * 8 + [3]
    ).json()["flags"][0]["id"]
    forms.acknowledge(clinic.owner, flag_id)
    forms.history(clinic.owner, clinic.patient_id)
    for action in (
        "form_response.create",
        "safety_flag.raise",
        "safety_flag.acknowledge",
        "form_response.read",
    ):
        [event] = forms.audit(clinic.tenant_id, action)
        assert event["result"] == "SUCCESS"
        assert event["payload"]["patient_id"] == str(clinic.patient_id)
        flat = str(event)
        for clinical in ("PHQ9", "MODERATE", "SEVERE", "ITEM9", "SAFETY_PLAN"):
            assert clinical not in flat, (action, clinical)


def test_a_correction_is_a_new_response_and_the_original_stays(
    forms: FormsApi, clinic: Clinic
) -> None:
    first = forms.record(clinic.owner, clinic.patient_id, answers=[1] * 9).json()
    second = forms.record(
        clinic.owner, clinic.patient_id, answers=[0] * 9, corrects_id=first["id"]
    ).json()
    assert second["corrects_id"] == first["id"]
    history = {
        r["id"]: r
        for r in forms.history(clinic.owner, clinic.patient_id).json()["responses"]
    }
    assert history[first["id"]]["corrected_by_id"] == second["id"]
    other = forms.record(
        clinic.owner,
        clinic.patient_id,
        instrument="GAD7",
        answers=[0] * 7,
        corrects_id=first["id"],
    )
    assert code(other) == "CORRECTED_RESPONSE_NOT_FOUND"


def test_invalid_stale_and_overreaching_bodies_are_refused(
    forms: FormsApi, clinic: Clinic
) -> None:
    assert (
        code(forms.record(clinic.owner, clinic.patient_id, answers=[0] * 8))
        == "INVALID_ANSWERS"
    )
    assert (
        code(forms.record(clinic.owner, clinic.patient_id, answers=[9] * 9))
        == "INVALID_ANSWERS"
    )
    assert (
        code(forms.record(clinic.owner, clinic.patient_id, instrument_version="0"))
        == "INSTRUMENT_VERSION_STALE"
    )
    for extra in (
        {"total_score": 0},
        {"band": "MINIMAL"},
        {"tenant_id": str(uuid.uuid4())},
        {"entered_by": str(uuid.uuid4())},
    ):
        assert forms.record(clinic.owner, clinic.patient_id, **extra).status_code == 422
    assert (
        forms.record(clinic.owner, clinic.patient_id, instrument="BDI").status_code
        == 422
    )


def test_another_clinic_gets_404_for_every_route(
    forms: FormsApi, clinic: Clinic
) -> None:
    flag_id = forms.record(
        clinic.owner, clinic.patient_id, answers=[0] * 8 + [1]
    ).json()["flags"][0]["id"]
    stranger = forms.register()
    assert forms.history(stranger, clinic.patient_id).status_code == 404
    assert forms.record(stranger, clinic.patient_id).status_code == 404
    assert forms.acknowledge(stranger, flag_id).status_code == 404


def test_a_nurse_needs_a_care_relationship(forms: FormsApi, clinic: Clinic) -> None:
    nurse = forms.add(clinic.owner, "NURSE")
    refused = forms.record(nurse, clinic.patient_id)
    assert (refused.status_code, code(refused)) == (
        403,
        "AUTHZ_CARE_RELATIONSHIP_DENIED",
    )
    assert forms.history(nurse, clinic.patient_id).status_code == 403
    denied = [
        e
        for e in forms.audit(clinic.tenant_id, "form_response.create")
        if e["result"] == "DENIED"
    ]
    assert denied and denied[0]["reason"] == "AUTHZ_CARE_RELATIONSHIP_DENIED"
    relate(
        forms.client,
        clinic.owner.headers,
        patient_id=clinic.patient_id,
        practitioner_id=nurse.user_id,
    )
    assert forms.record(nurse, clinic.patient_id).status_code == 201


def test_a_role_without_clinical_access_is_refused(
    forms: FormsApi, clinic: Clinic
) -> None:
    pharmacy = forms.add(clinic.owner, "PHARMACY")
    assert forms.record(pharmacy, clinic.patient_id).status_code == 403
    assert forms.history(pharmacy, clinic.patient_id).status_code == 403


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE form_responses SET total_score = 0",
        "DELETE FROM form_responses",
        "DELETE FROM safety_flags",
        "UPDATE safety_flags SET rule_code = 'PHQ9_ITEM9_POSITIVE'",
    ],
)
def test_responses_are_append_only_and_flags_change_only_by_acknowledgement(
    statement: str,
) -> None:
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE clinos_app"))
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(uuid.uuid4())},
        )
        with pytest.raises(ProgrammingError) as refused:
            conn.execute(text(statement))
        assert isinstance(refused.value.orig, InsufficientPrivilege)
