"""S1–S6, S8 — the tenant boundary on the audit surface, and the read path that is itself audited.

`docs/features/04-audit-log/06-test-plan.md` security tests S1, S2, S3, S5, S6, S7, S8 and
functional tests F5, F7, F8, F9. Requirement R12.

Every case here is about the same invariant from a different side: **the tenant is resolved from the
session and never supplied** (INV-1), so a caller cannot read another organisation's trail, cannot
name one, and cannot tell "absent" from "another tenant's" — and the read that was refused is itself
an event, because the attempt is exactly what the trail exists to hold.
"""

import uuid

from app.core.config import settings
from tests.audit.conftest import AuditApi, actions_of, audit_count, audit_rows

AUDIT_EVENTS = f"{settings.API_V1_STR}/audit/events"
PATIENTS = f"{settings.API_V1_STR}/patients"


def _seed(api: AuditApi, count: int) -> list[str]:
    """Write `count` distinct events through the application, returning their actions."""
    written: list[str] = []
    for index in range(count):
        if index % 2 == 0:
            response = api.rbac.client.post(
                PATIENTS,
                json={
                    "given_name": f"Audit{index}",
                    "family_name": "Synthetic",
                    "date_of_birth": "1990-01-01",
                },
                headers=api.headers,
            )
            assert response.status_code == 201, response.text
            written.append("patient.create")
        else:
            patient = api.rbac.client.get(PATIENTS, headers=api.headers).json()["data"][
                0
            ]
            response = api.rbac.client.patch(
                f"{PATIENTS}/{patient['id']}",
                json={"preferred_name": f"Audit{index}"},
                headers=api.headers,
            )
            assert response.status_code == 200, response.text
            written.append("patient.update")
    return written


# ---------------------------------------------------------------------------------------------
# S1, S2 — the tenant boundary
# ---------------------------------------------------------------------------------------------


def test_cross_tenant_audit_read_returns_empty(
    two_tenants: tuple[AuditApi, AuditApi],
) -> None:
    """S1: an auditor at A querying B's identifiers gets `200` with zero rows, not a `403`."""
    first, second = two_tenants
    _seed(first, 3)
    _seed(second, 2)

    response = first.rbac.client.get(
        AUDIT_EVENTS,
        params={"resource_id": str(uuid.uuid4())},
        headers=first.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 0
    assert body["data"] == []

    # Every event it can see is its own, and the other tenant's rows are not reachable by any filter.
    everything = first.rbac.client.get(
        AUDIT_EVENTS, params={"action": "patient.create"}, headers=first.headers
    ).json()
    assert everything["count"] == 2
    assert {row["action"] for row in everything["data"]} == {"patient.create"}


def test_cross_tenant_event_id_returns_404(
    two_tenants: tuple[AuditApi, AuditApi],
) -> None:
    """S2: a foreign event id is `404 Not Found`, never `403` — a `403` confirms it exists."""
    first, second = two_tenants
    _seed(second, 1)
    # Read the identifier as a plain value, not as an ORM instance: the row was loaded inside the
    # service's transaction, and holding the entity across the boundary is what `DetachedInstanceError`
    # is for. The identifier is all the case needs.
    foreign = str(audit_rows(second.tenant_id)[0]["event_id"])

    response = first.rbac.client.get(f"{AUDIT_EVENTS}/{foreign}", headers=first.headers)
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Audit event not found", (
        "the body must not distinguish 'absent' from 'another tenant's'"
    )

    # US-6: the attempted cross-tenant read is itself audited, with the actor.
    denials = [
        row
        for row in audit_rows(first.tenant_id)
        if row["action"] == "audit.read" and row["result"] == "DENIED"
    ]
    assert denials, "the cross-tenant attempt left no evidence"
    assert str(denials[0]["actor_id"]) == str(first.user_id)
    assert denials[0]["reason"] == "CROSS_TENANT"


