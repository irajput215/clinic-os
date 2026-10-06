"""S12 / R15 / INV-5 — the narrative never reaches a log, an audit row or an error response.

Design: `docs/features/06-clinical-records/05-data-and-audit.md` §"Field classification" and
§"The rule for audit metadata"; threat T-CLIN-08. `body` is `HIGHLY_SENSITIVE`: it is excluded from
application logs, analytics, telemetry and error responses, and the audit event records *that* an
action happened — identifiers and version numbers, never clinical text.

The sink is the application's own pipeline (`tests/observability/log_sinks.py` builds the shipped
`JSONFormatter` plus `RedactionFilter` and `EnvelopeFilter`), attached at `DEBUG`, which is the
widest view available. A passing test therefore means the process never said the sentinel — not that
a filter removed it afterwards.
"""

import json

from tests.clinical_records.conftest import (
    SENTINEL,
    ClinicalApi,
    ClinicalTenant,
    created_record,
)
from tests.observability.log_sinks import capture_logs


def test_narrative_never_reaches_logs_or_audit(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """S12: the sentinel narrative and the sentinel amendment reason appear in neither sink."""
    narrative = f"{SENTINEL} narrative about a synthetic patient"
    amendment = f"{SENTINEL} amended narrative"
    reason = f"reason-{SENTINEL}"

    with capture_logs() as sink:
        record = created_record(
            clinical.create_record(tenant.owner, tenant.patient, body=narrative)
        )
        assert clinical.sign(tenant.owner, record["id"]).status_code == 200
        assert (
            clinical.amend(
                tenant.owner,
                record["id"],
                body=amendment,
                amendment_reason=reason,
            ).status_code
            == 201
        )
        assert clinical.read_record(tenant.owner, record["id"]).status_code == 200
        assert clinical.timeline(tenant.owner, tenant.patient).status_code == 200
        assert clinical.read_version(tenant.owner, record["id"], 2).status_code == 200
        # A refusal path as well: the denied event must not carry the text either.
        assert (
            clinical.patch_record(
                tenant.owner, record["id"], body=f"{SENTINEL} refused"
            ).status_code
            == 403
        )
        # And a validation failure on a body that carries the sentinel.
        assert (
            clinical.create_record(
                tenant.owner,
                tenant.patient,
                body=f"{SENTINEL} invalid",
                tenant_id=str(tenant.tenant_id),
            ).status_code
            == 422
        )

    assert SENTINEL not in sink.raw, "the narrative reached a log sink"

    rows = clinical.audit_rows(tenant.tenant_id)
    assert rows, "no audit rows were written, so the audit half of this test is vacuous"
    actions = [row["action"] for row in rows]
    assert "clinical_record.write" in actions
    assert "clinical_record.read" in actions
    # The reason the amendment event carries is a controlled code, never the clinician's text.
    #
    # Only the writes that *succeeded*: the refusal path records `clinical_record.write` too, and it
    # legitimately carries the machine-readable code the refusal returned (`NOTE_ALREADY_SIGNED`) as
    # its reason. Both are controlled codes. The event this assertion is about is the amendment — the
    # one write that is handed a clinician's free-text reason and must not store it.
    amendment_events = [
        row
        for row in rows
        if row["action"] == "clinical_record.write"
        and row["result"] == "SUCCESS"
        and row["reason"] is not None
    ]
    assert amendment_events, "the amendment event was not written"
    for row in amendment_events:
        assert row["reason"] == "AMENDMENT"

    for row in rows:
        assert SENTINEL not in json.dumps(row, default=str), row


def test_the_database_holds_the_narrative_and_nothing_else_does(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """The narrative is stored once, in `body` — no copy in the audit row, no SOAP column."""
    narrative = f"{SENTINEL} stored once"
    record = created_record(
        clinical.create_record(tenant.owner, tenant.patient, body=narrative)
    )

    rows = clinical.version_rows(tenant.tenant_id, record["id"])
    assert [row["body"] for row in rows] == [narrative]

    for row in clinical.audit_rows(tenant.tenant_id):
        assert row["metadata"] is None or "body" not in json.dumps(row["metadata"])
