"""The practice-wide register, `GET /api/v1/tga-approvals`, and the audited TGA reads.

Contract: `docs2/sdlc/05-approvals/api.md` (agreed 2026-10-07). Denial paths first, as the build
contract orders them: unauthenticated, permission not held, another tenant's rows, a client-supplied
`tenant_id`, malformed filters and cursors. Then the success path: the two selectors and their union,
keyset paging without skips or repeats, the practice totals, the patient names, and one
`tga_approval.read` event per page.

"Today" for the expiry window is read from the database clock in `Australia/Sydney`, exactly as the
service reads it, so the boundary cases cannot drift with the machine's zone.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from httpx import Response
from sqlalchemy import text

from app.core.db import engine
from app.modules.tga_approvals import service
from app.modules.tga_approvals.models import APPROVAL_STATES
from app.modules.tga_approvals.schemas import ApprovalStateCode
from tests.tga.conftest import (
    APPROVALS_URL,
    TenantWithPatient,
    TgaApi,
    problem_code,
)
from tests.utils.rbac import ActorSession

READ = "tga_approval.read"


def _register(api: TgaApi, actor: ActorSession, **params: Any) -> Response:
    return api.client.get(APPROVALS_URL, params=params, headers=actor.headers)


def _sydney_today() -> date:
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date")
        ).scalar_one()
    assert isinstance(value, date)
    return value


def _read_events(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT result, reason, resource_id, actor_id, metadata FROM audit_log"
                    " WHERE tenant_id = :tenant_id AND action = :action"
                    ' ORDER BY "timestamp", event_id'
                ),
                {"tenant_id": tenant_id, "action": READ},
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def _seed(api: TgaApi, clinic: TenantWithPatient) -> dict[str, uuid.UUID]:
    """One approval per interesting register bucket, all on the clinic's one patient.

    Each `ACTIVE` row is at its own grain (dosage form), so the overlap exclusion is not provoked.
    """
    assert clinic.owner.tenant_id is not None
    today = _sydney_today()
    start = (today - timedelta(days=100)).isoformat()

    def insert(state: str, valid_to: date, form: str, **extra: Any) -> uuid.UUID:
        return api.insert_approval(
            tenant_id=clinic.owner.tenant_id,  # type: ignore[arg-type]
            patient_id=clinic.patient_id,
            state=state,
            dosage_form=form,
            valid_from=start,
            valid_to=valid_to.isoformat(),
            created_by=clinic.owner.user_id,
            **extra,
        )

    return {
        "pending": insert("PENDING", today + timedelta(days=300), "FORM_A"),
        "expiring": insert("ACTIVE", today + timedelta(days=10), "FORM_B"),
        "lapsed": insert("ACTIVE", today - timedelta(days=1), "FORM_C"),
        "healthy": insert("ACTIVE", today + timedelta(days=200), "FORM_D"),
        "revoked": insert(
            "REVOKED",
            today + timedelta(days=200),
            "FORM_E",
            revoked_reason_code="ENTERED_IN_ERROR",
        ),
        "expired": insert("EXPIRED", today - timedelta(days=5), "FORM_F"),
    }


def _ids(response: Response) -> set[uuid.UUID]:
    return {uuid.UUID(row["id"]) for row in response.json()["data"]}


# -- Denials ----------------------------------------------------------------------------------


def test_the_register_refuses_an_unauthenticated_caller(api: TgaApi) -> None:
    response = api.client.get(APPROVALS_URL)
    assert response.status_code == 401


def test_the_register_refuses_and_audits_a_caller_without_the_read_permission(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """Deny by default: an account with no role holds no `tga_approval:read`."""
    assert clinic.owner.tenant_id is not None
    _seed(api, clinic)
    nobody = api.second_clinician(owner=clinic.owner, role_code=None)  # type: ignore[arg-type]

    response = _register(api, nobody)

    assert response.status_code == 403
    assert problem_code(response) == "PERMISSION_NOT_HELD"
    assert "data" not in response.json()
    denials = [
        event
        for event in _read_events(clinic.owner.tenant_id)
        if event["actor_id"] == nobody.user_id
    ]
    assert [(event["result"], event["reason"]) for event in denials] == [
        ("DENIED", "PERMISSION_NOT_HELD")
    ]


def test_another_practices_register_shows_none_of_these_approvals(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """R8, INV-1: the tenant is the session's, and RLS plus the predicate bound every row and count."""
    _seed(api, clinic)
    intruder = api.register(clinic_name="Synthetic Clinic B")

    response = _register(api, intruder)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == []
    assert body["next_cursor"] is None
    assert set(body["counts"]["by_state"].values()) == {0}
    assert body["counts"]["expiring"] == 0


