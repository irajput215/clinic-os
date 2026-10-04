---
doc_id: OZ-FEAT-10-US
title: "Prescription safety gate — user stories"
owner: Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-10
phase: 03-phase-3-eprescribing
gate: [4, 6]
source:
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/22-user-stories.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A).

## Authorised Prescriber

**US-1** As an Authorised Prescriber, I want to dispatch a prescription for my patient so that they can
obtain their medicine lawfully.
- Acceptance: with an `ACTIVE` approval at the grain covering the service date, dispatch proceeds and the
  prescription reaches `QUEUED` then `DISPATCHED`.
- S: `prescription:dispatch` held; actor is the prescriber of record or an authorised dispatcher; active
  care relationship; fresh step-up.
- A: `prescription.dispatch` with `SUCCESS`, recording `approval_id` and the idempotency key.

**US-2** As an Authorised Prescriber, I want to be told plainly when an approval is missing or invalid,
so that I can fix it rather than guess.
- Acceptance: the response is `422` with **"Active TGA Approval Required"** and a reason code naming the
  failing dimension (category, dosage form, patient, or validity).
- S: no outbound call is made; a client-supplied approval field is ignored.
- A: `prescription.dispatch_blocked` with `DENIED` and the `block_reason`.

**US-3** As an Authorised Prescriber, I want a double-click or network retry to produce one prescription,
not two.
- Acceptance: two identical requests produce exactly one prescription and one provider call; the second
  returns the first result.
- S: the idempotency key is computed server-side; a client header is hashed into it, never used raw.
- A: one `prescription.dispatch` event; the duplicate is not re-dispatched.

## Clinical Safety Officer

**US-4** As the Clinical Safety Officer, I want an unknown provider outcome never reported as success or
failure, so that the platform never claims a prescription was dispensed when it may not have been.
- Acceptance: a timeout writes `result = UNKNOWN` and moves the prescription to
  `REQUIRES_RECONCILIATION`.
- S: no automatic retry that could duplicate; the state is explicit and queryable.
- A: `prescription.dispatch_failed` with `UNKNOWN`; on resolution, `reason = RECONCILED` carrying the
  original `correlation_id`.

**US-5** As the Clinical Safety Officer, I want a revocation to take effect immediately, so that no
prescription is dispensed against an approval that was just revoked.
- Acceptance: a revocation committing between the approval check and the dispatch insert still blocks
  dispatch.
- S: the approval row is read `FOR SHARE` inside the dispatch transaction.
- A: the `prescription.dispatch_blocked` event names `APPROVAL_REVOKED`.

**US-6** As the Clinical Safety Officer, I want every refusal recorded, so that repeated blocked attempts
across patients are visible as a pattern.
- Acceptance: exactly one blocked event per refused request, even when the caller cannot see the approval
  state.
- S: the gate writes its own event before returning any decision.
- A: `prescription.dispatch_blocked` with actor, tenant, resource, reason and `request_id`.

## Compliance Auditor

**US-7** As an auditor, I want to prove that no dispatch occurred without an approval, by inspecting the
code path rather than taking a developer's word.
- Acceptance: the repository lint reports zero imports of the provider client outside the gate module,
  and a token search finds no bypass parameter.
- S: the check runs in CI as a static test.
- A: the lint and search results are retained as gate evidence.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Role names align to doc 06 §9 before build | Security Lead | OPEN |
| Whether the pharmacy-initiated path (US-8 candidate) is in MVP scope | Head of Product | OPEN |