def test_a_tenant_can_read_its_own_event_by_id(api: AuditApi) -> None:
    """The positive half of S2: the design's `GET /api/v1/audit/{event_id}` shape."""
    _seed(api, 1)
    mine = audit_rows(api.tenant_id)[0]["event_id"]

    response = api.rbac.client.get(f"{AUDIT_EVENTS}/{mine}", headers=api.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_id"] == str(mine)
    assert body["hash"] == audit_rows(api.tenant_id)[0]["hash"]
    assert "tenant_id" not in body, (
        "the envelope the API returns declares no tenant — the caller already knows its own"
    )


def test_missing_tenant_setting_returns_zero_rows() -> None:
    """S3: fail closed. An unset `app.tenant_id` matches nothing through `NULLIF`, never everything.

    This is the database's own behaviour, asserted directly, because it is the control and not an
    implementation detail: the policy is
    `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`, and `= NULL` is never
    true.
    """
    from sqlalchemy import text

    from app.core.db import engine

    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            visible = conn.execute(text("SELECT count(*) FROM audit_log")).scalar_one()
    assert visible == 0, (
        f"an unset tenant context read {visible} rows — the policy is not fail-closed"
    )


def test_the_application_role_sees_only_its_own_tenants_rows(api: AuditApi) -> None:
    """The same policy, positive case: with the context set, `clinos_app` sees its own rows.

    Without this, S3 would pass on a policy that denies everything — a control that is broken in the
    direction nobody notices until the feature is useless.
    """
    from sqlalchemy import text

    from app.core.db import engine

    _seed(api, 2)
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(api.tenant_id)},
            )
            visible = conn.execute(
                text("SELECT count(*) FROM audit_log WHERE tenant_id = :tenant_id"),
                {"tenant_id": api.tenant_id},
            ).scalar_one()
    assert visible == audit_count(api.tenant_id)


# ---------------------------------------------------------------------------------------------
# S5, S6 — the permission gate
# ---------------------------------------------------------------------------------------------


