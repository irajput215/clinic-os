---
doc_id: FEAT-DOC-07
title: Documents, definition of done
owner: Head of Platform
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 21-technical-design, 12-data-classification
---

# Documents: definition of done

The six parts below are the standard parts. Tick only with a link to evidence.

| # | Part | Done | Evidence |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in `01-requirements.md` (R1–R11) has a passing test | [ ] | F1–F13 output in the CI run for the release commit |
| 2 | Security: deny-by-default request path, RLS, server-side key generation, 300 s mint, strict schema, scan gate implemented | [ ] | `03-design.md` reviewed against the merged diff; S1–S22 green |
| 3 | Security tests pass in CI: S1–S22, including the `I-013`/`I-014` cross-tenant key rows in Staging | [ ] | CI run URL; Staging run URL for S4 and S14 |
| 4 | Audit: `document.uploaded`, `document.viewed`, `document.scan_failed`, `document.deleted` registered in `07 §1` and emitted; A1–A3 pass | [ ] | `07-audit-architecture.md` §1 diff; A1–A3 output |
| 5 | Operations and compliance: classification applied, no content or filename in logs, residency register updated, alerts wired to the CSO for scan failure and hash mismatch | [ ] | Log sample review; residency register row; alert rule export |
| 6 | Deployment: image builds, scans clean, migration is expand-and-contract, verified in Staging against a real bucket | [ ] | Image digest and scan report; migration output; Staging verification note |

**No part is Done with an open High or Critical finding.**

## Gate sign-off and Verification Governance

| Stage | What is verified | Decision maker | Approver | Pass policy |
| --- | --- | --- | --- | --- |
| CI / automated | RLS on `documents`, no `DELETE` grant, `documents_events` append-only, schema lint for a missing policy | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 2 (Database)** | `documents` policy with `USING` and `WITH CHECK`, `FORCE ROW LEVEL SECURITY`, `clinos_app` is not the owner and has no `BYPASSRLS`, no `DELETE` or `TRUNCATE` grant, bucket-prefix constraint | **Security Lead** | **CTO** | **❌ NO conditional pass permitted.** Tenant isolation is the control the model depends on; a partial pass is a failed gate (`gates.md` Gate 2) |
| **Gate 4 (APIs)** | Per-request authorisation before the mint, 300 s TTL, key bound to the exact object, scan-state gate, upload validation, `404` not `403` across tenants, SSRF probe, rate limits | **Security Lead** | **CTO**, plus the **Clinical Safety Officer** where the scan-state gate is in scope | **❌ No conditional pass for the scan-state gate.** Conditional pass only for a non-clinical endpoint with a documented compensating control |
| Independent compliance | Audit event names registered, append-only proof, retention and residency position, immutability of stored objects | **Privacy Officer / Compliance Lead** | **External auditor** | Periodic / pre-launch |

**No self-approval.** The person who delivered the work never signs its gate; the deliverer and the
approver are different named roles. Gate 2 evidence is produced during the phase, not assembled on
gate day.

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Documents are stored privately | Private bucket, Block Public Access, SSE-KMS, versioning, no public objects | Bucket configuration and bucket policy | S16; configuration review | Head of Platform | planned |
| Documents are served only by a short-lived, tenant-scoped URL | Mint after an authorisation check; TTL exactly 300 s; bound to the exact key; issued per request and logged | `documents` module presign path | S1–S4, S7 | Security Lead | planned |
| The client never chooses an object key | Key generated server-side in the tenant prefix; unknown field rejected | `object_key` rule and strict schema | F3, S5, S6 | Head of Platform | planned |
| An unclean object is never visible or served | `scan_state` gate on list, detail and mint | `CHECK` constraint plus the `409` gate | S7, S8, F9, F10 | Clinical Safety Officer | planned |
| Uploads are validated and scanned | Size cap, extension allow-list, MIME check, magic bytes, antivirus, quarantine | Upload validation pipeline | F5–F10, S9, S22 | Security Lead | planned |
| Cross-tenant access is denied without leaking existence | RLS plus `404`, never `403`; IAM prefix condition | `pol_documents_tenant_isolation`; presigner prefix check | S3, S4, S10–S14 | CTO | planned |
| Document bytes never leak into logs, analytics or telemetry | Classification `HIGHLY_SENSITIVE` enforced at the schema and the sink | Field classification and redaction pipeline | S18 | Security Lead | planned |
| Document rows are not destroyed by the application | No delete endpoint; `REVOKE DELETE`; soft delete; lifecycle transition | Grant revocation and `deleted_at` | F11, S19, S20 | Privacy Officer | planned |
| Health data stays in Australia | Residency register, region-pinned bucket | `ap-southeast-2` configuration | Register entry | Compliance Lead | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| Audit action names `document.*` are not in `07-audit-architecture.md` §1 and must be registered before R10 can pass | Security Lead | OPEN — blocks part 4 |
| Malware-scan service residency, sub-processor status and terms | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION — blocks part 5 and the Gate 4 data-flow evidence |
| Retention period for objects, versions and audit events | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION — blocks part 5 |
| Object-key layout divergence between `05-tenant-isolation.md` §243 and `11-tga-inbox-pipeline.md` §8 / `04-database-erd.md` §3.9 | Head of Platform | OPEN — blocks part 2 sign-off |
| The malware-scan engine choice (self-hosted vs managed) and the quarantine bucket IAM boundary | Head of Platform | OPEN — blocks part 6 |
| Whether a residual **Medium** risk on D-02, D-05, D-07, D-08, D-12 or D-13 is accepted for the pilot | CTO + Security Lead | OPEN — blocks part 3 acceptance |
