---
doc_id: OZ-FEAT-09-US
title: "TGA inbox — user stories"
owner: Head of Product
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-09
phase: 02-phase-2-tga-approval-engine
gate: [5]
source:
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md §6, §7, §10
  - clinic-os-secure-by-design/03-threat-model.md §7
  - clinic-os-secure-by-design/22-user-stories.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A).

## Clinic Administrator

**US-1** As a Clinic Administrator, I want TGA approval letters to land in the system without manual
retyping, so that a prescription is not delayed by data entry.
- Acceptance: an email to the tenant's receiving address produces a review queue item or a usable
  `PENDING` record within 2 minutes of arrival.
- S: the mailbox identity maps to exactly one tenant at ingest; the tenant is never taken from the mail.
- A: `inbox.message.received` (registration required) with the authentication result and `correlation_id`.

**US-2** As a Clinic Administrator, I want to see why a letter could not be processed, so that I can fix
the source rather than guess.
- Acceptance: each failure names its reason — `ENCRYPTED`, `PASSWORD_PROTECTED`, `OVERSIZED`,
  `MALWARE_DETECTED`, `MIME_MISMATCH`, `NO_MATCH` — and offers the manual-entry path.
- S: a quarantined object is never served or previewed; only `CLEAN` attachments are reachable.
- A: `tga_document.validation_failed` / `tga_document.malware_detected` (registration required).

**US-3** As a Clinic Administrator, I want a letter about a patient I cannot access to stay out of my
queue, so that the queue does not leak a patient list.
- Acceptance: the care-relationship rule applies to the queue exactly as elsewhere.
- S: queue items are filtered by the same policy layer as clinical reads; cross-tenant identifiers never
  resolve.
- A: the refusal is audited with the same fidelity as a success.

## Clinical Safety Officer

**US-4** As the Clinical Safety Officer, I want no extraction to reach `ACTIVE` on its own, because an OCR
result must never sit between a clinician and a patient.
- Acceptance: the extractor role can write only `tga_extraction_results`; only the verify endpoint writes
  `ACTIVE`; a grant-inspection test proves both.
- S: no automated stage writes clinical state; no bypass parameter exists on the pipeline.
- A: `tga_approval.state_change` records every transition with `from_state`, `to_state` and `reason`.

**US-5** As the Clinical Safety Officer, I want to control the confidence threshold and see it changed, so
that routing is a clinical judgement rather than a magic number in code.
- Acceptance: the threshold is a `tenant_policy` value with a documented CSO rationale; composite
  `0.95`, field floor `0.80`, match `0.90` are recorded as **recommendations, not constants**.
- S: the value is writable only by `tenant:configure` with step-up; a field below its floor routes to
  review regardless of the composite score.
- A: the change writes an audit event with old value, new value and reason.

**US-6** As the Clinical Safety Officer, I want to know when a document was matched to the wrong patient,
so that a wrong-approval hazard is visible before it reaches a prescription.
- Acceptance: a wrong-patient association is only ever a proposal; where two candidates score within 0.05
  both are presented and an explicit choice is required; merging patient records is never automatic.
- S: matching is deterministic-first, candidate-only, tenant-scoped, and never merges records.
- A: `tga_approval.match` records the candidate identifiers that agreed and the reason each was proposed.

**US-7** As the Clinical Safety Officer, I want a queue item that ages to reach me, so that a low-confidence
letter is not lost behind newer, higher-scoring ones.
- Acceptance: the queue is ordered oldest first with the confidence shown; an item older than 4 hours
  raises an alert to the CSO.
- S: no ordering by score; no silent expiry of a queue item.
- A: queue age and the alert are observable via `tga_inbox_review_wait_seconds`.

## Doctor / Verifier

**US-8** As a Doctor, I want to verify an extracted approval against the letter itself, so that the record
I sign is the record on the paper.
- Acceptance: the document renders beside the extracted fields; each field shows its page and region, its
  confidence and the method that produced it; the decision is accept, correct, reject or defer.
- S: correct and reject require a reason; a second concurrent claim returns `409 Conflict`; step-up is
  required for the verification decision.
- A: `tga_approval.verify` records reviewer, decision, reason and fields corrected.

**US-9** As a Doctor, I want a letter that names the wrong patient to be rejected without changing anything,
so that no clinical state is written from a bad read.
- Acceptance: reject leaves the approval `PENDING`/`REJECTED` and never writes accepted values.
- S: no auto-association below the threshold; the reviewer's choice is explicit, never pre-selected.
- A: `tga_approval.verify` with `decision = REJECT` and the reason.

**US-10** As a Doctor, I want a corrected field to be recorded as a correction, not as a silent overwrite,
so that the machine's original reading and my correction are both preserved.
- Acceptance: `raw_value` is immutable; the human value is written to `accepted_value` with `accepted_by`
  and `accepted_at`.
- S: update is limited to the acceptance columns by column-level grant; `raw_value` and `confidence`
  cannot be altered.
- A: the correction is part of the verification event, which is auditable even when it matches the
  machine's proposal.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Role and permission names align to `06-authentication-rbac.md` before build | Security Lead | OPEN |
| Whether the review queue is clinic-staffed or a shared service changes US-7 alert routing | Clinical Safety Officer | OPEN |
| Whether an auto-create-above-higher-score path (US-1 variant) is ever enabled | Clinical Safety Officer | OPEN |
