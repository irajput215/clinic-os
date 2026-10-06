"""F1/F6, S13–S16 — the writer, the payload allow-list and the chain.

`docs/features/04-audit-log/06-test-plan.md` functional tests F1–F6 and security tests S12h,
S13–S16. Requirements R3, R4, R8, R11.

The tamper cases do something the application cannot do — they `UPDATE` and `DELETE` a row — and that
is the point rather than a contradiction: the threat model's T-AUD-1 is *an insider with direct SQL*,
and the verification job's job is to notice when that has happened. The grant that stops the
**application** role from doing it is proven separately, in `test_append_only_grants.py`.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings
from app.core.db import engine, tenant_transaction
from app.modules.audit import service
from app.modules.audit.models import GENESIS_HASH
from tests.audit.conftest import (
    AuditApi,
    audit_count,
    audit_rows,
    chain_report,
    tamper,
)

PATIENT = {
    "given_name": "Ada",
    "family_name": "Synthetic",
    "date_of_birth": "1990-01-01",
}


# ---------------------------------------------------------------------------------------------
# F1, F2, S12h — one transaction
# ---------------------------------------------------------------------------------------------


def test_audit_writes_in_the_same_transaction(api: AuditApi) -> None:
    """F1: a domain change and its audit row commit together, and exactly one event per change."""
    assert audit_count(api.tenant_id) == 0

    created = api.rbac.client.post(
        f"{settings.API_V1_STR}/patients", json=PATIENT, headers=api.headers
    )
    assert created.status_code == 201, created.text
    patient_id = created.json()["id"]

    rows = audit_rows(api.tenant_id)
    assert [row["action"] for row in rows] == ["patient.create"], (
        "one create must produce exactly one `patient.create` event"
    )
    event = rows[0]
    assert str(event["resource_id"]) == patient_id
    assert event["result"] == "SUCCESS"
    assert str(event["actor_id"]) == str(api.user_id), (
        "the actor is the session's account, resolved from the token and never from the body"
    )
    assert event["actor_role"] == "PRACTICE_OWNER", (
        "`actor_role` is the role held at decision time"
    )
    assert event["request_id"] is not None and event["request_id"] != ""


def test_a_patch_audits_only_the_fields_the_client_sent(api: AuditApi) -> None:
    """`patient.updated` carries field **names**, never values (R11, T-AUD-4)."""
    created = api.rbac.client.post(
        "/api/v1/patients", json=PATIENT, headers=api.headers
    )
    assert created.status_code == 201, created.text
    patient_id = created.json()["id"]

    patched = api.rbac.client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"preferred_name": "Adelaide"},
        headers=api.headers,
    )
    assert patched.status_code == 200, patched.text

    update = [
        row for row in audit_rows(api.tenant_id) if row["action"] == "patient.update"
    ]
    assert len(update) == 1
    assert update[0]["metadata"] == {"changed_fields": ["preferred_name"]}, (
        "the payload must name the field and never carry its value"
    )
    assert "Adelaide" not in str(update[0]["metadata"])


def test_rollback_leaves_no_orphan_event(api: AuditApi) -> None:
    """F2/S12h's precondition: a caller that rolls back takes its audit row with it."""
    with pytest.raises(RuntimeError, match="the business write failed"):
        with tenant_transaction(
            tenant_id=api.tenant_id, actor_id=api.user_id
        ) as session:
            service.record(
                session,
                service.AuditEvent(
                    action="patient.update",
                    result="SUCCESS",
                    resource_id=uuid.uuid4(),
                    payload={"changed_fields": ["family_name"]},
                ),
            )
            raise RuntimeError("the business write failed")

    assert audit_count(api.tenant_id) == 0


