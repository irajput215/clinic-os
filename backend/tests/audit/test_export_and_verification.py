"""F10, F11, S9, R9, R10 — the compliance export and the verification entry point.

`docs/features/04-audit-log/06-test-plan.md` F10 (*"Export a range: tenant-scoped CSV/JSONL bundle …
`audit.read` with `reason = EXPORT`"*), F11 (the outbox drains every committed event) and R9
(continuous and full-chain verification).

**What is tested is the bundle, not the bucket.** `04-design.md` §"Immutable export path" requires S3
Object Lock in `ap-southeast-2` in `COMPLIANCE` mode, which needs a bucket, credentials and a runtime
dependency this slice does not have. The export *function* and its manifest are implemented; the
adapter is a documented seam that refuses rather than pretending
(`app/modules/audit/archive.py`). These tests prove the half that exists and pin the half that does
not, so nobody can read "the export works" into a green suite.
"""

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import tenant_transaction
from app.modules.audit import service
from app.modules.audit.archive import (
    NOT_CONFIGURED,
    AuditArchiveNotConfigured,
    S3ObjectLockSink,
)
from app.modules.audit.models import GENESIS_HASH
from tests.audit.conftest import AuditApi, audit_rows, chain_report, tamper

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PATIENTS = f"{settings.API_V1_STR}/patients"


def _seed(api: AuditApi, count: int = 2) -> list[uuid.UUID]:
    """Two audited writes through the API, returning the event ids they produced."""
    for index in range(count):
        response = api.rbac.client.post(
            PATIENTS,
            json={
                "given_name": f"Export{index}",
                "family_name": "Synthetic",
                "date_of_birth": "1990-01-01",
            },
            headers=api.headers,
        )
        assert response.status_code == 201, response.text
    return [row["event_id"] for row in audit_rows(api.tenant_id)]


# ---------------------------------------------------------------------------------------------
# F10 — the bundle
# ---------------------------------------------------------------------------------------------


def test_export_bundle_is_tenant_scoped(api: AuditApi) -> None:
    """F10: canonical JSONL of this tenant's chain, plus a manifest carrying the head hash."""
    _seed(api, 2)

    with tenant_transaction(tenant_id=api.tenant_id) as session:
        bundle = service.export_chain(session, tenant_id=api.tenant_id)

    lines = [line for line in bundle.jsonl.decode("utf-8").splitlines() if line]
    assert len(lines) == len(audit_rows(api.tenant_id))

    # Every line is canonical JSON: sorted keys, no insignificant whitespace. That is what makes the
    # bundle verifiable by something which is not this application.
    for line in lines:
        decoded = json.loads(line)
        assert service.canonical_json(decoded) == line, (
            "the exported line is not the canonical serialisation of its own content"
        )
        assert str(decoded["tenant_id"]) == str(api.tenant_id)
        assert "hash" not in decoded, (
            "the hash is not part of the payload it is computed over; the manifest carries it"
        )
        assert "prev_hash" in decoded, (
            "the linkage is exported, so an offline checker can walk the chain without the database"
        )

    manifest = bundle.manifest
    assert manifest["tenant_id"] == str(api.tenant_id)
    assert manifest["event_count"] == len(lines)
    assert str(manifest["head_hash"]) == audit_rows(api.tenant_id)[-1]["hash"], (
        "the manifest's head hash must be the chain's head, not a summary of the window"
    )
    assert manifest["chain_verified"] is True
    assert manifest["bundle_sha256"], (
        "the manifest carries a digest of the bytes it describes"
    )


def test_export_refuses_a_broken_chain(api: AuditApi) -> None:
    """`04-design.md`: *"a break stops the upload"* — the refusal is in the export, not the caller."""
    ids = _seed(api, 3)
    tamper(
        "UPDATE audit_log SET result = 'FAILED' WHERE tenant_id = :tenant_id AND event_id = :event_id",
        {"tenant_id": api.tenant_id, "event_id": ids[1]},
    )

    with pytest.raises(
        service.AuditWriteRefused, match="refusing to export a broken chain"
    ):
        with tenant_transaction(tenant_id=api.tenant_id) as session:
            service.export_chain(session, tenant_id=api.tenant_id)


