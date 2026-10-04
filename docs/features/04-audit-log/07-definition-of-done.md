---
doc_id: FEAT-AUD-07
title: Audit log, definition of done
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 07-audit-architecture, 26-security-gates, 17-compliance-control-matrix
source:
  - clinic-os-secure-by-design/17-compliance-control-matrix.md
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md §3
  - clinic-os-secure-by-design/07-audit-architecture.md §3, §4, §10
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Definition of Done

The six parts are from doc 24. Tick only with a link to evidence.

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in 01-requirements.md has a passing test | [ ] | `tests/audit/` run output; F1–F12 |
| 2 | Security: single writer, RLS, deny-by-default read path, strict filter schema, no bypass route | [ ] | `tests/security/test_audit_append_only_grants.py`; S1–S16 |
| 3 | Security tests pass in CI: S1–S16, including S12a–S12d on every migration | [ ] | CI log for the release commit |
| 4 | Audit: events emitted and verified; A1–A4; `audit.read` written on every read | [ ] | Coverage test output; sample event with the full envelope |
| 5 | Operations & compliance: classification applied, `reason` never logged, residency register entry for DR-11, audit-write-failure alert live | [ ] | Alert definition; residency register entry |
| 6 | Deployment: image builds, expand-and-contract migration, `audit_log` partitions created, verified in Staging | [ ] | Migration run log; Staging grant listing |

**No part is Done with an open High or Critical finding.** T-AUD-7 (retention over-deletion) is residual
Medium and therefore **blocks part 5**: it may not be signed until OPEN-1 closes.

## Gate sign-off & Verification Governance

| Stage / Gate | What is verified | Verifier (Decision Maker) | Approver | Pass policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Grant inspection after every migration (`S12a`), refusal of `UPDATE`/`DELETE`/`TRUNCATE` (`S12b`–`S12d`), hash-chain break detection, sentinel payload test | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 2 (Database)** | The app role holds exactly `{SELECT, INSERT}` on `audit_log`; it is not the owner and has no `BYPASSRLS`; no `UPDATE` or `DELETE` policy exists; `FORCE ROW LEVEL SECURITY`; partitions present | **Security Lead** | **CTO** | **NO conditional pass — Gate 2 permits no conditional pass** |
| **Gate 4 (APIs)** | Read path authorisation, tenant scoping, filter validation, error envelope, rate limit, export scoping | **Security Lead** | **CTO** | Conditional pass only for a non-clinical read-path item with a compensating control |
| **Independent compliance** | Audit trail integrity, chain verification reports, retention schedule and legal-hold register, immutability proof for a regulator | **Compliance Lead** | **External auditor** (pre-launch / periodic) | Periodic; no pass without the verification reports |

**No self-approval.** The deliverer of the audit module never signs Gate 2 or Gate 4; the decision maker
and the approver are different named roles. Gate evidence is produced during the phase, not assembled on
gate day. A failed gate stops dependent work and is re-run.

## Control matrix rows fed by this feature

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Audit is append-only | App role holds `SELECT, INSERT` only; no `UPDATE`/`DELETE` grant and no update policy | `audit_log` grants in the migration; `core/audit.py` as the single writer | S12a–S12d; grant listing | Security Lead | planned |
| An `UPDATE`/`DELETE` against `audit_log` is refused | Database privilege, not convention | `REVOKE UPDATE, DELETE, TRUNCATE`; `42501 insufficient_privilege` | S12b–S12d | Security Lead | planned |
| Audit and the business write commit together | One transaction for the domain change, the audit event and the outbox row | transaction helper in `core/db.py`; `core/audit.py` | F1, F2 | CTO | planned |
| A failed audit write fails the operation | Fail-closed write path | `core/audit.py`; `500` + rollback | S12h | Security Lead | planned |
| Denied and failed attempts are audited | Same fidelity as success | per-module audit calls; `result = DENIED`/`FAILED` | F5; A2 | Security Lead | planned |
| No clinical content, secret or full request body in a payload | Per-action metadata allow-list by schema | `core/audit.py` payload allow-list | S15, S16 | Clinical Safety Officer | planned |
| Tamper-evident hash chaining | SHA-256 chain with a verification job | `audit` module; verification job | S13, S14 | Security Lead | planned |
| The trail survives a compromised application server | Outbox → SQS → S3 Object Lock `COMPLIANCE` in `ap-southeast-2` | audit writer; bucket policy | F11; verification report | CTO | planned |
| The audit trail is searchable for the questions asked | Tenant-scoped read with keyset pagination, filters and export rules | `/api/v1/audit*` | F7, F8, F10 | Compliance Lead | planned |
| Audit reads are themselves audited | `audit.read` on every call, including an empty result | `core/audit.py` | F9 | Security Lead | planned |
| Audit write failure is alerted | Alert on any failed audit write | alert catalogue; audit writer | A3; alert definition | Security Lead | planned |
| Audit retention and legal hold are provable | Partition-level expiry, legal-hold register, no row-level delete | `audit_log` partitions; partition job | F12; partition drop log | Head of Legal and Compliance | **REQUIRES LEGAL/REGULATORY VALIDATION** |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 retention period per event class and jurisdiction — blocks part 5 and T-AUD-7 | Head of Legal and Compliance | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OPEN-2 envelope type conflicts (`event_id` ULID vs `uuid`; `prev_hash`/`hash` type; `request_id` nullability) | Security Lead | OPEN |
| OPEN-4 ownership of the export bundle path (feature 14?) and of `audit_outbox` | Compliance Lead + CTO | OPEN |
| OPEN-5 break-glass procedure for platform staff and its approver | Security Lead | OPEN |
| OPEN-7 `tenant_id IS NULL` platform events under RLS | Security Lead + CTO | OPEN |
| `record.purged` (doc 14 §3.3) is not in the doc 07 §1 action catalogue — a certificate cannot be written until it is registered | Head of Legal and Compliance + Security Lead | OPEN |
| `audit_log` does not exist in the repo until feature 01 lands; S12a–S12d cannot run before then | Head of Platform | OPEN — dependency on feature 01 |
