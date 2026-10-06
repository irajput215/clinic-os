"""Lifecycle: creation, the state machine, revocation, the expiry sweep and the supersede chain.

F1-F10 of `docs/features/08-tga-approvals/06-test-plan.md`, and R1-R7, R11, R12 of
`01-requirements.md`. The denial path is asserted beside every success path, because a control that
has never refused anything has not been tested.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.modules.tga_approvals import service
from app.modules.tga_approvals.models import LEGAL_TRANSITIONS
from tests.tga.conftest import (
    DEFAULT_APPROVAL,
    TenantWithPatient,
    TgaApi,
    problem_code,
    validation_types,
)


def test_create_approval_is_201_pending_and_tenant_from_session(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """R1, F1, US-1: created `PENDING`, at the grain, with the tenant resolved from the session."""
    before = api.approval_count(clinic.owner.tenant_id or uuid.uuid4())
    created = api.create(clinic.owner, clinic.patient_id)

    assert created["state"] == "PENDING"
    assert created["source"] == "MANUAL_ENTRY"
    assert created["tenant_id"] == str(clinic.owner.tenant_id)
    assert created["created_by"] == str(clinic.owner.user_id)
    assert created["verified_by"] is None
    assert created["valid_from"] == DEFAULT_APPROVAL["valid_from"]
    assert created["valid_to"] == DEFAULT_APPROVAL["valid_to"]
    assert api.approval_count(clinic.owner.tenant_id) == before + 1

    # The exclusion constraint indexes a column the trigger derives from the dates, and the database
    # is asked whether that is true — not Python.
    assert api.interval_is_derived(
        created["id"],
        valid_from=DEFAULT_APPROVAL["valid_from"],
        valid_to=DEFAULT_APPROVAL["valid_to"],
    )
    # The creation is the first link of the reconstructible history.
    assert api.events(created["id"]) == [
        {
            "from_state": None,
            "to_state": "PENDING",
            "reason": "MANUAL_ENTRY",
            "actor_id": clinic.owner.user_id,
        }
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "00000000-0000-0000-0000-000000000001"),
        ("state", "ACTIVE"),
        ("verified_by", "00000000-0000-0000-0000-000000000002"),
        ("created_by", "00000000-0000-0000-0000-000000000003"),
        ("source", "INBOX_EXTRACTION"),
    ],
)
def test_mass_assignment_is_refused_and_writes_nothing(
    api: TgaApi, clinic: TenantWithPatient, field: str, value: str
) -> None:
    """R2, S5: `tenant_id`, `state`, `verified_by` and the rest are not the client's to set."""
    before = api.approval_count(clinic.owner.tenant_id)
    response = api.create_raw(clinic.owner, clinic.patient_id, **{field: value})
    assert response.status_code == 422, response.text
    assert api.approval_count(clinic.owner.tenant_id) == before


