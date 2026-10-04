---
doc_id: OZ-FEAT-09-REQ
title: "TGA inbox — requirements"
owner: Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-09
phase: 02-phase-2-tga-approval-engine
gate: [5]
source:
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md
  - clinic-os-secure-by-design/03-threat-model.md §7, §13
  - clinic-os-secure-by-design/21-technical-design.md §9
  - clinic-os-secure-by-design/26-security-gates.md §6
repo_docs:
  - 02-user-stories.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# TGA inbox: requirements

## Purpose

Turn TGA approval correspondence that arrives as an email into a chart-ready approval record, without
ever trusting the machine's reading of it. The extraction result is a **proposal with a score**; only a
recorded human decision can present an approval to the safety gate as `ACTIVE`.

## The pipeline in one line

email → attachment extraction → sender/attachment validation → MIME and size check → malware scan →
private object storage (hash + scan state) → PDF/OCR → field and number extraction → patient and grain
matching → confidence score → **human verification** → approval record → audit → workflow update.

Source: `11-tga-inbox-pipeline.md` §1, §2; `21-technical-design.md` §9.

## Functional requirements

| ID | Requirement | Acceptance criterion (testable) | Source |
| --- | --- | --- | --- |
| R1 | Stages run in the fixed order above; a document that fails exits to a quarantine or review queue and records where it stopped | No silent skip; every document ends in a terminal state a human can find | `11` §1, §2 |
| R2 | Sender authentication is verified and recorded; unknown senders are quarantined | SPF/DKIM/DMARC result stored on the message row and displayed at verification; failed auth extracts no attachment | `11` §2 s1; `03` §7 |
| R3 | Attachment acceptance is bounded | Allow-listed types only, ≤ 25 MB per file, ≤ 10 attachments per message, double extensions rejected | `11` §2 s2, §9 |
| R4 | Extension, declared `Content-Type` and magic bytes must agree | A mismatch quarantines the file and it is **never parsed** | `11` §9 |
| R5 | Every file is malware-scanned before it is reachable from the clinical record | Positive verdict moves the file to the quarantine bucket (separate IAM boundary), notifies the CSO and stops the pipeline | `11` §2 s4, §8 |
| R6 | The original is stored private, versioned and encrypted, with its hash recorded at ingest | Bucket in `ap-southeast-2`, no public access, key generated server-side; hash verifies on retrieval or an alert is raised | `11` §8 |
| R7 | The text layer is used first; OCR runs only where none exists, in an isolated worker with no network egress | Encrypted or password-protected files are not cracked; they route to manual review with `ENCRYPTED` | `11` §2 s5, §10 |
| R8 | No extracted value is used unless it clears its floor or a human accepts it | Candidates carry per-field confidence; a field that cannot be extracted is left empty and marked `NOT_FOUND`, never guessed | `11` §3 |
| R9 | Every extracted value keeps its page and region provenance | Each candidate row stores the page number and the bounding region it came from | `21` §9; `11` §5 |
| R10 | Patient matching proposes candidates only, never a write | ≥ 2 independent identifiers agree, one of which is date of birth or a national identifier; no auto-merge, ever | `11` §7 |
| R11 | Matching never crosses a tenant boundary | The matching query runs under RLS with tenant context; a national identifier is not a tenant-crossing key; canary-tenant test passes | `11` §7 r2; `03` §7 |
| R12 | A composite score below the configured threshold stays `PENDING` and enters the human queue | Never auto-associated; a per-field floor below its value routes to review regardless of the composite | `11` §4; `03` §7 |
| R13 | The confidence threshold is a clinical safety parameter, not a constant | A `tenant_policy` value with CSO sign-off; change requires `tenant:configure` with step-up and is recorded in the audit trail | `11` §4 |
| R14 | **No automated step writes clinical state, and no path reaches `ACTIVE` without a recorded human decision** | Extractor role cannot write `tga_approvals`; the verify endpoint is the only writer of `ACTIVE`; grant inspection passes | `11` §3 r3; `21` §9; `26` §6 |
| R15 | The reviewer sees evidence, not a default | Document beside the fields, per-field confidence and producing method, candidates with agreed identifiers and reasons, **no pre-selected candidate** | `11` §6; `03` §7 |
| R16 | The review decision is accept, correct, reject or defer; correct and reject require a reason | Accept records the reviewer on the record; every decision writes `tga_approval.verify` | `11` §6 |
| R17 | Queue order and claim are deterministic | Oldest first with score shown; an item older than 4 h alerts the CSO; a second concurrent claim returns `409 Conflict` | `11` §6 |
| R18 | Duplicate ingestion does not duplicate records | Same content hash links to the existing document; no duplicate approval; a duplicate grain enters the supersede flow | `11` §7 r5, §10, §2 s10 |
| R19 | Every failure is a recorded outcome, not a gap | Oversized, encrypted, macro-bearing, multi-approval and unknown-patient cases each route to a named queue with a reason | `11` §10 |
| R20 | Every stage writes an audit event carrying the originating message's correlation identifier | Audit write failure stops the pipeline at that stage; the email-to-record path is reconstructable | `11` §11, §2 s11 |
| R21 | Stage 12 never dispatches | It re-evaluates a blocked prescription by making an approval available; a re-evaluation that still fails leaves it `BLOCKED` | `11` §2 s12 |
| R22 | Inbox-to-chart is measured against a **2-minute median target** | A document above threshold produces a usable record within 2 minutes, or a queue item appears within 2 minutes; p95 alert at 120 s; reviewer think time excluded | `11` §12 |
| R23 | Cross-tenant access returns `404`, never `403`; denied and failed attempts are audited with equal fidelity | A cross-tenant lookup is indistinguishable from a missing record | `03` §13; `README.md` |
| R24 | A reversal is a designed, audited procedure | Reversal writes `tga_approval.state_change`; it is never an in-place edit of accepted values | `21` §9; `08` §2, §3 |