def test_export_window_is_half_open_and_keeps_its_linkage(api: AuditApi) -> None:
    """A ranged export reports the linkage it inherited rather than pretending to be genesis."""
    _seed(api, 3)
    rows = audit_rows(api.tenant_id)
    after_first = rows[0]["timestamp"] + timedelta(microseconds=1)

    with tenant_transaction(tenant_id=api.tenant_id) as session:
        bundle = service.export_chain(
            session, tenant_id=api.tenant_id, from_timestamp=after_first
        )

    assert bundle.manifest["event_count"] == 2
    assert bundle.manifest["window_prev_hash"] == rows[0]["hash"], (
        "a window that starts mid-chain must carry the hash it continues from"
    )
    assert bundle.manifest["head_hash"] == rows[-1]["hash"]


def test_a_full_export_starts_at_genesis(api: AuditApi) -> None:
    _seed(api, 1)
    with tenant_transaction(tenant_id=api.tenant_id) as session:
        bundle = service.export_chain(session, tenant_id=api.tenant_id)
    assert bundle.manifest["window_prev_hash"] == GENESIS_HASH


def test_write_bundle_writes_both_files(api: AuditApi, tmp_path: Path) -> None:
    """The local delivery path: the JSONL and its manifest, written together."""
    _seed(api, 1)
    with tenant_transaction(tenant_id=api.tenant_id) as session:
        bundle = service.export_chain(session, tenant_id=api.tenant_id)

    jsonl_path, manifest_path = service.write_bundle(str(tmp_path), bundle)
    assert Path(jsonl_path).read_bytes() == bundle.jsonl
    written = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert written["head_hash"] == bundle.manifest["head_hash"]


# ---------------------------------------------------------------------------------------------
# R10 — the gap, pinned so it cannot be mistaken for done
# ---------------------------------------------------------------------------------------------


def test_the_s3_object_lock_adapter_refuses_rather_than_pretending(
    api: AuditApi,
) -> None:
    """R10's delivery is **not wired**, and this test is the evidence.

    The adapter exists so the specification has one place to land (bucket, prefix, write-only role,
    Object Lock). Until it has a bucket and credentials it raises, because the alternative — a
    successful no-op — would record an export that never left the host, which is worse than an
    outage: an outage is visible.
    """
    _seed(api, 1)
    with tenant_transaction(tenant_id=api.tenant_id) as session:
        bundle = service.export_chain(session, tenant_id=api.tenant_id)

    sink = S3ObjectLockSink(bucket="clinos-audit-lockbox")
    with pytest.raises(AuditArchiveNotConfigured) as refusal:
        service.archive(sink, bundle)
    assert NOT_CONFIGURED in str(refusal.value)
    assert sink.region == "ap-southeast-2", (
        "the design's region is the default, never a guess"
    )


# ---------------------------------------------------------------------------------------------
# R9 — the verification entry point
# ---------------------------------------------------------------------------------------------


def test_verify_audit_chain_entry_point_reports_ok(api: AuditApi) -> None:
    """R9: the runnable entry point a 15-minute scheduler would call, for one tenant."""
    _seed(api, 2)
    completed = subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "verify_audit_chain.py"),
            "--tenant",
            str(api.tenant_id),
            "--json",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report["verified"] is True
    assert report["events"] == 2
    assert report["head_hash"] == audit_rows(api.tenant_id)[-1]["hash"]
    assert report["report_sha256"], "the report carries a self-digest"


