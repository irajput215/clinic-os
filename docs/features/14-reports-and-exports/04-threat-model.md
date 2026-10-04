---
doc_id: OZ-FEAT-14-THREAT
title: "Reports and exports — STRIDE threat model and residual risk register"
owner: Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-14
phase: 02-phase-2-tga-approval-engine
gate: [4]
source:
  - clinic-os-secure-by-design/03-threat-model.md
  - clinic-os-secure-by-design/02-security-architecture.md §11
  - clinic-os-secure-by-design/05-tenant-isolation.md §8
  - clinic-os-secure-by-design/12-data-classification.md §1, §4
  - clinic-os-secure-by-design/14-retention-and-deletion.md §1, §3
  - clinic-os-secure-by-design/26-security-gates.md §5
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Threat model and residual risk register

## Methodology

$$\text{Risk Score} = \text{Likelihood (1--5)} \times \text{Impact (1--5)}$$

| Band | Range | Meaning |
| --- | --- | --- |
| Low | $\le 4$ | acceptable; monitored by standard telemetry |
| Medium | $5 - 9$ | managed; automated CI test required |
| High | $10 - 16$ | must be mitigated before pilot deployment |
| Critical | $\ge 17$ | blocks release outright |

## STRIDE assessment

| ID | STRIDE | Threat and attack path | Inherent | Control | Residual | Owner | Source |
|---|---|---|---|---|---|---|---|
| **T-14.1** | Info disclosure | A user with export rights pulls the whole patient register to move it to a competitor or a personal device | High (4×4=16) | Privileged permission, typed reason, step-up, asynchronous job, per-tenant quota, watermark naming the requester, every request alerts | **Medium (2×3=6)** | Security Lead | `02 §11`; `20 §9`; `12 §2` |
| **T-14.2** | Info disclosure | A report or export job is run for tenant A while tenant B rows match the filter, and B's data lands in A's artefact | Critical (3×5=15) | RLS enabled and forced on `report_runs` and `export_jobs`; tenant from session; aggregation reads through the same RLS-scoped transaction; row count asserted exactly | **Low (1×4=4)** | CTO | `05 §8` I-027, I-028; `03 §RLS` |
| **T-14.3** | Info disclosure | An export artefact stays in the bucket after its window and is found by a later scan, a log, or an old URL in browser history | High (4×4=16) | `expires_at` set at readiness; scheduled expiry and deletion; 300 s identity-bound presigned URL; object never public; deletion audited as `export.expired` | **Low (2×2=4)** | Head of Platform | `20 §9`; `21 §5`; `05 §8` I-028 |
| **T-14.4** | Repudiation | An export happens with no recorded purpose, so nobody can say why bulk data left | High (4×3=12) | `reason_code NOT NULL` with a controlled list; absent reason returns `422`; `export.requested` records requester, reason code, scope, row count | **Low (1×3=3)** | Compliance Lead | `02 §11`; `20 §9`; `07 §2` |
| **T-14.5** | Tampering | The retention job over-deletes: a record inside minimum retention, or under legal hold, is purged | Critical (3×5=15) | Candidate selection by record type, jurisdiction and trigger date; minimum retention is a floor; held records excluded and counted; an unevaluable hold check aborts the run; purge permission held only by `clinos_retention` | **Medium (2×4=8)** | Privacy Officer | `14 §2`, §3.2; T5, T6, T15 |
| **T-14.6** | Info disclosure / Elevation | A DSAR is used to obtain another patient's record — a plausible request naming a different patient, or a changed `patient_id` in the body | High (4×4=16) | Scope is resolved server-side from the request row; a request naming another patient returns `404`; identity verification is a mandatory state; the response is a bounded, watermarked, expiring export | **Low (1×4=4)** | Privacy Officer | APP 12; `14 §4`; `05 §8` I-001 |
| **T-14.7** | Denial of service | Report or export generation is used as a DoS vector: repeated heavy runs exhaust the database pool or the worker queue | High (4×4=16) | 5 per hour keyed on session and tenant plus a per-tenant daily quota; asynchronous execution off the request path; bounded batches; alert on every bulk export request | **Medium (2×4=8)** | Head of Platform | `02 §11`; `14 §3.2`; `26 §5` |
| **T-14.8** | Info disclosure | A watermarked artefact is forwarded on; the watermark is trusted as a control when it is only a deterrent | Medium (3×3=9) | The watermark carries tenant, requester, purpose code and timestamp so a leak is attributable; the real control is the bounded permission, the reason and the alerting; removal of the watermark is itself audited at download | **Low (2×2=4)** | Security Lead | `12 §2`; `20 §9` |
| **T-14.9** | Elevation of privilege | A DSAR or correction path is repurposed as a deletion primitive to destroy unfavourable clinical history | High (3×4=12) | No DSAR path issues `DELETE`; a correction appends; a deletion request is an assessment that records a refusal; `clinos_app` holds no `DELETE` on any table here | **Low (1×4=4)** | Privacy Officer | APP 13; `14 §1`, §3.5 |
| **T-14.10** | Tampering | A downloaded artefact is edited to change reported counts, then presented as the submitted report | Medium (3×3=9) | `artefact_sha256` recorded; a submitted report is immutable and a correction is a new version referencing it; the audit event records the row count and period | **Low (2×2=4)** | Compliance Lead | `08 §6`; `07 §2` |

## Assumptions

- Single database, modular monolith, RLS enabled — the same assumption as `03-threat-model.md`.
- The S3 exports bucket is private, region-pinned to `ap-southeast-2`, and reached only by presigned
  URL (`13-data-residency.md` §4; `21 §5`).
- Step-up is provided by the identity layer, not hand-rolled (feature 02).

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Whether the export TTL should be shorter than 300 s given the artefact size (OPEN-2) | Security Lead | OPEN |
| The compensating control if a tenant legitimately needs more than the daily quota (OPEN-3) | Head of Platform | OPEN |
| Whether an export may ever be delivered outside the platform (for example by a regulator portal) — no integration exists today | Compliance Lead | **REQUIRES LEGAL/REGULATORY VALIDATION** |
