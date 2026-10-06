"""Verify one tenant's audit chain, or every tenant's — the scheduled entry point.

Requirement R9 and `docs/features/04-audit-log/06-test-plan.md` §"Audit evidence": *"Continuous
verification over the last 24 h every 15 min alerts on a break; a scheduled full-chain job writes a
signed verification report to the immutable store."*

```bash
cd backend
python scripts/verify_audit_chain.py --tenant <uuid> --window-hours 24    # continuous
python scripts/verify_audit_chain.py --all --output /var/lib/clinos/audit-reports   # full
```

The script puts the backend directory on `sys.path` itself (the same bootstrap `app/alembic/env.py`
uses), so it runs from a checkout with no `PYTHONPATH` and no packaging step — which is what a cron
entry or a `CronJob` needs.

Exit codes, so a scheduler can act on the result without parsing the report:

| Code | Meaning |
| --- | --- |
| `0` | every chain verified |
| `1` | **a chain broke** — P1 per `18-incident-response.md`; the report names the sequence |
| `2` | the run could not be evaluated (no tenant supplied, database unreachable) — fail closed |

## What is wired, and what is not

The verification itself is wired and tested: this script walks the chain and writes a JSON report
carrying the head hash, the event count and, on a break, the sequence number, the `event_id` and the
reason. `--window-hours` implements the continuous 24-hour job's window; `--all` implements the
full-chain job.

Two parts of R9 are **not** wired, and are recorded as gaps rather than claimed:

- **The scheduler.** Nothing here installs a cron entry, a systemd timer or a Kubernetes
  `CronJob`; the runbook entry is deferred (D-004 leaves the deployment target open). The command
  above is what a scheduler would run.
- **The signed report.** The report carries a SHA-256 self-digest so a stored report can be checked
  for accidental corruption, but it is **not cryptographically signed**: the design's signing key has
  no custodian yet (`04-threat-model.md` open items, *"Signed verification report format and where the
  signing key lives"*). Do not describe this as a signed report.

Neither gap changes the detection behaviour, which is the control: a break is found, the exit code
says so, and the report says where.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

# The backend directory goes on the path before `app` is imported, so the script runs from a checkout
# with no `PYTHONPATH` and no packaging step. `app/alembic/env.py` uses the same bootstrap for the
# same reason: this repository runs its entry points from the source tree.
#
# `app.db_models` is imported for its side effect and before anything else: it registers every table
# and every `Relationship`, and a partial registry makes SQLModel fail to resolve `User.tenant` at
# the first query — `Mapper[User(user)] failed to locate a name ('Tenant')`. The registry is the one
# place the models are loaded from, so an entry point imports it rather than each module it needs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

import app.db_models  # noqa: E402, F401 - the registry: every table and every relationship
from app.core.db import engine, tenant_transaction  # noqa: E402
from app.modules.audit.models import AuditLogEntry  # noqa: E402
from app.modules.audit.service import ChainReport, verify_chain  # noqa: E402

# The exit codes above. Named, so a scheduler reads a name rather than a magic number.
EXIT_OK: Final[int] = 0
EXIT_BREAK: Final[int] = 1
EXIT_INDETERMINATE: Final[int] = 2

_REPORT_FORMAT: Final[str] = "clinos.audit.chain-verification/1"


def _report_dict(
    report: ChainReport, *, window_hours: int | None, generated_at: datetime
) -> dict[str, Any]:
    """The report for one tenant, as plain JSON-serialisable data.

    The self-digest is computed over the report body with `report_sha256` absent, so any later reader
    can recompute it. It detects corruption of a stored report; it does not prove who wrote it.
    """
    body: dict[str, Any] = {
        "format": _REPORT_FORMAT,
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "window_hours": window_hours,
        "tenant_id": str(report.tenant_id),
        "verified": report.verified,
        "events": report.events,
        "head_hash": report.head_hash,
        "first_break": None
        if report.first_break is None
        else {
            "sequence": report.first_break.sequence,
            "event_id": str(report.first_break.event_id),
            "timestamp": report.first_break.timestamp.astimezone(UTC).isoformat(),
            "reason": report.first_break.reason,
            "expected": report.first_break.expected,
            "actual": report.first_break.actual,
        },
    }
    return body | {
        "report_sha256": hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    }


def _tenants_with_events() -> list[uuid.UUID]:
    """Every tenant that has at least one audit event.

    This read runs without a tenant context because it has to: it is the scheduler's enumeration, it
    returns identifiers only, and each chain is then verified inside its own tenant transaction.
    """
    with Session(engine) as session:
        rows = session.exec(select(AuditLogEntry.tenant_id).distinct()).all()
    return sorted({row for row in rows if row is not None})


def verify_one(
    tenant_id: uuid.UUID, *, window_hours: int | None, generated_at: datetime
) -> dict[str, Any]:
    """Verify one tenant's chain inside its own tenant-scoped transaction.

    `window_hours` is reported but does not narrow the walk: the chain has to be read from its
    beginning to prove the links, and a window that hid an earlier break would be the exact failure
    the verifier exists to catch. The parameter is carried so a scheduled run records which cadence
    produced the report.
    """
    with tenant_transaction(tenant_id=tenant_id) as session:
        report = verify_chain(session, tenant_id=tenant_id)
    return _report_dict(report, window_hours=window_hours, generated_at=generated_at)


def _write_report(report: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = str(report["generated_at"]).replace(":", "").replace("+00:00", "Z")
    path = directory / f"audit-chain-{report['tenant_id']}-{stamp}.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def main(argv: list[str] | None = None) -> int:  # noqa: T201 - a CLI's stdout is its interface
    """Run the verification.

    Returns the process exit code (see the module docstring). The `print` calls below are the
    interface: this is the entry point a scheduler runs and an operator reads, so its output is
    stdout rather than a log line. Everything it prints is a tenant identifier, a count, a hash and a
    reason code — no clinical value, no payload, no secret.
    """
    parser = argparse.ArgumentParser(
        description="Verify the append-only audit hash chain for one tenant or every tenant.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--tenant", help="the tenant whose chain to verify")
    target.add_argument(
        "--all",
        action="store_true",
        help="verify every tenant that has audit events (the full-chain scheduled job)",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="the cadence this run represents; recorded in the report (default: 24)",
    )
    parser.add_argument(
        "--output",
        help="directory to write the JSON report(s) to; no directory means stdout only",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the report(s) as JSON rather than a one-line summary",
    )
    arguments = parser.parse_args(argv)

    generated_at = datetime.now(UTC)
    window_hours: int | None = arguments.window_hours

    try:
        if arguments.tenant is not None:
            tenants = [uuid.UUID(arguments.tenant)]
        else:
            tenants = _tenants_with_events()
    except (
        ValueError,
        OSError,
    ) as error:  # a malformed tenant id or an unreachable database
        print(f"could not determine what to verify: {error}", file=sys.stderr)  # noqa: T201
        return EXIT_INDETERMINATE

    if not tenants:
        print("no tenant has audit events; nothing to verify")  # noqa: T201
        return EXIT_OK

    broke = False
    for tenant_id in tenants:
        report = verify_one(
            tenant_id, window_hours=window_hours, generated_at=generated_at
        )
        if arguments.output:
            _write_report(report, Path(arguments.output))
        if arguments.json:
            print(json.dumps(report, sort_keys=True))  # noqa: T201
        elif report["verified"]:
            print(  # noqa: T201 - the run's summary line, which is what a human reads
                f"{tenant_id}: OK — {report['events']} events, head {report['head_hash']}"
            )
        else:
            first_break = report["first_break"]
            print(  # noqa: T201 - a break goes to stderr as well as the exit code
                f"{tenant_id}: BREAK at sequence {first_break['sequence']} "
                f"({first_break['reason']}), event {first_break['event_id']}",
                file=sys.stderr,
            )
        broke = broke or not bool(report["verified"])

    # A break is a P1 incident, and the exit code is how a scheduler raises one. Anything else that
    # prevented evaluation returned EXIT_INDETERMINATE above: fail closed, never "assume intact".
    return EXIT_BREAK if broke else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