def test_audit_read_requires_the_permission(api: AuditApi) -> None:
    """S5/S6: a caller without `audit:read` is refused `403`, and the refusal is not a data leak."""
    actor = api.rbac.add_actor(
        tenant_id=api.tenant_id, granted_by=api.user_id, role_code="NURSE"
    )
    response = api.rbac.client.get(
        AUDIT_EVENTS, params={"action": "patient.create"}, headers=actor.headers
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"


def test_audit_read_is_available_to_a_compliance_auditor(api: AuditApi) -> None:
    """S5's positive half: `COMPLIANCE_AUDITOR` holds `audit:read` and can use it."""
    actor = api.rbac.add_actor(
        tenant_id=api.tenant_id, granted_by=api.user_id, role_code="COMPLIANCE_AUDITOR"
    )
    _seed(api, 1)

    response = api.rbac.client.get(
        AUDIT_EVENTS, params={"action": "patient.create"}, headers=actor.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["count"] >= 1


def test_audit_unauthenticated_returns_401(api: AuditApi) -> None:
    """S6: no session is `401`, and the request never reaches a tenant."""
    response = api.rbac.client.get(AUDIT_EVENTS, params={"action": "patient.create"})
    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------------------------
# F8 — the request is refused before it becomes a scan
# ---------------------------------------------------------------------------------------------


def test_unbounded_scan_and_wide_range_refused(api: AuditApi) -> None:
    """F8: no filter is `422`, and a range over 90 days is `422`."""
    unfiltered = api.rbac.client.get(AUDIT_EVENTS, headers=api.headers)
    assert unfiltered.status_code == 422, unfiltered.text
    assert "at least one filter" in unfiltered.text

    too_wide = api.rbac.client.get(
        AUDIT_EVENTS,
        params={"from": "2020-01-01T00:00:00Z", "to": "2021-01-01T00:00:00Z"},
        headers=api.headers,
    )
    assert too_wide.status_code == 422, too_wide.text
    assert "90 days" in too_wide.text


def test_an_unknown_result_is_refused(api: AuditApi) -> None:
    """The `result` filter is a closed set, so a typo is a `422` rather than an empty page."""
    response = api.rbac.client.get(
        AUDIT_EVENTS, params={"result": "MAYBE"}, headers=api.headers
    )
    assert response.status_code == 422, response.text


def test_a_forged_cursor_is_refused(api: AuditApi) -> None:
    """S7/S8's spirit: the cursor is an input, and an input this API did not issue is a `422`.

    A forged cursor is the way a caller would try to skip to a position it was never authorised to
    reach, so the signature is what makes the opaque token a control rather than a convenience.
    """
    response = api.rbac.client.get(
        AUDIT_EVENTS,
        params={"action": "patient.create", "cursor": "not-a-cursor"},
        headers=api.headers,
    )
    assert response.status_code == 422, response.text

    forged = api.rbac.client.get(
        AUDIT_EVENTS,
        params={
            "action": "patient.create",
            "cursor": "eyJlIjogIjEiLCAidCI6ICIyIn0=.deadbeef",
        },
        headers=api.headers,
    )
    assert forged.status_code == 422, forged.text


def test_limit_is_capped_at_the_server_maximum(api: AuditApi) -> None:
    """F7: default 50, max 200. Asking for more is a `422`, not a silently truncated page."""
    response = api.rbac.client.get(
        AUDIT_EVENTS,
        params={"action": "patient.create", "limit": 500},
        headers=api.headers,
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------------------------
# F7, F9 — keyset pagination and the audited read
# ---------------------------------------------------------------------------------------------


def test_read_pagination_and_filters(api: AuditApi) -> None:
    """F7: keyset on `(timestamp, event_id)`, an opaque cursor, and filters that narrow."""
    written = _seed(api, 6)
    assert written.count("patient.create") == 3

    page = api.rbac.client.get(
        AUDIT_EVENTS,
        params={"action": "patient.create", "limit": 2},
        headers=api.headers,
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["count"] == 2
    assert body["next_cursor"] is not None

    second = api.rbac.client.get(
        AUDIT_EVENTS,
        params={"action": "patient.create", "limit": 2, "cursor": body["next_cursor"]},
        headers=api.headers,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()

    first_ids = {row["event_id"] for row in body["data"]}
    second_ids = {row["event_id"] for row in second_body["data"]}
    assert not (first_ids & second_ids), (
        "the second page repeated a row the first page already returned — the cursor is not keyset"
    )
    all_ids = [row["event_id"] for row in body["data"] + second_body["data"]]
    assert len(set(all_ids)) == len(all_ids)
    assert second_body["next_cursor"] is None, (
        "three create events in pages of two must end after the second page"
    )

    # Newest first, which is the order the `(tenant_id, timestamp DESC)` index serves.
    timestamps = [row["timestamp"] for row in body["data"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_audit_read_is_itself_audited(api: AuditApi) -> None:
    """F9: every call writes `audit.read`, including the one that returns nothing."""
    before = actions_of(api.tenant_id)

    empty = api.rbac.client.get(
        AUDIT_EVENTS,
        params={"resource_type": "PRESCRIPTION"},
        headers=api.headers,
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["count"] == 0

    events = audit_rows(api.tenant_id)[len(before) :]
    assert [event["action"] for event in events] == ["audit.read"], (
        "an empty result must still be audited — that is the whole point of R7's 'equal fidelity'"
    )
    payload = events[0]["metadata"]
    assert payload["result_count"] == 0
    assert payload["query_filters"] == {"resource_type": "PRESCRIPTION"}, (
        "the event records the filters that were asked for, and nothing the caller did not supply"
    )


def test_the_read_event_recorded_for_a_page_counts_the_page(api: AuditApi) -> None:
    """The `audit.read` event carries the result count of the page that was returned."""
    _seed(api, 2)
    before = len(audit_rows(api.tenant_id))

    response = api.rbac.client.get(
        AUDIT_EVENTS, params={"action": "patient.create"}, headers=api.headers
    )
    assert response.status_code == 200, response.text

    events = audit_rows(api.tenant_id)[before:]
    assert len(events) == 1
    assert events[0]["metadata"]["result_count"] == response.json()["count"]


def test_the_single_event_read_is_also_audited(api: AuditApi) -> None:
    """A one-event read is a read: it writes `audit.read` like any other."""
    _seed(api, 1)
    mine = audit_rows(api.tenant_id)[0]["event_id"]
    before = len(audit_rows(api.tenant_id))

    response = api.rbac.client.get(f"{AUDIT_EVENTS}/{mine}", headers=api.headers)
    assert response.status_code == 200, response.text

    events = audit_rows(api.tenant_id)[before:]
    assert [event["action"] for event in events] == ["audit.read"]
    assert events[0]["metadata"]["result_count"] == 1


def test_the_read_api_returns_no_clinical_value(api: AuditApi) -> None:
    """S10's audit-surface half: a full read returns the envelope and no patient content.

    The patient's names are in the record; they must not be in the trail, and therefore not in the
    API's answer either.
    """
    sentinel = "PATIENT_NAME_SENTINEL-4b71"
    created = api.rbac.client.post(
        PATIENTS,
        json={
            "given_name": sentinel,
            "family_name": sentinel,
            "date_of_birth": "1990-01-01",
        },
        headers=api.headers,
    )
    assert created.status_code == 201, created.text

    response = api.rbac.client.get(
        AUDIT_EVENTS, params={"action": "patient.create"}, headers=api.headers
    )
    assert response.status_code == 200, response.text
    assert sentinel not in response.text, (
        "the audit read API returned a clinical value — the trail has become a second copy of the "
        "medical record"
    )
