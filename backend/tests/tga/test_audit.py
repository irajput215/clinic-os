"""Audit: every transition through the merged Feature 04 writer, in the caller's transaction.

INV-4, A1-A3, T2-40. Two properties are asserted, and they are different properties:

* **coverage** — every state change and every verification emits exactly one event, with the action
  name the platform's **closed** catalogue declares (`app/modules/audit/actions.py`). The feature
  document's own `approval.created` / `approval.verified` names are not in that catalogue, so a
  writer that emitted them would refuse the write at runtime; this test pins the names that are
  actually in it.
* **atomicity** — an audit write that fails takes the clinical change with it. That is the one
  property that cannot be observed from a passing request, so it is provoked by breaking the writer.
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.modules.audit import service as audit_service
from app.modules.audit.actions import ACTIONS
from app.modules.tga_approvals import service
from tests.tga.conftest import TenantWithPatient, TgaApi

CREATED = "tga_approval.create"
VERIFIED = "tga_approval.verify"
STATE_CHANGE = "tga_approval.state_change"
MATCHED = "tga_approval.match"


def _event_count(tenant_id: uuid.UUID) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM tga_approval_events WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )


def test_the_actions_this_module_emits_are_in_the_closed_catalogue() -> None:
    """A name outside the catalogue is refused by the writer — so this is checked before emitting."""
    assert {CREATED, VERIFIED, STATE_CHANGE, MATCHED} <= ACTIONS


def test_every_state_change_and_verification_is_audited(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """A1, T2-40: one event per action, with the actor, the tenant and the resource."""
    assert clinic.owner.tenant_id is not None
    tenant_id = clinic.owner.tenant_id
    verifier = api.second_clinician(owner=clinic.owner)

    created = api.create(clinic.owner, clinic.patient_id)
    assert api.activate(clinic.owner, created, verifier=verifier).status_code == 200
    assert api.revoke(clinic.owner, created["id"]).status_code == 200

    second = api.create(
        clinic.owner, clinic.patient_id, approval_reference="TGA-2026-000401"
    )
    assert api.activate(clinic.owner, second, verifier=verifier).status_code == 200
    assert api.match(clinic.owner, clinic.patient_id, date_of_service="2026-06-01").status_code == 200

    created_events = api.audit_events(tenant_id=tenant_id, action=CREATED)
    assert len(created_events) == 2
    assert all(event["result"] == "SUCCESS" for event in created_events)

    verified_events = api.audit_events(tenant_id=tenant_id, action=VERIFIED)
    assert [event["resource_id"] for event in verified_events] == [
        uuid.UUID(created["id"]),
        uuid.UUID(second["id"]),
    ]
    assert all(event["actor_id"] == verifier.user_id for event in verified_events)

    state_changes = api.audit_events(tenant_id=tenant_id, action=STATE_CHANGE)
    assert [event["resource_id"] for event in state_changes] == [uuid.UUID(created["id"])]
    assert all(event["actor_id"] == clinic.owner.user_id for event in state_changes)

    matches = api.audit_events(tenant_id=tenant_id, action=MATCHED)
    assert len(matches) == 1
    assert all(event["tenant_id"] == tenant_id for event in matches)


def test_the_expiry_sweep_audits_each_row_it_moves(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """A system transition has no human actor, and it is still audited."""
    assert clinic.owner.tenant_id is not None
    verifier = api.second_clinician(owner=clinic.owner)
    approval = api.create(
        clinic.owner,
        clinic.patient_id,
        valid_from="2025-01-01",
        valid_to="2025-06-01",
    )
    assert api.activate(clinic.owner, approval, verifier=verifier).status_code == 200

    assert service.expire_due_approvals(tenant_id=clinic.owner.tenant_id) == 1
    events = [
        event
        for event in api.audit_events(
            tenant_id=clinic.owner.tenant_id, action=STATE_CHANGE
        )
        if event["resource_id"] == uuid.UUID(approval["id"])
    ]
    assert len(events) == 1
    assert events[0]["actor_id"] is None


def test_a_failed_audit_write_takes_the_change_with_it(
    api: TgaApi, clinic: TenantWithPatient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A3, INV-4: the audit row and the clinical row commit together or not at all."""
    assert clinic.owner.tenant_id is not None
    tenant_id = clinic.owner.tenant_id
    before_approvals = api.approval_count(tenant_id)
    before_events = _event_count(tenant_id)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the audit store is unavailable")

    # The writer is the platform's, and it is reached through the audit module's facade — the same
    # seam the service uses, broken in the same place a database outage would break it.
    monkeypatch.setattr(audit_service, "record", refuse)

    with pytest.raises(RuntimeError):
        api.create_raw(clinic.owner, clinic.patient_id)

    monkeypatch.undo()
    assert api.approval_count(tenant_id) == before_approvals, (
        "an approval was committed without its audit event"
    )
    assert _event_count(tenant_id) == before_events, (
        "a lifecycle row was committed without its audit event"
    )
