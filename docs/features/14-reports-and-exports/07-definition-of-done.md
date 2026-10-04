---
doc_id: OZ-FEAT-14-DOD
title: "Reports and exports — definition of done"
owner: Compliance Lead + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-14
phase: 02-phase-2-tga-approval-engine
gate: [4]
source:
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md §5
  - clinic-os-secure-by-design/17-compliance-control-matrix.md TGA-03, APP-13, STATE-01, TEN-02
  - clinic-os-secure-by-design/05-tenant-isolation.md §8
  - clinic-os-secure-by-design/14-retention-and-deletion.md §2, §3
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Definition of done

The six parts are from doc 24. Tick only with a link to evidence.

| # | Part | Done | Evidence |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in `01-requirements.md` has a passing test | [ ] | F1–F10 command output; R1–R18 traceability in `06-test-plan.md` |
| 2 | Security: privileged permission, typed reason, step-up, async job, re-authorisation at download, identity-bound URL, watermark, expiry, per-tenant quota, RLS and grants implemented | [ ] | `03-design.md` export contract; S6–S14 |
| 3 | Security tests pass in CI: S1–S20 | [ ] | CI run URL; `tests/isolation/test_export_isolation.py` report |
| 4 | Audit: the eight events emitted and verified; A1–A4; names registered in `07 §1` | [ ] | `07 §1` registration diff; A1–A4 output |
| 5 | Operations and compliance: classification applied, no HIGHLY_SENSITIVE in logs, residency register updated for the exports bucket, metrics and alerts present | [ ] | S20 output; residency register entry; alert config |
| 6 | Deployment: image builds, scans clean, migration expand-and-contract, verified in Staging | [ ] | Pipeline report; Staging sign-off |

**No part is Done with an open High or Critical finding.**

## Gate sign-off and verification governance

| Stage / gate | What is verified | Verifier (decision maker) | Approver | Pass policy |
| --- | --- | --- | --- | --- |
| **CI / automated** | Grant inspection (`information_schema.role_table_grants`), no-`DELETE` proof, no-PHI payload check, export rate limits | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 4 (APIs)** | Privileged permission, typed reason, step-up, cross-tenant `404` on every report and export route including downloads, mass-assignment rejection, error envelope | **Security Lead** | **CTO** | No conditional pass for cross-tenant or reason/step-up refusals |
| **Gate 4 (data protection)** | RLS forced on the four tables; artefact expiry and deletion; identity-bound URL; watermark; per-tenant daily quota | **Security Lead** | **Privacy Officer** | No conditional pass |
| **Gate 4 (retention)** | Minimum-retention floor, legal-hold exclusion, fail-closed hold check, deletion certificate with no deleted values | **Privacy Officer** | **Compliance Lead** | No conditional pass on over-deletion |
| **Independent compliance** | DSAR workflow fidelity, APP 12/13 evidence, audit-trail integrity for legal reporting | **Compliance Lead** | **External Auditor** | Periodic / pre-launch |

No self-approval: the person who built or verified a control never signs its gate. The Security Lead
signs Gate 4 and the CTO approves; the Privacy Officer signs the retention control and the Compliance
Lead approves.

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Bulk export requires purpose, step-up and is visible | Typed reason, step-up, rate limit, alert on every request | `POST /api/v1/exports` | S6, S7, S11, S12 | Security Lead | planned |
| An export cannot cross a tenant | RLS forced on export and report tables; exact row-count assertion | `export_jobs`, `report_runs` policy | S1–S5 | CTO | planned |
| An artefact is not accessible after its window | `expires_at`, scheduled deletion, 300 s identity-bound URL | expiry worker | F6, S9, S10 | Head of Platform | planned |
| The app cannot destroy clinical or DSAR records | No `DELETE` grant to `clinos_app`; no DSAR delete path | `REVOKE DELETE` on the four tables | S13, S14, F8 | Privacy Officer | planned |
| Retention is jurisdiction-aware and hold-aware | Candidate selection by rule, minimum-retention floor, fail-closed hold check | `retention_jobs`, purge worker | F10, S16–S18 | Privacy Officer | planned |
| TGA reporting obligation is evidenced (`17` TGA-03) | Reporting extract with an approval record | `report_runs` and `report.generated` | F1, F3 | Compliance Lead | planned |
| APP 12 / APP 13 handled with a recorded outcome (`17` APP-13) | DSAR state machine, correction appended, refusal with a ground | `data_subject_requests` | F7–F9, S15 | Privacy Officer | planned |
| Health data stays in Australia (`17` TEN-02, `13 §4`) | Region-pinned exports bucket, presigner refuses another region | bucket policy | residency register entry | Compliance Lead | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 reporting cycle, fields, format and channel — doc 08 §6 says six-monthly is "the working assumption" and names no months | Compliance Lead | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OPEN-2 artefact TTL for exports | Security Lead | OPEN |
| OPEN-3 per-tenant daily quota value — doc 02 §11 requires one and states no number | Head of Platform | OPEN |
| OPEN-4 operative retention period per jurisdiction, and for a patient who moves between them | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OPEN-5 the eight audit action names are not in doc 07 §1, and `dsar:manage` and `retention:run` are not in the `06 §9` matrix; both must be registered before use | Security Lead + CTO | OPEN |
| OPEN-6 whether a missed reporting period must block prescribing | Clinical Safety Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OPEN-7 watermark algorithm: visible overlay against per-record HMAC | Security Lead | OPEN |
| OPEN-8 test paths `tests/reports/`, `tests/exports/` are unconfirmed against the repo layout | Head of Platform | OPEN |
| OPEN-9 the `clinos_retention` delete scope must match `04-database-erd.md` §6 exactly | Privacy Officer | OPEN |