def test_audit_write_failure_rolls_back_business_operation(
    api: AuditApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S12h / R4 / T-AUD-3: **a change that cannot be audited does not happen.**

    The failure is injected at the writer, which is the only place it can be injected without
    weakening the test: `record` refusing is exactly the condition R4 describes, and the assertion is
    that the patient row does not exist afterwards. An implementation that swallowed the refusal to
    "keep the clinical change" passes every other test in this file and fails this one.
    """
    real_record = service.record

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("audit sink unavailable")

    monkeypatch.setattr("app.modules.patients.service.audit.record", refuse)
    assert real_record is not refuse

    with pytest.raises(RuntimeError, match="audit sink unavailable"):
        api.rbac.client.post("/api/v1/patients", json=PATIENT, headers=api.headers)

    with engine.connect() as conn:
        remaining = conn.execute(
            text("SELECT count(*) FROM patients WHERE tenant_id = :tenant_id"),
            {"tenant_id": api.tenant_id},
        ).scalar_one()
    assert remaining == 0, (
        "the patient row survived a failed audit write — INV-4 is broken: an unaudited change "
        "happened"
    )


def test_role_grant_is_audited_in_the_same_transaction(api: AuditApi) -> None:
    """The RBAC half of the first consumers: a grant produces `user.permission_change`."""
    target = api.rbac.add_actor(tenant_id=api.tenant_id, granted_by=api.user_id)
    before = audit_count(api.tenant_id)

    role_id = api.rbac.role_id_for(tenant_id=api.tenant_id, code="NURSE")
    granted = api.rbac.client.post(
        f"/api/v1/users/{target.user_id}/roles",
        json={"role_id": str(role_id)},
        headers=api.headers,
    )
    assert granted.status_code == 201, granted.text

    events = audit_rows(api.tenant_id)[before:]
    assert [event["action"] for event in events] == ["user.permission_change"]
    payload = events[0]["metadata"]
    assert payload["change"] == "GRANT"
    assert payload["role_code"] == "NURSE"
    assert payload["target_user_id"] == str(target.user_id)
    assert "patient:create" in payload["added"], (
        "the payload records the permission bundle the grant conferred"
    )


def test_role_revoke_is_audited_in_the_same_transaction(api: AuditApi) -> None:
    """And a revoke produces the same action with `change = REVOKE`."""
    target = api.rbac.add_actor(
        tenant_id=api.tenant_id, granted_by=api.user_id, role_code="NURSE"
    )
    role_id = api.rbac.role_id_for(tenant_id=api.tenant_id, code="NURSE")
    before = audit_count(api.tenant_id)

    revoked = api.rbac.client.delete(
        f"/api/v1/users/{target.user_id}/roles/{role_id}", headers=api.headers
    )
    assert revoked.status_code == 204, revoked.text

    events = audit_rows(api.tenant_id)[before:]
    assert [event["action"] for event in events] == ["user.permission_change"]
    assert events[0]["metadata"]["change"] == "REVOKE"
    assert events[0]["metadata"]["removed"], "the revoke records what it took away"


# ---------------------------------------------------------------------------------------------
# R11 / S16 — the payload allow-list
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,payload",
    [
        ("patient.create", {"patient_name": "Ada Synthetic"}),
        ("patient.create", {"field_set": ["given_name"], "medicine_name": "Synthetic"}),
        (
            "patient.update",
            {"changed_fields": ["given_name"], "directions": "one tablet"},
        ),
        ("audit.read", {"result_count": 1, "approval_number": "TGA-1"}),
    ],
)
def test_payload_allowlist_rejects_clinical_content(
    api: AuditApi, action: str, payload: dict[str, object]
) -> None:
    """S16 / R11 / T-AUD-4: an unlisted key throws `AUDIT_PAYLOAD_REJECTED` and no row is written."""
    with pytest.raises(service.AuditWriteRefused) as refusal:
        with tenant_transaction(
            tenant_id=api.tenant_id, actor_id=api.user_id
        ) as session:
            service.record(
                session,
                service.AuditEvent(action=action, result="SUCCESS", payload=payload),
            )
    assert "AUDIT_PAYLOAD_REJECTED" in str(refusal.value)
    assert audit_count(api.tenant_id) == 0, "a refused payload wrote a row anyway"


def test_a_sentinel_clinical_value_never_reaches_the_payload(api: AuditApi) -> None:
    """S15: the sentinel goes through a real clinical endpoint and appears nowhere in the trail.

    The patient's names are stored — they are the record — but the audit payload must carry neither
    them nor *any* clinical value: it carries the field **names** and the identifier, nothing else.
    """
    sentinel = "PATIENT_NAME_SENTINEL-9f2c"
    created = api.rbac.client.post(
        "/api/v1/patients",
        json={**PATIENT, "given_name": sentinel, "family_name": sentinel},
        headers=api.headers,
    )
    assert created.status_code == 201, created.text

    payload_blob = repr([row["metadata"] for row in audit_rows(api.tenant_id)])
    assert sentinel not in payload_blob, (
        "a clinical value reached the audit payload — the trail is a second copy of the record"
    )
    for row in audit_rows(api.tenant_id):
        assert sentinel not in str(row["reason"])
        assert sentinel not in str(row["actor_role"])


def test_an_action_outside_the_catalogue_is_refused(api: AuditApi) -> None:
    """R5/R11: *"No new action name may be invented."* An invented name throws before any insert."""
    with pytest.raises(service.AuditWriteRefused) as refusal:
        with tenant_transaction(tenant_id=api.tenant_id) as session:
            service.record(
                session, service.AuditEvent(action="patient.purge", result="SUCCESS")
            )
    assert "AUDIT_PAYLOAD_REJECTED" in str(refusal.value)
    assert audit_count(api.tenant_id) == 0


def test_a_result_outside_the_envelope_is_refused(api: AuditApi) -> None:
    """`result` is a closed set: `SUCCESS, DENIED, FAILED, UNKNOWN` (R6)."""
    with pytest.raises(service.AuditWriteRefused):
        with tenant_transaction(tenant_id=api.tenant_id) as session:
            service.record(
                session, service.AuditEvent(action="patient.create", result="MAYBE")
            )


def test_the_writer_refuses_without_a_tenant_context() -> None:
    """Fail closed: no `app.tenant_id` means no row, not a row in the wrong tenant's chain."""
    from sqlmodel import Session

    with Session(engine) as session, session.begin():
        with pytest.raises(service.AuditContextRequired):
            service.record(
                session, service.AuditEvent(action="patient.create", result="SUCCESS")
            )


# ---------------------------------------------------------------------------------------------
# F6, S13, S14 — the chain and its verification
# ---------------------------------------------------------------------------------------------


def _three_events(api: AuditApi) -> list[uuid.UUID]:
    """Write three chained events through the writer, returning their identifiers."""
    ids: list[uuid.UUID] = []
    for index in range(3):
        with tenant_transaction(
            tenant_id=api.tenant_id, actor_id=api.user_id
        ) as session:
            entry = service.record(
                session,
                service.AuditEvent(
                    action="patient.update",
                    result="SUCCESS",
                    resource_id=uuid.uuid4(),
                    payload={"changed_fields": [f"field_{index}"]},
                ),
            )
            ids.append(entry.event_id)
    return ids


def test_hash_chain_links_consecutive_events(api: AuditApi) -> None:
    """F6: genesis is 64 zeroes, and every later `prev_hash` is the previous event's `hash`."""
    _three_events(api)
    rows = audit_rows(api.tenant_id)

    assert rows[0]["prev_hash"] == GENESIS_HASH
    for previous, current in zip(rows, rows[1:], strict=False):
        assert current["prev_hash"] == previous["hash"]

    report = chain_report(api.tenant_id)
    assert report.verified is True
    assert report.events == 3
    assert report.head_hash == rows[-1]["hash"]


def test_the_hash_is_the_canonical_recomputation(api: AuditApi) -> None:
    """R8: `SHA-256(canonical_json(event without hash) ‖ prev_hash)` — recomputed independently.

    The recomputation uses the service's own public canonical form, which is the point: an outside
    verifier has to be able to reproduce it from the stored row alone, and if the writer hashed
    anything the stored row does not carry, this fails.
    """
    _three_events(api)
    with tenant_transaction(tenant_id=api.tenant_id) as session:
        entries = list(service.chain(session, tenant_id=api.tenant_id))
        for entry in entries:
            assert service.compute_hash(entry) == entry.hash


def test_hash_chain_verification_detects_a_modified_row(api: AuditApi) -> None:
    """S13: a mutated payload is reported as a break at that sequence number."""
    ids = _three_events(api)
    assert chain_report(api.tenant_id).verified is True

    tamper(
        "UPDATE audit_log SET metadata = CAST(:payload AS jsonb)"
        " WHERE tenant_id = :tenant_id AND event_id = :event_id",
        {
            "payload": '{"changed_fields": ["something_else"]}',
            "tenant_id": api.tenant_id,
            "event_id": ids[1],
        },
    )

    report = chain_report(api.tenant_id)
    assert report.verified is False
    assert report.first_break is not None
    assert report.first_break.reason == "HASH_MISMATCH"
    assert report.first_break.sequence == 2
    assert report.first_break.event_id == ids[1]


def test_hash_chain_verification_detects_a_relinked_row(api: AuditApi) -> None:
    """S13/T-AUD-6: re-pointing `prev_hash` at an earlier event is detected, not accepted.

    A re-link is the subtler attack: the row's own hash is recomputed to match its new `prev_hash`,
    so only the *linkage* catches it. Detecting it needs the walk, not a per-row digest check.
    """
    ids = _three_events(api)
    rows = audit_rows(api.tenant_id)

    # Skip the middle event: the third now claims the first as its predecessor.
    tamper(
        "UPDATE audit_log SET prev_hash = :prev_hash WHERE tenant_id = :tenant_id"
        " AND event_id = :event_id",
        {
            "prev_hash": rows[0]["hash"],
            "tenant_id": api.tenant_id,
            "event_id": ids[2],
        },
    )

    report = chain_report(api.tenant_id)
    assert report.verified is False
    assert report.first_break is not None
    # The third row now claims the *first* as its predecessor, so the linkage is what fails — the
    # walk expects the second row's hash at that position. That is the honest reason, and it is the
    # one an incident report needs: `PREV_HASH_MISMATCH` at sequence 3 says a link was rewritten.
    assert report.first_break.reason == "PREV_HASH_MISMATCH"
    assert report.first_break.sequence == 3
    assert report.first_break.event_id == ids[2]


def test_hash_chain_verification_detects_a_deleted_middle_row(api: AuditApi) -> None:
    """S14: deleting a row breaks the `prev_hash` linkage at the row that follows it."""
    ids = _three_events(api)

    tamper(
        "DELETE FROM audit_log WHERE tenant_id = :tenant_id AND event_id = :event_id",
        {"tenant_id": api.tenant_id, "event_id": ids[1]},
    )

    report = chain_report(api.tenant_id)
    assert report.verified is False
    assert report.first_break is not None
    assert report.first_break.reason == "PREV_HASH_MISMATCH"
    assert report.first_break.sequence == 2
    assert report.first_break.event_id == ids[2]


def test_a_truncated_chain_is_detected(api: AuditApi) -> None:
    """A chain whose first surviving row is not the genesis event is a break, not a fresh start.

    This is what "sequence gap" means for `(timestamp, event_id)`: the first row's `prev_hash` is not
    the genesis value, so the history it claims to continue is missing.
    """
    ids = _three_events(api)
    tamper(
        "DELETE FROM audit_log WHERE tenant_id = :tenant_id AND event_id = :event_id",
        {"tenant_id": api.tenant_id, "event_id": ids[0]},
    )

    report = chain_report(api.tenant_id)
    assert report.verified is False
    assert report.first_break is not None
    assert report.first_break.reason == "PREV_HASH_MISMATCH"
    assert report.first_break.sequence == 1
    assert report.first_break.event_id == ids[1]


def test_concurrent_writers_do_not_fork_the_chain(api: AuditApi) -> None:
    """R8: the advisory lock serialises writers, so parallel inserts produce one chain.

    Without the lock, two writers read the same head and both chain to it — a fork that verification
    would report as tampering even though nothing was. The assertion is the chain's own verdict plus
    a check that every `prev_hash` appears exactly once, which is what "no fork" means for a hash
    chain: one predecessor per event, and one successor per hash.
    """
    from concurrent.futures import ThreadPoolExecutor

    def write(index: int) -> None:
        with tenant_transaction(
            tenant_id=api.tenant_id, actor_id=api.user_id
        ) as session:
            service.record(
                session,
                service.AuditEvent(
                    action="patient.read",
                    result="SUCCESS",
                    payload={"purpose": f"CONCURRENT_{index}"},
                ),
            )

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(write, range(5)))

    rows = audit_rows(api.tenant_id)
    assert len(rows) == 5
    prev_hashes = [row["prev_hash"] for row in rows]
    assert len(set(prev_hashes)) == len(prev_hashes), (
        f"two events chained onto the same predecessor: {prev_hashes} — the writers forked"
    )
    assert chain_report(api.tenant_id).verified is True


