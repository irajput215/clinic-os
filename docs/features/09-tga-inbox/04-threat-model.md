---
doc_id: OZ-FEAT-09-THREAT
title: "TGA inbox — STRIDE threat model"
owner: Security Lead + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-09
phase: 02-phase-2-tga-approval-engine
gate: [5]
source:
  - clinic-os-secure-by-design/03-threat-model.md §7, §8, §13
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md
  - clinic-os-secure-by-design/16-vendor-register.md §2
  - clinic-os-secure-by-design/26-security-gates.md §6
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Threat model

**Assets.** Inbound approval correspondence; extracted fields; the mapping to a patient; the verification
decision; the source PDF. **Trust boundaries.** TB-1 edge (mail and attachments are fully untrusted),
TB-3 application, TB-4 data, TB-5 storage. **Entry points.** The inbound mailbox,
`POST /api/v1/tga-inbox/messages`, `POST /api/v1/tga-inbox/{id}/verify`, `…/reject`, the extraction
worker. Source: `03-threat-model.md` §7.

**Risk scoring.** `Likelihood × Impact`, each 1–5; banded **Low ≤4 · Medium 5–9 · High 10–16 ·
Critical ≥17**. Doc 03 §7 records a score and a compressed label; where the label disagrees with this
repo's bands, the bands are applied and the source label is noted.

## STRIDE

| ID | STRIDE | Threat & attack path | Control / mitigation | Residual (L×I) | Owner | Source |
| --- | --- | --- | --- | --- | --- | --- |
| **T-09.1** | **Spoofing** | **Forged or spoofed sender** — a forged approval email creates a fictitious approval | SPF/DKIM/DMARC verified and recorded; sender allow-list per tenant plus quarantine for unknown senders; extraction produces a candidate only; a human verifies before `ACTIVE`; the state machine never self-activates | **12 = 3×4 — High** (source labels Medium) | Clinical Safety Officer | `03` §7; `11` §2 s1, §3 |
| **T-09.2** | **Tampering** | **Malicious attachment** — a PDF or archive carries malware or an exploit | Type allow-list, magic-byte check, size and decompression caps, antivirus scan, quarantine bucket with a separate IAM boundary before visibility | **8 = 2×4 — Medium** | Security Lead | `03` §7 |
| **T-09.3** | **Tampering / Elevation** | **MIME or extension used to escape the checks** — a double extension or a polyglot passes the declared-type check and executes elsewhere | Extension, `Content-Type` and magic bytes must agree; mismatch quarantined and never parsed; parser isolated with no egress; download-only disposition | **6 = 2×3 — Medium** (source labels Low) | Security Lead | `11` §9; `03` §8 |
| **T-09.4** | **Tampering / Elevation** | **OCR text as an injection vector** — document text instructs the extraction model to change behaviour, select a patient or emit a value | Model output is untrusted input; extraction is field-scoped and schema-validated; no clinical write without human confirmation; injection attempts logged as a security signal | **9 = 3×3 — Medium** | Clinical Safety Officer + Security Lead | `03` §7; `11` §9 |
| **T-09.5** | **Tampering** | **Filename or extension used to escape the intended path** — `../../etc/passwd`, `a.pdf.exe`, a name used to build an object key | Key generated server-side from `tenant_id`/`document_id`; the original filename is stored in the database and sanitised for display, never used as a path; bucket policy requires the tenant prefix | **4 = 1×4 — Low** (derived) | Security Lead | `11` §8, §9; `03` §8 |
| **T-09.6** | **Tampering (clinical safety)** | **Extraction error auto-associates a document with the wrong patient** — a misread name or identifier attaches an approval to the wrong person | Candidates only, never a write; per-field floor `0.80`; deterministic cross-check; explicit human selection with **no pre-selected default**; two candidates within 0.05 both presented; no auto-merge; `raw_value` immutable beside `accepted_value` | **16 = 4×4 — High** | Clinical Safety Officer | `03` §7; `11` §6, §7 |
| **T-09.7** | **Elevation of privilege** | **Extraction writes directly to an approval** — a code path that trusts the extractor and skips verification | Extractor role has `INSERT` on `tga_extraction_results` only, never on `tga_approvals`; the verify endpoint is the only writer of `ACTIVE`; grant inspection and negative SQL execution in CI | **5 = 1×5 — Medium** (source labels Low) | Security Lead | `03` §7; `04` §3.7, §9 |
| **T-09.8** | **Tampering (clinical safety)** | **Confidence-threshold incorrect tuning releases an unverified approval** — the threshold is lowered to clear a backlog, or a composite score masks one bad field | Threshold is a policy value with CSO sign-off and a documented rationale; change requires `tenant:configure` with step-up and is audited; per-field floor routes to review regardless of the composite; nothing auto-activates; verification rate and correction rate reviewed monthly | **8 = 2×4 — Medium** (derived) | Clinical Safety Officer | `11` §4, §12; `26` §6 |
| **T-09.9** | **Information disclosure** | **Cross-tenant matching** — a shared matcher resolves a patient in another tenant, or a national identifier becomes a tenant-crossing key | Matching runs under RLS with tenant context set in the worker before any query; no cross-tenant identifier key; canary-tenant test `inbox.matching_never_crosses_tenant_boundaries`; `404`, never `403` | **10 = 2×5 — High** (source labels Medium) | Security Lead | `03` §7; `11` §7 r2 |
| **T-09.10** | **Information disclosure** | **Shared mailbox leaks one tenant's correspondence to another** — one platform mailbox serves every tenant | Mailbox identity mapped to exactly one tenant at ingest; tenant set on the message row; tenant context set in the worker before any query; RLS; test `inbox.cross_tenant_message_not_visible` | **10 = 2×5 — High** (source labels Medium) | Security Lead | `03` §7 |
| **T-09.11** | **Denial of service** | **Mailbox flooding** — inbound volume starves the extraction worker | Queue with a DLQ; extraction rate limit per tenant; backpressure metric; quota per tenant | **6 = 3×2 — Medium** | Head of Platform | `03` §7 |
| **T-09.12** | **Denial of service** | **ZIP bomb or decompression abuse** — a small attachment expands to exhaust the worker | 25 MB size cap, decompression-ratio cap, scan with resource limits, per-tenant quota, isolated worker with a memory and wall-clock cap | **6 = 2×3 — Medium** (source labels Low) | Head of Platform | `03` §8; `11` §9 |
| **T-09.13** | **Repudiation** | **A verifier denies the verification decision** — a clinician claims they did not accept an approval | Verification writes the append-only approval event with actor, timestamp, source message and the accepted field values; `GRANT SELECT, INSERT` only on the event table | **6 = 2×3 — Medium** (source labels Low) | Compliance Lead | `03` §7; `11` §6 |
| **T-09.14** | **Information disclosure** | **Document text, OCR result, subject or filename leaks into logs or telemetry** — PHI reaches a log sink or a crash report | `HIGHLY_SENSITIVE` never reaches a log, analytics or error telemetry; the audit records the action, never the content; sentinel test over every sink | **8 = 2×4 — Medium** (derived) | Security Lead | `12` §3; `07` §7; `11` §11 |
| **T-09.15** | **Tampering** | **Duplicate or replayed ingestion creates a duplicate approval** — the same email or content is processed twice | `UNIQUE (tenant_id, provider_message_id)`; content-hash linkage instead of a second object; duplicate grain enters the supersede flow; stages are idempotent | **4 = 1×4 — Low** (derived) | CTO | `11` §2 s10, §7 r5, §10 |
| **T-09.16** | **Elevation of privilege** | **An automation releases a blocked dispatch** — the workflow-update stage dispatches, or writes a gating state without a human decision | Stage 12 never dispatches; it re-evaluates and a still-failing prescription stays `BLOCKED`; audit write is same-transaction; Gate 5 check "TGA ingestion cannot write a gating state without a human verification" | **5 = 1×5 — Medium** (derived) | Clinical Safety Officer | `11` §2 s12; `26` §6 |
| **T-09.17** | **Elevation of privilege** | **Two reviewers verify concurrently** — a race produces two decisions or two approvals | Queue item claimed with a lease; a second claim returns `409 Conflict`; the verify endpoint is the single writer of `ACTIVE` | **4 = 1×4 — Low** (derived) | CTO | `11` §6 |
| **T-09.18** | **Information disclosure** | **A quarantined object is served** — malware or a validation failure is downloaded from the review UI | Quarantine bucket with a separate IAM boundary; an unclean object is never served; the clinical record shows the quarantine state and reason; only `CLEAN` attachments are listable and mintable | **4 = 1×4 — Low** (derived) | Security Lead | `11` §8; `04` §3.7 |

