---
doc_id: OZ-RECON-2026-11-21
title: "Reconciliation: TGA inbox and Parchment adapter against the task plan"
owner: CTO
status: DRAFT — for review
last_reviewed: 2026-11-21
next_review: 2026-12-05
classification: RESTRICTED
---

# Reconciliation: what was built vs the plan (2026-11-21)

Between 2026-11-17 and 2026-11-21 the TGA inbox and a Parchment adapter were built on owner request
(PRs #101–#105), guided by the feature documents and by two decision records written during that work
(D-011, D-012, both still **Proposed**). They were **not** built task by task from
[`docs/tasks/`](../tasks/). This document maps every relevant task to what exists, states each
deviation and why, and lists what is now owed. No task checkbox in `docs/tasks/` is ticked by this
document: the Definition of Done ticks a task only with linked evidence.

**Status key:** **Done** (meets the acceptance criterion) · **Differs** (built, but not as the task says;
the reason is given) · **Partial** · **Not done** · **Pre-existing** (built before this work, not
re-verified here).

## 1. Three conflicts inside the document set

A conflict between layers is a defect to raise, not a judgement call (AGENTS.md). These need an owner's
ruling:

| # | Conflict | Where | Owner |
|---|---|---|---|
| C1 | **Phase order.** `docs/tasks/02-phase-2-tga-approval-engine.md` puts the inbox in **Phase 2** (S4–S8), before e-prescribing. `docs3/roadmap.md` (newer) puts "TGA inbox" and "Parchment" in **Phase 7**, after the go-live blockers and Phase 6. Which plan governs? | both files | Head of Product + CTO |
| C2 | **Object key.** T2-20 says the key is `documents/{tenant_id}/{document_id}/v{n}/{sanitised_filename}`. FEAT-09 design says *"the original filename is **never** the key"* (and records this as OPEN-6). The build follows the feature document (normative for requirements) and uses `tga-inbox/{tenant_id}/{sha256}`. | `docs/tasks/02…` T2-20; `docs/features/09-tga-inbox/03-design.md` | Security Lead |
| C3 | **Task numbering.** `docs/to-be-completed.md` numbers the inbox as T2-19…T2-24 and the verification UI as T2-25…T2-30; `docs/tasks/02…` numbers them T2-17…T2-35 with different content. This document uses `docs/tasks/`. | `docs/to-be-completed.md` §Phase 2 | Delivery Lead |

## 2. TGA inbox — Phase 2 tasks S4 to S10

| Task | Status | What exists | Deviation or gap |
|---|---|---|---|
| **T2-17** Intake route and mailbox-to-tenant mapping | **Differs** | `POST /api/v1/tga-inbox/messages`; dedupe on `provider_message_id`; SPF/DKIM/DMARC stored and shown; unknown address refused `404` | Route is `/messages`, not `/intake`. The tenant comes from the **address** (`tga+<tenant>@<domain>`), not a mailbox mapping table. The route needs a bearer token (the task calls it unauthenticated; this is stricter). Tests are `tests/tga_inbox/`, not `tests/inbox/test_intake_dedup.py`. No V-04 data-flow record. |
| **T2-18** Attachment validation | **Differs** | Double extensions, MIME vs magic bytes, 25 MB, 10 files; a mismatch is recorded as refused and never parsed; nothing reachable before `CLEAN` (DB check constraint) | **PDF only**: PNG/JPEG/TIFF/DOCX are refused, because there is no OCR to read them. No explicit total-request cap beyond the schema's per-file and count limits. Refused files are recorded but not kept (no quarantine store). |
| **T2-19** Malware scan and quarantine boundary | **Partial** | Scan runs before storage; `INFECTED` is refused, not stored, and the verdict is recorded | The scanner is a **stand-in** (EICAR only). No quarantine bucket or IAM boundary, no CSO notification, no incident, and no engine version stored. |
| **T2-20** Private storage, hash, short-lived access | **Differs** | Content-addressed key; sha256 at ingest, verified on every retrieval (`409` on mismatch) | Key format: see C2. Storage is a stand-in (memory or a local directory): no SSE-KMS, no versioning. The PDF is streamed through the API as `application/pdf` inline (so the review screen can show it), **not** a 5-minute presigned URL as `octet-stream`. The `documents` module (FEAT-07) does not exist. |
| **T2-21** Failure handling to a terminal state | **Partial** | Every message ends `EXTRACTED`, `FAILED` (with a reason) or decided; encrypted and no-text-layer PDFs go to a person; oversized and disguised files are refused with a reason; each is audited | No multi-approval split. No macro or JavaScript check in PDFs. No `pipeline_events` table (audit events serve). No worker: the pipeline runs inside the ingest request. |
| **T2-22** Text layer first, isolated OCR | **Partial** | Text layer is read first; encrypted files are never cracked; stream size bounded (zip-bomb test) | **No OCR** at all. The text reader is a standard-library stand-in (`pdf_text.py`); a maintained library is a new dependency awaiting approval. No worker isolation, no parser timeout. |
| **T2-23** Per-field provenance | **Partial** | `method`, `extractor_version`, `page_number`, `raw_value` (encrypted), `confidence`, `NOT_FOUND`, all stored | `region` exists but is never populated (no coordinates). No "ambiguous digit lowers confidence" rule. |
| **T2-24** Pattern-plus-pass extraction | **Differs** | Two independent passes: labelled line, and a self-checking pattern (IHI, HPI-I and Medicare check digits) | The task asks for a pattern set **plus a model pass**. No model pass: D-011 deferred an LLM (a new third-party flow). |
| **T2-25** Per-layout parser registry | **Not done** | One rule set for every layout | |
| **T2-26** Patient matching | **Done**, minus fuzzy fields | Two agreeing identifiers, one DOB or national; under RLS; blind-index IHI and Medicare; no merge; nothing pre-selected; all candidates shown | No configured fuzzy fields. "Unknown patient" means the reviewer searches; there is no separate manual-resolution queue. |
| **T2-27…T2-29** Point-in-time match | **Pre-existing** | `tga_approvals` | Not touched by this work. |
| **T2-30** Composite score and four policy values | **Differs** | A composite (mean of the five mandatory fields' confidence) and a per-field floor, shown on the review screen; auto-create does not exist | Thresholds are **constants** in `extraction.py`, not configuration writable under `tenant:configure` with step-up. Match confidence is not in the composite. No CSO sign-off. |
| **T2-31** Low-confidence routing names the field | **Partial** | Every message goes to a person; fields under the floor are flagged by name | `TGA_EXTRACTION_LOW_CONFIDENCE` is not written (not in the audit catalogue). |
| **T2-32** Verification queue with a lease | **Partial — defect** | Oldest first; 15-minute lease; second claim `409`; accept, correct, reject and defer; correct and reject need a reason code | **Defect:** accept does **not** apply the care-relationship rule to the reviewer for the chosen patient. No alert for items older than 4 hours. |
| **T2-33** No automated path to `ACTIVE` | **Partial** | Accept creates `PENDING` only; activation is the existing verify by a second clinician (four-eyes); the pipeline writes as `clinos_extractor`, which the database refuses on `tga_approvals` and `patients` (tested) | No test that **enumerates every writer** of `tga_approvals.state`. |
| **T2-34** Verification UI | **Partial** | `/tga-inbox` and `/tga-inbox/{id}`: PDF beside fields, confidence and method per field, candidates with agreeing identifiers, nothing pre-selected | Page number shown but no jump to the page. No Playwright spec (CI has no inbox token). No CSO usability note. |
| **T2-35** Filing reversal | **Not done** | | |
| **T2-40** TGA event catalogue | **Differs** | Ingest `tga_document.ingest` / `.extract`; reads `tga_approval.read`; decisions `tga_approval.verify` (FEAT-09 R16), all in the same transaction | Existing catalogue names only; none of the `TGA_*` names from `spec.md` §8. |
| **T2-41** No PHI in logs | **Partial** | The module logs nothing; subject and every value encrypted at rest; payload and identity types print `<HIGHLY_SENSITIVE>` | No inbox-specific sentinel test. |
| **T2-42** Two-minute target measured | **Not done** | | No metrics. |
| **T2-43** Import boundaries | **Partial** | Cross-module calls go through service facades | The inbox imports `tga_approvals.schemas.TgaApprovalCreate` (a schema, not a model). No lint enforces boundaries. |
| **T2-44** Golden set | **Not done** | Synthetic letters exist only as test fixtures | |
| **T2-45, T2-46** Gate 4 and 5 bundles | **Not done** | | |

## 3. Parchment — Phase 3 adapter tasks T3-1 to T3-5

The prescriptions module, its gate, outbox and reconciliation (T3-6…T3-31) were **pre-existing**; this
work added only the adapter.

| Task | Status | What exists | Deviation or gap |
|---|---|---|---|
| **T3-1** Adapter interface and one adapter | **Differs** | `ParchmentTransport` behind the existing `DispatchTransport` (`send`, `lookup`), refuses a missing idempotency key | The interface method is `send` (pre-existing), not `dispatch`. Files are `prescriptions/transports/`, not `pharmacy/parchment_adapter.py`. The adapter does not check the key against the `dispatch_attempts` row. **No real HTTP client**: Parchment's API docs were unreachable and nothing is guessed, so `configured_transport()` is still `None`. |
| **T3-2** Credentials, owner, rotation | **Not done** | | Waiting for Parchment. |
| **T3-3** Timeout, retry, breaker, bulkhead | **Differs** | Deadline, at most 4 attempts with full jitter on transient `NotSent` only, breaker, bulkhead (`resilience.py`) | Breaker opens after **5 consecutive** failures with **1** half-open probe; the task says 10 failures in 30 s or 50 % over 20 calls, and 3 probes. No `429` / `Retry-After` handling. A timeout is never retried (the task allows retries on transient failures; Parchment's idempotency is unconfirmed). |
| **T3-4** Redacted logging | **Partial** | The adapter logs nothing; payloads never print | No sentinel scan specific to the adapter. |
| **T3-5** Simulated driver | **Differs** | `SimulatedParchmentWire`: scripted, records every payload, idempotent on the key | It lives in `app/` (next to the adapter), not `tests/fakes/`. Timeout, 5xx and malformed body are all expressed as one `UNKNOWN` answer rather than separately. |

## 4. Work with no task behind it

| Work | Source | Note |
|---|---|---|
| CI only on `testing` and `prod`; `main` deploys without tests (PR #101) | Owner decision 2026-11-21, recorded in AGENTS.md | Gates still need a green CI run on the evidence commit: run it on `testing`. |
| Draft consult note from an accepted letter (PR #104) | D-011 §3 (Proposed) | Read-time draft, never stored; changed from D-011's first wording so the clinician stays the author. |
| `frame-src blob:` added to the frontend CSP (PR #102) | Needed to show the PDF | Should have been asked first. |
| `GET /patients/{id}/tga-letters` | D-011 §3 | Declared in the patients route census. |

## 5. What is owed, in order

1. **Fix the T2-32 defect**: apply the care-relationship rule to the reviewer on accept. A safety control; do first.
2. **Rule on C1–C3** (§1).
3. **Approve or amend D-011 and D-012.** Both remain Proposed; the code follows them.
4. **CSO decisions:** the threshold values (T2-30), the correction and rejection reason lists, the golden set (T2-44).
5. **Vendor decisions** (D-011 open items): mailbox, scanner, OCR, object store; Parchment contract and sandbox (D-012).
6. Then the remaining tasks above, re-ordered by whichever plan C1 says governs.

The go-live blockers in `docs3/roadmap.md` (run the app as `clinos_app`, move it to Sydney, turn off
Neon scale-to-zero) apply under either plan and are independent of this list.