def test_verify_audit_chain_entry_point_exits_1_on_a_break(api: AuditApi) -> None:
    """A break is a P1, and the exit code is how a scheduler raises one — never a zero exit."""
    ids = _seed(api, 3)
    tamper(
        "UPDATE audit_log SET reason = 'tampered' WHERE tenant_id = :tenant_id"
        " AND event_id = :event_id",
        {"tenant_id": api.tenant_id, "event_id": ids[1]},
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "verify_audit_chain.py"),
            "--tenant",
            str(api.tenant_id),
            "--json",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1, (completed.stdout, completed.stderr)
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report["verified"] is False
    assert report["first_break"]["sequence"] == 2
    assert report["first_break"]["reason"] == "HASH_MISMATCH"


def test_verify_audit_chain_entry_point_refuses_a_malformed_tenant() -> None:
    """Fail closed: an input the run cannot evaluate is exit `2`, never "assume intact"."""
    completed = subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "verify_audit_chain.py"),
            "--tenant",
            "not-a-uuid",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2, (completed.stdout, completed.stderr)


def test_the_verification_covers_every_tenant_with_events(api: AuditApi) -> None:
    """The full-chain job's enumeration, which is the one query that crosses tenants."""
    _seed(api, 1)
    from sqlmodel import Session

    from app.core.db import engine

    with Session(engine) as session:
        enumerated = service.tenant_ids(session)
    assert api.tenant_id in enumerated, (
        "a tenant with events was not enumerated, so the scheduled full-chain job would skip it"
    )


def test_a_chain_is_reported_intact_after_an_audited_read(api: AuditApi) -> None:
    """The chain stays verifiable across the read path too: reading is itself an event."""
    _seed(api, 1)
    response = api.rbac.client.get(
        f"{settings.API_V1_STR}/audit/events",
        params={"action": "patient.create"},
        headers=api.headers,
    )
    assert response.status_code == 200, response.text
    report = chain_report(api.tenant_id)
    assert report.verified is True, (
        f"the chain broke at {report.first_break} — the read path writes an unchained event"
    )
    assert report.events == len(audit_rows(api.tenant_id))


def test_the_export_and_the_database_agree_on_the_head(api: AuditApi) -> None:
    """US-5: *"the exported JSONL sequence carries the same chain as the database"*."""
    _seed(api, 3)
    with tenant_transaction(tenant_id=api.tenant_id) as session:
        bundle = service.export_chain(session, tenant_id=api.tenant_id)
        report = service.verify_chain(session, tenant_id=api.tenant_id)

    assert bundle.manifest["head_hash"] == report.head_hash

    # Walk the exported lines independently, as an offline checker would: recompute each event's
    # hash from its own exported content and the previous line's hash.
    previous = GENESIS_HASH
    for line in (line for line in bundle.jsonl.decode().splitlines() if line):
        decoded = json.loads(line)
        assert decoded["prev_hash"] == previous
        entry = service.AuditLogEntry(
            event_id=uuid.UUID(decoded["event_id"]),
            timestamp=datetime.fromisoformat(decoded["timestamp"]).replace(tzinfo=UTC),
            tenant_id=None
            if decoded["tenant_id"] is None
            else uuid.UUID(decoded["tenant_id"]),
            actor_id=None
            if decoded["actor_id"] is None
            else uuid.UUID(decoded["actor_id"]),
            actor_role=decoded["actor_role"],
            action=decoded["action"],
            resource_type=decoded["resource_type"],
            resource_id=(
                None
                if decoded["resource_id"] is None
                else uuid.UUID(decoded["resource_id"])
            ),
            result=decoded["result"],
            reason=decoded["reason"],
            source_ip=decoded["source_ip"],
            request_id=decoded["request_id"],
            correlation_id=decoded["correlation_id"],
            prev_hash=decoded["prev_hash"],
            hash="",
            payload=decoded["metadata"],
        )
        previous = service.compute_hash(entry)

    assert previous == report.head_hash, (
        "the exported bundle's recomputed head does not match the database's — the bundle is not a "
        "faithful copy of the chain"
    )