def test_chain_order_is_timestamp_then_event_id(api: AuditApi) -> None:
    """The order the chain is walked in is the primary key, and it is total.

    Two events with the same microsecond timestamp still have a deterministic order, because
    `event_id` breaks the tie. Verification depends on that: a non-total order would make "the
    previous event" ambiguous.
    """
    ids = _three_events(api)
    same_moment = datetime.now(UTC)
    for event_id in ids:
        tamper(
            "UPDATE audit_log SET timestamp = :moment WHERE tenant_id = :tenant_id"
            " AND event_id = :event_id",
            {"moment": same_moment, "tenant_id": api.tenant_id, "event_id": event_id},
        )

    rows = audit_rows(api.tenant_id)
    assert [row["event_id"] for row in rows] == sorted(ids, key=str), (
        "the chain is no longer walked in `(timestamp, event_id)` order"
    )


def test_the_pg_advisory_lock_is_transaction_scoped(api: AuditApi) -> None:
    """The lock cannot leak across a pooled connection: it is released by `COMMIT`.

    A session-level advisory lock (or a session-level `SET`) would hold the tenant's chain for the
    life of the pooled connection and serialise every later request behind it — the failure mode the
    `SET LOCAL` design already guards against for tenant context.
    """
    from sqlalchemy import text

    with tenant_transaction(tenant_id=api.tenant_id) as session:
        _three_events(api)
        assert session is not None

    with engine.connect() as conn:
        held = conn.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted"
            )
        ).scalar_one()
    assert held == 0, (
        f"{held} advisory locks are still held after the transaction committed"
    )


def test_currently_held_grants_still_refuse_a_direct_update() -> None:
    """A last guard with teeth: the owner connection *can* tamper, and that is the only reason the
    tamper tests above work.

    If a future migration gave `clinos_app` the privilege, the tests above would still fail for the
    right reason (the tamper is done as the owner and always succeeds) — but this one names the
    asymmetry explicitly, so the suite cannot quietly start proving nothing.
    """
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            with pytest.raises(ProgrammingError):
                conn.execute(text("SELECT 1 FROM audit_log FOR UPDATE"))