## Failure modes this feature forbids

| Forbidden failure mode | The control that prevents it | Source |
| --- | --- | --- |
| OCR, a filename, a `Content-Type` header or an extension being trusted | Every one is untrusted input; server-generated keys; magic-byte checks; schema-validated field-scoped extraction | `11` §1, §9 |
| Auto-association below the configured threshold | Threshold is a policy value with clinical sign-off; below it the record stays `PENDING` | `11` §3, §4 |
| Auto-merging patient records | A candidate is a proposal, never a write; merging is a separate permissioned audited human action | `11` §7 r1 |
| One clinic reading another clinic's data | Tenant from the verified context, RLS with `FORCE`, `SET LOCAL`, `404` for other-tenant rows | `03` §13; `04` §8 |
| Sensitive information leaking through logs | PHI exclusion, structured allow-list logging, fixed error contract, telemetry schema | `03` §13; `12` §5.2 |
| Audit events disappearing | Append-only grants, same-transaction write, alert on audit write failure | `03` §13; `07` §3 |
| An integration writing a gating state without a human decision | Extraction cannot write `tga_approvals`; only the verify endpoint writes `ACTIVE` | `26` §6 |
| A document instructing the extraction model | Injection attempts are logged as a security signal; the model cannot select a patient or write state | `03` §7 |
| A third party receiving patient data without a register entry | Vendor register entry required before merge; V-04, V-07, V-08 are unresolved | `03` §13; `16` §2, §3 |

## Assumptions

- The mailbox provider, OCR service and malware scanner are third parties whose data-processing position
  and residency is **REQUIRES LEGAL/REGULATORY VALIDATION** (V-04, V-07, V-08).
- Single database, modular monolith, RLS enabled; the extraction worker is a separate role with no
  access to `tga_approvals`.
- Content disarm and reconstruction is **not** applied by default to PDFs whose visual fidelity is
  clinically relied on (`11` §9).

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| OCR/extraction vendor data-processing position, no-training commitment and residency (V-07) | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Mailbox provider processing location and inbound-mail retention (V-04) | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Malware-scanning service residency and quarantine design (V-08) | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether CDR is safe for the PDFs these clinics rely on | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Threshold values and rationale (T-09.8) | Clinical Safety Officer | OPEN |
| Injection-attempt detection signal: what is logged, and where it alerts | Security Lead | OPEN |
