"""A1-A3, S13 / R15 / INV-4 — the audit trail, written on the caller's transaction.

Design: `docs/features/06-clinical-records/05-data-and-audit.md` §"Audit event catalogue" and
§"The rule for audit metadata"; `docs/features/04-audit-log/`. The four story labels the clinical
documents name map onto the two actions doc 07 §1 already carries — `clinical_record.read` and
`clinical_record.write` — so no new action name is invented, and the events are distinguished by
their payload and envelope fields.

Assertions are delta-style: the trail is append-only, so a case filters the rows it caused by its
own tenant and never asserts an absolute count.
"""

from tests.clinical_records.conftest import ClinicalApi, ClinicalTenant, created_record
from tests.observability.log_sinks import capture_logs


def test_create_event_carries_the_envelope_and_no_clinical_text(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """A1: one event, the full envelope, identifiers only."""
    record = created_record(
        clinical.create_record(tenant.owner, tenant.patient, body="Envelope test body.")
    )

    created = [
        event
        for event in clinical.clinical_events(tenant.tenant_id)
        if event["action"] == "clinical_record.write"
        and event["result"] == "SUCCESS"
        and str(event["resource_id"]) == record["id"]
    ]
    assert len(created) == 1, created
    event = created[0]

    assert event["resource_type"] == "CLINICAL_RECORD"
    assert str(event["tenant_id"]) == str(tenant.tenant_id)
    assert str(event["actor_id"]) == str(tenant.owner.user_id)
    assert event["actor_role"] == "PRACTICE_OWNER"
    assert event["request_id"] is not None
    assert event["metadata"] == {"patient_id": str(tenant.patient), "version": 1}
    assert "Envelope test body." not in str(event["metadata"])


def test_every_action_writes_one_event(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """A1: create, read, sign and amend each emit one event carrying the action, not the narrative."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200
    assert (
        clinical.amend(
            tenant.owner,
            record["id"],
            body="Amended body.",
            amendment_reason="Amendment reason",
        ).status_code
        == 201
    )
    assert clinical.read_record(tenant.owner, record["id"]).status_code == 200

    writes = clinical.clinical_events(tenant.tenant_id, action="clinical_record.write")
    reads = clinical.clinical_events(tenant.tenant_id, action="clinical_record.read")

    # create, sign, amend — three successful writes on this record.
    assert len([row for row in writes if row["result"] == "SUCCESS"]) == 3, writes
    assert len([row for row in reads if row["result"] == "SUCCESS"]) == 1, reads

    amendment = [row for row in writes if row["reason"] == "AMENDMENT"]
    assert len(amendment) == 1, writes
    assert amendment[0]["metadata"] == {
        "patient_id": str(tenant.patient),
        "version": 2,
        "supersedes_version": 1,
    }
    # The clinician's typed reason is never in the audit payload.
    assert "Amendment reason" not in str(amendment[0]["metadata"])


def test_a_missing_permission_is_audited_as_denied(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """A2: a refusal is recorded with the same fidelity as a success."""
    pharmacy = clinical.add_actor(session=tenant.owner, role_code="PHARMACY")

    refused = clinical.read_record(pharmacy, "00000000-0000-0000-0000-000000000000")
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "PERMISSION_NOT_HELD"

    denied = [
        row
        for row in clinical.clinical_events(tenant.tenant_id)
        if row["result"] == "DENIED"
    ]
    assert len(denied) == 1, denied
    assert denied[0]["action"] == "clinical_record.read"
    assert denied[0]["reason"] == "AUTHZ_DENIED"
    assert str(denied[0]["actor_id"]) == str(pharmacy.user_id)


def test_cross_tenant_denial_audited_with_equal_fidelity(
    clinical: ClinicalApi, two_tenants: tuple[ClinicalTenant, ClinicalTenant]
) -> None:
    """S13 / R10: the substituted identifier is recorded in the *caller's* trail."""
    first, second = two_tenants
    record = created_record(clinical.create_record(first.owner, first.patient))

    assert clinical.read_record(second.owner, record["id"]).status_code == 404
    assert clinical.sign(second.owner, record["id"]).status_code == 404

    denied = [
        row
        for row in clinical.clinical_events(second.tenant_id)
        if row["result"] == "DENIED"
    ]
    assert len(denied) == 2, denied
    assert {row["action"] for row in denied} == {
        "clinical_record.read",
        "clinical_record.write",
    }
    assert {row["reason"] for row in denied} == {"AUTHZ_DENIED_CROSS_TENANT"}

    # The first tenant's own trail has no denial for its own record.
    assert not [
        row
        for row in clinical.clinical_events(first.tenant_id)
        if row["result"] == "DENIED"
    ]


def test_audit_write_failure_blocks_the_clinical_write(
    clinical: ClinicalApi, tenant: ClinicalTenant, monkeypatch
) -> None:
    """A3 / S12 / INV-4: a write that cannot be audited does not happen."""
    from app.modules.audit.service import AuditWriteRefused
    from app.modules.clinical_records import service as clinical_service

    def refuse(_session: object, _event: object) -> None:
        raise AuditWriteRefused("AUDIT_PAYLOAD_REJECTED: injected failure")

    monkeypatch.setattr(clinical_service.audit, "record", refuse)

    with capture_logs() as sink:
        response = clinical.create_record(
            tenant.owner, tenant.patient, body="This write must not survive."
        )

    assert response.status_code == 500, response.text
    # The clinical row and its version were rolled back with the audit row.
    assert clinical.row_counts(tenant.tenant_id) == (0, 0)
    # And the failure response carries no narrative and no internals.
    assert "This write must not survive." not in response.text
    assert "Traceback" not in response.text
    assert "This write must not survive." not in sink.raw


def test_the_two_action_names_are_in_the_closed_catalogue() -> None:
    """The action names and payload keys this module emits are registered, not invented."""
    from app.modules.audit.actions import ACTIONS, PAYLOAD_ALLOW_LIST, PAYLOAD_KEYS

    assert "clinical_record.read" in ACTIONS
    assert "clinical_record.write" in ACTIONS
    assert PAYLOAD_ALLOW_LIST["clinical_record.write"] == {
        "patient_id",
        "version",
        "supersedes_version",
    }
    assert PAYLOAD_ALLOW_LIST["clinical_record.read"] <= PAYLOAD_KEYS