## Out of scope for the MVP

- Manual approval entry and the approval state machine itself (FEAT-08)
- Prescription dispatch and pharmacy confirmation (FEAT-11, FEAT-12)
- Generic upload validation and presigned URLs — reused from the documents module (FEAT-07)
- Choosing an OCR, extraction, mailbox or malware-scanning vendor
- The numeric values of the four threshold policy settings

## Open items

| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | The four threshold values and their documented rationale, with clinical sign-off | Clinical Safety Officer | OPEN |
| OPEN-2 | `tenant_policy` is named in `11` §4 but has no table specification in `04` §3 — where the threshold is stored is unresolved | Head of Platform | OPEN |
| OPEN-3 | Page/region provenance required by `21` §9 has no column in `tga_extraction_results` (`04` §3.7); design proposes `page_number` and `region` | CTO + CSO | OPEN |
| OPEN-4 | `match_candidates` and `pipeline_events` are named in `11` §5 but unspecified in `04`; design proposes columns | CTO | OPEN |
| OPEN-5 | Approval state vocabulary: `04`/`08` use uppercase `PENDING`/`ACTIVE`; `08-tga-approvals/03-design.md` uses `pending_verification`/`active` — FEAT-09 depends on the former | CTO + CSO | OPEN |
| OPEN-6 | Object key convention differs between `11` §8 and `04` §3.9 | Security Lead | OPEN |
| OPEN-7 | Mailbox provider, its processing location and its retention of inbound mail (V-04) | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-8 | Third-party OCR/extraction vendor data-processing position and residency (V-07) | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-9 | Malware-scanning service residency and contract terms (V-08) | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-10 | Whether content disarm and reconstruction is safe for clinically relied-on PDFs | CSO | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-11 | Whether a tenant forwards TGA mail from its own address, which changes the sender allow-list design | Head of Integrations | OPEN |
| OPEN-12 | Whether the review queue is clinic-staffed or a shared service, which changes alert routing | CSO | OPEN |
| OPEN-13 | Whether auto-creation of a `PENDING` record above a higher score should ever be enabled | CSO | OPEN |
| OPEN-14 | Reversal semantics: which actor, which reason codes, and whether a rejected item can be re-opened | CSO | OPEN |