def test_window_of_more_than_two_years_is_refused_with_the_documented_code(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """R3, F3: `422 ERR_WINDOW_EXCEEDS_MAX_DURATION`, and zero rows written."""
    before = api.approval_count(clinic.owner.tenant_id)
    response = api.create_raw(
        clinic.owner,
        clinic.patient_id,
        valid_from="2026-01-01",
        valid_to="2028-01-02",
    )
    assert response.status_code == 422, response.text
    assert "ERR_WINDOW_EXCEEDS_MAX_DURATION" in validation_types(response)
    assert api.approval_count(clinic.owner.tenant_id) == before

    # The boundary itself is legal: exactly two years is allowed, and one day beyond it is not. The
    # schema and `ck_tga_approvals_max_duration` are asserted to agree by the leap-day-safe
    # arithmetic in `schemas._max_valid_to`.
    assert (
        api.create_raw(
            clinic.owner,
            clinic.patient_id,
            valid_from="2026-01-01",
            valid_to="2028-01-01",
        ).status_code
        == 201
    )
    assert (
        api.create_raw(
            clinic.owner,
            clinic.patient_id,
            approval_reference="TGA-2026-000124",
            valid_from="2024-02-29",
            valid_to="2026-03-01",
        ).status_code
        == 422
    )


def test_a_reversed_window_is_refused(api: TgaApi, clinic: TenantWithPatient) -> None:
    response = api.create_raw(
        clinic.owner, clinic.patient_id, valid_from="2026-07-01", valid_to="2026-01-01"
    )
    assert response.status_code == 422, response.text
    assert "ERR_WINDOW_NOT_FORWARD" in validation_types(response)


def test_illegal_transition_is_refused_with_409(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """R6, F6: `revoked -> active`, and a second verification of an `ACTIVE` row, are `409`."""
    verifier = api.second_clinician(owner=clinic.owner)
    approval = api.create(clinic.owner, clinic.patient_id)
    assert api.activate(clinic.owner, approval, verifier=verifier).status_code == 200

    # `ACTIVE -> ACTIVE`: the second attempt has to get past four-eyes first (the verifier is still
    # not the creator), so the refusal that comes back is the transition, not the identity.
    repeated = api.activate(clinic.owner, approval, verifier=verifier)
    assert repeated.status_code == 409, repeated.text
    assert problem_code(repeated) == "ILLEGAL_STATE_TRANSITION"
    assert api.row(approval["id"])["state"] == "ACTIVE"

    # And a terminal row is terminal: revoke it, then try to revoke it again.
    revoked = api.revoke(clinic.owner, approval["id"])
    assert revoked.status_code == 200, revoked.text
    again = api.revoke(clinic.owner, approval["id"])
    assert again.status_code == 409, again.text
    assert problem_code(again) == "ILLEGAL_STATE_TRANSITION"


def test_every_terminal_state_refuses_every_outbound_transition() -> None:
    """R4, R6: the map itself. A terminal state has no legal successor, and that is the contract."""
    assert set(LEGAL_TRANSITIONS) == {
        "PENDING",
        "ACTIVE",
        "EXPIRED",
        "REJECTED",
        "REVOKED",
        "SUPERSEDED",
    }
    for terminal in ("EXPIRED", "REJECTED", "REVOKED", "SUPERSEDED"):
        assert LEGAL_TRANSITIONS[terminal] == frozenset()
    assert LEGAL_TRANSITIONS["PENDING"] == frozenset({"ACTIVE", "REJECTED", "REVOKED"})
    assert LEGAL_TRANSITIONS["ACTIVE"] == frozenset(
        {"SUPERSEDED", "EXPIRED", "REVOKED"}
    )


def test_revoke_requires_a_reason_code_and_stores_it(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """R9, F5, US-6: a revocation without a reason is `422`; with one it is recorded as a code."""
    approval = api.create(clinic.owner, clinic.patient_id)

    missing = api.revoke(clinic.owner, approval["id"], reason_code=None)
    assert missing.status_code == 422, missing.text
    assert api.row(approval["id"])["state"] == "PENDING"

    revoked = api.revoke(clinic.owner, approval["id"], reason_code="CLINICAL_ERROR")
    assert revoked.status_code == 200, revoked.text
    body = revoked.json()
    assert body["state"] == "REVOKED"
    assert body["revoked_reason_code"] == "CLINICAL_ERROR"
    assert body["revoked_by"] == str(clinic.owner.user_id)
    assert body["revoked_at"] is not None

    # Free text is not a reason code: the column is a code, and the schema says so.
    other = api.create(
        clinic.owner, clinic.patient_id, approval_reference="TGA-2026-000125"
    )
    free_text = api.revoke(clinic.owner, other["id"], reason_code="patient asked me to")
    assert free_text.status_code == 422, free_text.text


def test_expiry_sweep_is_idempotent_and_uses_the_database_clock(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F7, T2-10: the sweep moves a closed window to `EXPIRED` once, and a second run changes nothing."""
    verifier = api.second_clinician(owner=clinic.owner)
    approval = api.create(
        clinic.owner,
        clinic.patient_id,
        valid_from="2025-01-01",
        valid_to="2025-06-01",
    )
    assert api.activate(clinic.owner, approval, verifier=verifier).status_code == 200

    tenant_id = clinic.owner.tenant_id
    assert tenant_id is not None
    assert service.expire_due_approvals(tenant_id=tenant_id) == 1
    assert api.row(approval["id"])["state"] == "EXPIRED"
    assert service.expire_due_approvals(tenant_id=tenant_id) == 0

    transitions = [
        (event["from_state"], event["to_state"]) for event in api.events(approval["id"])
    ]
    assert transitions == [
        (None, "PENDING"),
        ("PENDING", "ACTIVE"),
        ("ACTIVE", "EXPIRED"),
    ]


def test_the_half_open_boundary_decides_when_a_row_is_due(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """T2-11, D-006 §2: a row whose `valid_to` is today is **not** valid today, so it is due.

    This is the one place the boundary is decided, and the sweep, the match and reporting must agree
    with it. Evaluating `valid_to < CURRENT_DATE` — the literal expression the task list writes —
    would leave a row the gate already refuses looking `ACTIVE` for one more day.
    """
    verifier = api.second_clinician(owner=clinic.owner)
    tenant_id = clinic.owner.tenant_id
    assert tenant_id is not None
    today = _sydney_today()
    approval = api.create(
        clinic.owner,
        clinic.patient_id,
        valid_from=(today - timedelta(days=30)).isoformat(),
        valid_to=today.isoformat(),
    )
    assert api.activate(clinic.owner, approval, verifier=verifier).status_code == 200

    assert service.expire_due_approvals(tenant_id=tenant_id) == 1
    assert api.row(approval["id"])["state"] == "EXPIRED"


def _sydney_today() -> date:
    """Today in `Australia/Sydney`, read from the same zone constant the service uses."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(service.SYDNEY_TIMEZONE)).date()


def test_supersede_leaves_exactly_one_live_record_and_a_walkable_chain(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F9, T2-9, R12: the replacement is atomic with the predecessor's `SUPERSEDED`, and the chain
    resolves to one live grant."""
    verifier = api.second_clinician(owner=clinic.owner)
    first = api.create(clinic.owner, clinic.patient_id)
    assert api.activate(clinic.owner, first, verifier=verifier).status_code == 200

    replacement = api.client.post(
        f"/api/v1/tga-approvals/{first['id']}/supersede",
        json={
            "approval_reference": "TGA-2026-000999",
            "creation_reason": "EXTENSION",
            "valid_from": "2026-06-01",
            "valid_to": "2027-06-01",
        },
        headers=clinic.owner.headers,
    )
    assert replacement.status_code == 201, replacement.text
    second = replacement.json()
    assert second["state"] == "PENDING"
    assert second["supersedes_id"] == first["id"]
    # The predecessor stays live until an independent verifier activates the replacement.
    assert api.row(first["id"])["state"] == "ACTIVE"

    # The creator of the replacement cannot verify it — four-eyes applies to the supersede path too.
    assert api.activate(clinic.owner, second, verifier=clinic.owner).status_code == 403
    assert api.activate(clinic.owner, second, verifier=verifier).status_code == 200

    predecessor = api.row(first["id"])
    assert predecessor["state"] == "SUPERSEDED"
    # `api.row` reads the column through SQLAlchemy, which hands back a `uuid.UUID`; the API body
    # carries it as a string. Coerced, as `test_verification.py` does for `resource_id`.
    assert predecessor["superseded_by_id"] == uuid.UUID(second["id"])
    assert api.row(second["id"])["state"] == "ACTIVE"

    detail = api.read(clinic.owner, first["id"])
    assert detail.status_code == 200, detail.text
    chain = detail.json()["supersede_chain"]
    assert {link["id"] for link in chain} == {first["id"], second["id"]}
    live = [link for link in chain if link["state"] == "ACTIVE"]
    assert len(live) == 1 and live[0]["id"] == second["id"]


def test_a_duplicate_grain_entry_is_refused(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """T2-12: the same grain and window while a live row exists is `409 DUPLICATE_APPROVAL_GRAIN`."""
    api.create(clinic.owner, clinic.patient_id)
    duplicate = api.create_raw(clinic.owner, clinic.patient_id)
    assert duplicate.status_code == 409, duplicate.text
    assert problem_code(duplicate) == "DUPLICATE_APPROVAL_GRAIN"
