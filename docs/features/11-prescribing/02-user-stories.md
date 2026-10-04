---
doc_id: OZ-FEAT-11-US
title: "Prescribing — user stories"
owner: Head of Product
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-11
phase: 03-phase-3-eprescribing
gate: [4, 5]
source:
  - clinic-os-secure-by-design/22-user-stories.md US-21…US-26
  - clinic-os-secure-by-design/20-product-requirements.md §7
  - clinic-os-secure-by-design/06-authentication-rbac.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A). Stories map to `22-user-stories.md`
US-21…US-26; where the source story is a gate story, this module supplies the prescription it acts on and
FEAT-10 supplies the decision.

## Authorised Prescriber

**US-1** As an Authorised Prescriber, I want to stage a draft prescription for my patient so that I can
review it before it becomes a clinical instruction.
- Acceptance: saved in `DRAFT` with all clinical fields; no dispatch is possible from `DRAFT`.
- S: `prescription:stage`; tenant from the session; active care relationship; strict body schema.
- A: `prescription.create` with actor, tenant, `patient_id`, `request_id`.

**US-2** As an Authorised Prescriber, I want to correct a draft before signing so that what I sign is what
I intend.
- Acceptance: `PATCH` succeeds while `DRAFT`; the response names the changed fields.
- S: only the prescriber of record or an authorised stager may modify; `prescription:stage`.
- A: `prescription.modify` with changed field **names**, never values.

**US-3** As an Authorised Prescriber, I want to sign with a fresh step-up factor so that the signature
cannot be applied to a stale session.
- Acceptance: signing sets `SIGNED`, `signed_at` and `signed_by`; a stale `auth_time` returns
  `401 step_up_required` and leaves the draft unchanged.
- S: `prescription:sign` is identity-bound and never grantable; the signer must be the prescriber of record.
- A: `prescription.sign` with `prescriber_id`, `patient_id`, `step_up = true`.

**US-4** As an Authorised Prescriber, I want to be told plainly why a dispatch was refused so that I can
fix the approval rather than guess.
- Acceptance: a refusal shows the FEAT-10 reason and the failing dimension; the prescription is `BLOCKED`;
  the retry after the approval is obtained does **not** require re-signing.
- S: no client field can assert an approval; the decision comes from FEAT-10.
- A: `prescription.dispatch_blocked` (FEAT-10) with the reason; this module records the `BLOCKED` transition.

**US-5** As an Authorised Prescriber, I want a correction after signing to be an addendum, not an edit, so
that the original decision remains provable.
- Acceptance: an addendum creates a new version that references the original; the original is unchanged
  byte-for-byte.
- S: no `UPDATE` path exists on a signed payload or signature.
- A: `prescription.modify` on the **new** version, carrying `supersedes_id`.

## Nurse (staging where configured)

**US-6** As a Nurse, I want to stage a draft for the prescriber so that the consultation is not slowed by
data entry.
- Acceptance: draft is created and remains `DRAFT`; it cannot be signed or dispatched by the Nurse.
- S: `prescription:stage` only; no `prescription:sign`, no `prescription:dispatch`.
- A: `prescription.create` with the Nurse as actor and the prescriber of record recorded separately.

**US-7** As a Nurse, I want to see the approval status at the point of care so that I do not stage a
prescription the pathway does not permit.
- Acceptance: the detail response exposes `approval_status`; the frontend may disable Dispatch, which is a
  courtesy only — the backend still refuses.
- S: read-only; the field is advisory and never an enforcement input.
- A: `prescription.read`-class access recorded per patient, not per row.

## Practice Owner

**US-8** As a Practice Owner, I want to cancel a prescription before dispatch with a reason so that an
abandoned script is not left non-terminal.
- Acceptance: `DRAFT` or `SIGNED` → `CANCELLED` with a required reason code.
- S: `prescription:cancel`; step-up where the tenant config requires it.
- A: `prescription.reject` with the reason **code**; free text never written to the log line.

**US-9** As a Practice Owner, I want a signed prescription to be uncorrectable in place so that no clinical
record can be rewritten after the fact.
- Acceptance: the immutability test in `06-test-plan.md` (S1) passes.
- S: immutability enforced by database privilege and a fail-closed trigger, not by convention.
- A: any refused mutation is audited as a denied attempt.

## Compliance Auditor

**US-10** As an auditor, I want the full state history of a prescription so that I can reconstruct who did
what and when.
- Acceptance: `GET .../history` returns the ordered transition list from `prescription_state_history`.
- S: read-only; tenant-scoped by RLS; cross-tenant returns `404`.
- A: every auditor read is logged.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Role names above are placeholders; align to `06-authentication-rbac.md` before build | Security Lead | OPEN |
| Whether the Nurse staging story is in pilot scope, and in which tenant configuration | Head of Product | OPEN |
| Whether a Practice Owner needs a separate permission from the prescriber for cancellation | Clinical Safety Officer | OPEN |
