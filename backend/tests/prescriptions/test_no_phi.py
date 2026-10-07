"""INV-5 for prescriptions: clinical content reaches no log sink and no audit payload.

FEAT-10 A4/A5, FEAT-11 S13. Sentinels in every HIGHLY_SENSITIVE field are pushed through stage, sign
(refused and allowed), dispatch and a validation refusal, with the root logger at `DEBUG`; then every
audit row the tenant has is inspected.
"""

import json

from sqlalchemy import text

from app.core.db import engine
from tests.observability.log_sinks import capture_logs
from tests.prescriptions.conftest import Clinic, RxApi

SENTINELS = {
    "medicine_name": "QZQZ Medicina",
    "dose_instruction": "QZQZ take with QZQZ",
    "triage_outcome": "QZQZ triage verdict",
    "conventional_therapy": "QZQZ prior therapy",
}


def test_no_clinical_value_in_logs_or_audit(rx: RxApi, clinic: Clinic) -> None:
    with capture_logs(envelope_filter=False) as sink:
        refused = rx.stage(clinic, **SENTINELS)
        assert rx.sign_raw(clinic.owner, refused["id"]).status_code == 422
        rx.approve(clinic)
        assert rx.sign_raw(clinic.owner, refused["id"]).status_code == 200
        assert rx.dispatch_raw(clinic.owner, refused["id"]).status_code == 202
        assert rx.stage_raw(clinic.owner, clinic, **SENTINELS, quantity="0").status_code == 422
        assert rx.list(clinic.owner).status_code == 200
    raw = sink.raw
    assert "QZQZ" not in raw
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT metadata, reason FROM audit_log WHERE tenant_id = :t"),
            {"t": clinic.owner.tenant_id},
        ).all()
    assert rows
    assert "QZQZ" not in json.dumps([[row[0], row[1]] for row in rows])
