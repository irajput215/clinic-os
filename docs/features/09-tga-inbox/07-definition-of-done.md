---
doc_id: OZ-FEAT-09-DOD
title: "TGA inbox — Definition of Done and Gate 5 sign-off"
owner: CTO + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-09
phase: 02-phase-2-tga-approval-engine
gate: [5]
source:
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md §6
  - clinic-os-secure-by-design/17-compliance-control-matrix.md
  - clinic-os-secure-by-design/16-vendor-register.md
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Definition of Done

The six parts are from doc 24. Tick only with a link to evidence.

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in `01-requirements.md` (R1–R24) has a passing test | [ ] | F1–F21 |
| 2 | Security: deny-by-default path, RLS with `NULLIF` + `FORCE`, permission and care-relationship checks, step-up, strict schemas, untrusted-input handling implemented | [ ] | `03-design.md` § Deny-by-default; S14–S16, S20 |
| 3 | Security tests pass in CI: S1–S20, including the MIME and malware bypass tests, the injection test and the grant inspection | [ ] | `06-test-plan.md` |
| 4 | Audit: every stage event emitted and verified; A1–A5; all action names registered in `07` §1 | [ ] | A1–A5, S19 |
| 5 | Operations & compliance: classification applied, no `HIGHLY_SENSITIVE` in logs or telemetry, residency register updated, the `tga_inbox_end_to_end_seconds` histogram and p95 alert live | [ ] | S17, F21; `05-data-and-audit.md` |
| 6 | Deployment: image builds, scans clean of Critical, migration expand-and-contract, verified in Staging against the sandbox mailbox | [ ] | CI scan reports; staging evidence |

**No part is Done with an open High or Critical finding.** A Critical finding blocks deployment outright.

## Gate sign-off & Verification Governance

| Stage / Gate | What is Verified | Verifier (Decision Maker) | Approver | Pass Policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Grant inspection (`S12`), extractor-role denial (`S11`), MIME/malware bypass (`S7`, `S8`), path escape (`S9`), injection (`S10`), action-catalogue registration (`S19`) | CI pipeline (pytest + static checks) | Automated gate | **Hard block on failure** |
| **Gate 5 (Integrations) — TGA ingestion boundary** | Every provider has a data-flow record; credentials per environment in Secrets Manager with a named owner; events deduplicated; timeouts become explicit non-terminal states; **TGA ingestion cannot write a gating state without a human verification** | **Security Lead** | **CTO + Compliance Lead** | **NO conditional pass** for the human-verification control; conditional pass only under the terms below |
| **Gate 5 conditional pass** | A provider whose data-flow record is complete but whose contractual terms are still under review, marked **REQUIRES LEGAL/REGULATORY VALIDATION** | Security Lead | **CTO + Compliance Lead** | Available **with an expiry and no production enablement**; granted by the CTO with the Compliance Lead |
| **Clinical sign-off** | The threshold policy values and rationale, the queue-age alert, the reviewer decision vocabulary and the refusal messages | **Clinical Safety Officer** | Practice Owner | **Cannot be waived** |
| **Independent compliance** | Reconstructability from email to approval record; audit integrity; vendor register position for V-04, V-07, V-08 | Privacy Officer / Compliance Lead | External auditor (TGA / ISO 27001) | Periodic / pre-launch |

**No self-approval.** The person who delivered the work never signs its gate.

**No integration can write clinical state without a human decision.** The extraction role has no write
access to `tga_approvals`; only the verify endpoint, acting on a recorded reviewer decision, writes
`ACTIVE`. Stage 14 re-evaluates a blocked prescription and never dispatches. Any change to that control
requires a **Gate 5 re-run** with CSO approval.

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Extraction is never trusted automatically | Confidence scoring, per-field floors, a deterministic cross-check and human verification | `tga_extraction_results`; threshold policy | F6, F7, F8, F20 | Clinical Safety Officer | planned |
| No auto-association below the configured threshold | The threshold is a policy value with clinical sign-off; nothing is auto-activated | `tenant_policy.tga_inbox_confidence_threshold` | F6, A5 | Clinical Safety Officer | planned |
| Every document is traceable to its paper | Original, extraction, confidence, decision and reviewer all stored | `documents`, `tga_extraction_results`, `match_candidates` | F7, F13, F17, A1 | Compliance Lead | planned |
| Uploads are validated as untrusted input | Extension, MIME, magic-byte, size and malware checks, then isolated parsing | validation module shared with FEAT-07 | F3, S7, S8, S9 | Security Lead | planned |
| Matching never crosses a tenant boundary | Matching runs under RLS with tenant context; no cross-tenant identifier key | matching service | S1–S5 | Security Lead | planned |
| Reviewers see evidence, not a default | Document beside fields, per-field confidence, candidates with reasons, no pre-selected match | review queue UI | F6, F12, F16 | Clinical Safety Officer | planned |
| Document storage is private and auditable | Private bucket in `ap-southeast-2`, versioning, KMS, 5-minute presigned URLs, lifecycle rules | bucket policy | F13, S8; residency register | CTO | planned |
| Inbox-to-chart is measured | Histogram per stage with a p95 alert at 120 s, excluding reviewer think time | `tga_inbox_end_to_end_seconds` | F21 | Head of Integrations | planned |
| An unauditable ingestion cannot proceed | Audit write in the same transaction; failure stops the pipeline | pipeline audit writer | A2, S19 | Security Lead | planned |
| No third party receives patient data without a register entry | Vendor register entry required before merge; V-04, V-07, V-08 unresolved | `16` §2, §3 | gate record | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 threshold values and rationale with clinical sign-off | Clinical Safety Officer | OPEN |
| OPEN-2 `tenant_policy` table unspecified in `04` | Head of Platform | OPEN |
| OPEN-3 page/region provenance columns absent from `04` §3.7 | CTO + CSO | OPEN |
| OPEN-4 `match_candidates`, `pipeline_events` and queue-item states unspecified in `04` | CTO | OPEN |
| OPEN-5 approval state vocabulary conflict (`PENDING`/`ACTIVE` vs `pending_verification`/`active`) | CTO + CSO | OPEN |
| OPEN-6 object key convention conflict (`11` §8 vs `04` §3.9) | Security Lead | OPEN |
| Five audit action names require registration in `07` §1 before use | Security Lead | REQUIRES REGISTRATION BEFORE USE |
| V-04 mailbox provider data-processing position and residency | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| V-07 OCR/extraction vendor data-processing position and residency | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| V-08 malware-scanning service residency and contract terms | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-10 content disarm and reconstruction position | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-12 review-queue staffing and alert routing | Clinical Safety Officer | OPEN |
| OPEN-13 auto-create-above-higher-score decision | Clinical Safety Officer | OPEN |
| OPEN-14 reversal semantics (actor, reason codes, re-open) | Clinical Safety Officer | OPEN |