def test_a_client_tenant_id_is_ignored_and_audited(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """INV-1: naming another tenant changes nothing, and the attempt is written down."""
    seeded = _seed(api, clinic)
    intruder = api.register(clinic_name="Synthetic Clinic B")
    assert intruder.tenant_id is not None

    response = _register(api, intruder, tenant_id=str(clinic.owner.tenant_id))

    assert response.status_code == 200, response.text
    assert _ids(response).isdisjoint(seeded.values())
    events = _read_events(intruder.tenant_id)
    assert [(event["result"], event["reason"]) for event in events] == [
        ("SUCCESS", "CLIENT_TENANT_ID_IGNORED")
    ]


def test_malformed_filters_are_refused_before_any_read(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    for params in (
        {"state": "LAPSED"},
        {"state": "active"},
        {"expiring_within_days": -1},
        {"expiring_within_days": service.MAX_EXPIRING_WITHIN_DAYS + 1},
        {"expiring_within_days": "soon"},
        {"limit": 0},
        {"limit": service.MAX_PAGE_SIZE + 1},
        {"cursor": "x" * 513},
    ):
        response = _register(api, clinic.owner, **params)
        assert response.status_code == 422, params


def test_a_forged_or_garbled_cursor_is_refused(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    _seed(api, clinic)
    first = _register(api, clinic.owner, limit=2).json()
    body, signature = first["next_cursor"].split(".", 1)

    for cursor in ("not-a-cursor", f"{body}.{'A' * len(signature)}", f"{body}x"):
        response = _register(api, clinic.owner, cursor=cursor)
        assert response.status_code == 422
        assert problem_code(response) == "INVALID_CURSOR"


# -- Success ----------------------------------------------------------------------------------


def test_no_filter_lists_every_approval_with_the_practice_totals(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    seeded = _seed(api, clinic)

    response = _register(api, clinic.owner)

    assert response.status_code == 200, response.text
    body = response.json()
    assert _ids(response) == set(seeded.values())
    assert body["count"] == len(seeded)
    assert body["next_cursor"] is None
    assert body["counts"] == {
        "by_state": {
            "PENDING": 1,
            "ACTIVE": 3,
            "EXPIRED": 1,
            "REJECTED": 0,
            "REVOKED": 1,
            "SUPERSEDED": 0,
        },
        # The 10-day one, and the one the expiry job has not reached yet.
        "expiring": 2,
        "expiring_within_days": service.DEFAULT_EXPIRING_WITHIN_DAYS,
    }
    # Newest first on the shared `(created_at, id)` keyset.
    created = [row["created_at"] for row in body["data"]]
    assert created == sorted(created, reverse=True)


def test_state_filters_select_by_state(api: TgaApi, clinic: TenantWithPatient) -> None:
    seeded = _seed(api, clinic)

    pending = _register(api, clinic.owner, state="PENDING")
    inactive = _register(
        api,
        clinic.owner,
        state=["EXPIRED", "REVOKED", "SUPERSEDED", "REJECTED"],
    )

    assert _ids(pending) == {seeded["pending"]}
    assert _ids(inactive) == {seeded["revoked"], seeded["expired"]}
    # The totals do not follow the filter: the chips need every count on every filter.
    assert pending.json()["counts"] == inactive.json()["counts"]


def test_needs_action_is_pending_or_expiring(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """The two selectors are a union: the register's "Needs action" filter is one query."""
    seeded = _seed(api, clinic)

    expiring = _register(api, clinic.owner, expiring_within_days=30)
    needs_action = _register(
        api, clinic.owner, state="PENDING", expiring_within_days=30
    )

    assert _ids(expiring) == {seeded["expiring"], seeded["lapsed"]}
    assert _ids(needs_action) == {
        seeded["pending"],
        seeded["expiring"],
        seeded["lapsed"],
    }


def test_the_expiry_window_is_counted_on_the_last_covered_day(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """D-006 interim `[)`: `valid_to` is not covered, so the last covered day is `valid_to - 1`."""
    assert clinic.owner.tenant_id is not None
    today = _sydney_today()
    start = (today - timedelta(days=10)).isoformat()
    inside = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="ACTIVE",
        dosage_form="FORM_A",
        valid_from=start,
        # Last covered day = today + 7.
        valid_to=(today + timedelta(days=8)).isoformat(),
    )
    outside = api.insert_approval(
        tenant_id=clinic.owner.tenant_id,
        patient_id=clinic.patient_id,
        state="ACTIVE",
        dosage_form="FORM_B",
        valid_from=start,
        # Last covered day = today + 8.
        valid_to=(today + timedelta(days=9)).isoformat(),
    )

    response = _register(api, clinic.owner, expiring_within_days=7)

    assert _ids(response) == {inside}
    assert outside not in _ids(response)
    assert response.json()["counts"]["expiring"] == 1
    assert response.json()["counts"]["expiring_within_days"] == 7


def test_keyset_pages_never_skip_or_repeat_an_approval(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    seeded = _seed(api, clinic)

    seen: list[uuid.UUID] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 4}
        if cursor is not None:
            params["cursor"] = cursor
        response = _register(api, clinic.owner, **params)
        assert response.status_code == 200, response.text
        body = response.json()
        seen.extend(uuid.UUID(row["id"]) for row in body["data"])
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 2
    assert len(seen) == len(set(seen)) == len(seeded)
    assert set(seen) == set(seeded.values())


def test_a_filtered_page_continues_the_same_filter(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    seeded = _seed(api, clinic)

    first = _register(api, clinic.owner, state="ACTIVE", limit=2).json()
    second = _register(
        api, clinic.owner, state="ACTIVE", limit=2, cursor=first["next_cursor"]
    ).json()

    ids = [uuid.UUID(row["id"]) for row in first["data"] + second["data"]]
    assert set(ids) == {seeded["expiring"], seeded["lapsed"], seeded["healthy"]}
    assert second["next_cursor"] is None


def test_each_row_names_its_patient(api: TgaApi, clinic: TenantWithPatient) -> None:
    """The register names patients through the patients facade, preferred name first."""
    assert clinic.owner.tenant_id is not None
    other = api.create_patient(
        clinic.owner, given_name="Robert", family_name="Example", preferred_name="Bob"
    )
    api.create(clinic.owner, clinic.patient_id)
    api.create(clinic.owner, other)

    rows = _register(api, clinic.owner).json()["data"]

    names = {uuid.UUID(row["patient_id"]): row["patient_display_name"] for row in rows}
    assert names == {clinic.patient_id: "Ada Synthetic", other: "Bob Example"}


def test_a_soft_deleted_patients_approval_stays_listed_without_a_name(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """A regulatory register never drops a row because the patient is no longer readable."""
    approval = api.create(clinic.owner, clinic.patient_id)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE patients SET deleted_at = now() WHERE id = :id"),
            {"id": clinic.patient_id},
        )

    rows = _register(api, clinic.owner).json()["data"]

    assert [(row["id"], row["patient_display_name"]) for row in rows] == [
        (approval["id"], None)
    ]


def test_each_register_page_is_one_audited_read_with_its_filters(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    assert clinic.owner.tenant_id is not None
    _seed(api, clinic)

    first = _register(
        api, clinic.owner, state=["PENDING"], expiring_within_days=30, limit=2
    ).json()
    _register(
        api,
        clinic.owner,
        state=["PENDING"],
        expiring_within_days=30,
        limit=2,
        cursor=first["next_cursor"],
    )

    events = _read_events(clinic.owner.tenant_id)
    assert [event["result"] for event in events] == ["SUCCESS", "SUCCESS"]
    assert all(event["actor_id"] == clinic.owner.user_id for event in events)
    assert all(event["resource_id"] is None for event in events)
    assert [event["metadata"] for event in events] == [
        {
            "query_filters": {"state": ["PENDING"], "expiring_within_days": 30},
            "result_count": 2,
        },
        {
            "query_filters": {
                "state": ["PENDING"],
                "expiring_within_days": 30,
                "cursor": True,
            },
            "result_count": 1,
        },
    ]


# -- The per-patient list and the detail read are audited too ---------------------------------


def test_a_patient_list_and_a_detail_read_are_each_one_audited_read(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """US-2: `approval.read` once per patient-level access, not per row."""
    assert clinic.owner.tenant_id is not None
    first = api.create(clinic.owner, clinic.patient_id)
    api.create(
        clinic.owner,
        clinic.patient_id,
        approval_reference="TGA-2026-000124",
        dosage_form="ORAL_SPRAY",
    )

    assert api.list_for_patient(clinic.owner, clinic.patient_id).status_code == 200
    assert api.read(clinic.owner, first["id"]).status_code == 200

    events = _read_events(clinic.owner.tenant_id)
    assert [
        (event["result"], event["resource_id"], event["metadata"]) for event in events
    ] == [
        ("SUCCESS", None, {"patient_id": str(clinic.patient_id), "result_count": 2}),
        (
            "SUCCESS",
            uuid.UUID(first["id"]),
            {"patient_id": str(clinic.patient_id), "result_count": 1},
        ),
    ]


def test_read_refusals_are_audited(api: TgaApi, clinic: TenantWithPatient) -> None:
    """HANDOFF section 8: TGA read refusals were unaudited until `tga_approval.read` existed."""
    assert clinic.owner.tenant_id is not None
    approval = api.create(clinic.owner, clinic.patient_id)
    intruder = api.register(clinic_name="Synthetic Clinic B")
    assert intruder.tenant_id is not None
    nobody = api.second_clinician(owner=clinic.owner, role_code=None)  # type: ignore[arg-type]

    assert api.read(intruder, approval["id"]).status_code == 404
    assert api.list_for_patient(intruder, clinic.patient_id).status_code == 404
    assert api.read(nobody, approval["id"]).status_code == 403
    assert api.list_for_patient(nobody, clinic.patient_id).status_code == 403

    intruder_events = _read_events(intruder.tenant_id)
    assert [(e["result"], e["reason"]) for e in intruder_events] == [
        ("DENIED", "CROSS_TENANT"),
        ("DENIED", "CROSS_TENANT"),
    ]
    # The cross-tenant identifier is held only in the intruder's own trail.
    assert intruder_events[0]["resource_id"] == uuid.UUID(approval["id"])
    nobody_events = [
        e
        for e in _read_events(clinic.owner.tenant_id)
        if e["actor_id"] == nobody.user_id
    ]
    assert [(e["result"], e["reason"]) for e in nobody_events] == [
        ("DENIED", "PERMISSION_NOT_HELD"),
        ("DENIED", "PERMISSION_NOT_HELD"),
    ]


def test_the_patient_list_shares_the_register_cursor_rules(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """One keyset, one cursor format: a garbled cursor is refused on the patient list too."""
    response = api.list_for_patient(clinic.owner, clinic.patient_id, cursor="nope")
    assert response.status_code == 422
    assert problem_code(response) == "INVALID_CURSOR"


# -- Units ------------------------------------------------------------------------------------


def test_the_filter_vocabulary_is_the_models_states() -> None:
    assert ApprovalStateCode.__args__ == APPROVAL_STATES  # type: ignore[attr-defined]


def test_the_expiry_bound_follows_the_half_open_boundary() -> None:
    today = date(2026, 10, 7)
    bound = service.last_expiring_valid_to(today=today, within_days=30)
    last_covered = bound - timedelta(days=1)
    assert last_covered == today + timedelta(days=30)
    assert service.within_validity_window(
        valid_from=today, valid_to=bound, date_of_service=last_covered
    )
    assert not service.within_validity_window(
        valid_from=today, valid_to=bound, date_of_service=bound
    )


def test_the_service_refuses_out_of_range_arguments() -> None:
    tenant = uuid.uuid4()
    for kwargs in (
        {"limit": 0},
        {"limit": service.MAX_PAGE_SIZE + 1},
        {"expiring_within_days": -1},
        {"expiring_within_days": service.MAX_EXPIRING_WITHIN_DAYS + 1},
    ):
        try:
            service.list_register(
                tenant_id=tenant,
                actor_id=None,
                actor_role=None,
                **kwargs,  # type: ignore[arg-type]
            )
        except ValueError:
            continue
        raise AssertionError(f"{kwargs} was accepted")
