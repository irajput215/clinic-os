---
doc_id: OZ-FEAT-12-STORY
title: "Pharmacy dispatch — user stories"
owner: Head of Product
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-12
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/22-user-stories.md
  - clinic-os-secure-by-design/10-integration-boundaries.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A).

## Pharmacy user

**US-1** As a pharmacy user, I want the prescription dispatch to appear at my pharmacy without being
entered again, so that I dispense exactly what the prescriber signed.
- Acceptance: a signed provider event creates one `pharmacy_dispatches` row `RECEIVED` for my pharmacy.
- S: the event is signature-verified and the tenant is routed from the verified payload; my user cannot
  see another tenant's receipt.
- A: `integration.request` on arrival, then a receipt-created event carrying the provider reference.

**US-2** As a pharmacy user, I want to confirm that I dispensed the prescription, so that the
prescriber's record is complete.
- Acceptance: `POST /api/v1/pharmacy/dispatches/{id}/dispense` returns `200` and moves the receipt to
  the terminal `DISPENSED` state.
- S: `pharmacy_dispatch:confirm` held, step-up fresh, tenant ownership checked.
- A: the dispense confirmation event records the actor, the resource and `step_up = true`.

**US-3** As a pharmacy user, I want the same provider event arriving twice to show one prescription,
not two, so that nobody dispenses it twice.
- Acceptance: the second delivery returns `200` and changes nothing; exactly one receipt exists.
- S: dedupe on `(provider, provider_event_id)`; the duplicate does not disclose the row's tenant.
- A: `integration.webhook_duplicate` (proposed, OPEN-6) with the provider event id.

**US-4** As a pharmacy user, I want to reject a dispatch with a reason, so that the prescriber knows why
the medicine was not dispensed.
- Acceptance: reject requires a reason code and moves the receipt to the terminal `REJECTED` state.
- S: same permission and step-up as confirm; free text is never stored or logged.
- A: the reject event carries the reason **code** only.

## Doctor

**US-5** As a prescribing doctor, I want to see whether the pharmacy received and dispensed the
prescription, so that I can follow up with the patient.
- Acceptance: the prescription view shows the receipt status and the confirmation timestamp.
- S: read is tenant-scoped and shows only fields the prescriber needs; no unrelated pharmacy data.
- A: the read is logged against the prescriber's tenant and role.

**US-6** As a prescribing doctor, I want the platform never to tell me a prescription was dispensed when
it has not been confirmed, so that I do not act on a false state.
- Acceptance: a missing or failed provider event leaves the state non-terminal and visible as such.
- S: `DISPENSED` requires an explicit verified event or a pharmacy confirmation, never a timeout.
- A: `prescription.dispatch_failed` with `outcome_class = UNKNOWN` when the outcome is unknown.

## Clinical Safety Officer

**US-7** As the Clinical Safety Officer, I want a provider outage to surface as an unknown outcome, so
that the platform never claims a dispense that may not have happened.
- Acceptance: a connection failure moves the record to `REQUIRES_RECONCILIATION`; the reconciliation job
  resolves it in both directions.
- S: no automatic retry that could duplicate a dispense.
- A: the resolution event carries `reason = RECONCILED` and the original `correlation_id`.

**US-8** As the Clinical Safety Officer, I want an out-of-order event to be recorded but never to move a
terminal state backwards, so that a late `RECEIVED` cannot reopen a dispensed prescription.
- Acceptance: the stale event is stored with `process_result = STALE`; the terminal state is unchanged.
- S: the ordering comparison and a terminal-state guard trigger enforce it in the database.
- A: the stale event is retained and repeats raise an alert.

**US-9** As the Clinical Safety Officer, I want a payload that maps to no tenant quarantined and
alerted, so that a misrouted or probing event cannot write clinical state anywhere.
- Acceptance: `202`, a quarantine record, an alert, and zero tenant rows written.
- S: the payload is never routed by path or header; quarantine access is restricted to a named role.
- A: the quarantine event records the provider and the payload hash, never the payload content.

**US-10** As the Clinical Safety Officer, I want a burst of unverified webhooks to raise an alert, so
that a signature-forging attempt is visible rather than absorbed.
- Acceptance: unverified events are dropped `401`, counted, and alert above the threshold.
- S: IP allow-listing is a second control; a bad signature from an allow-listed address still fails.
- A: every drop is audited with the provider and source IP.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Role names above are placeholders; align to `06-authentication-rbac.md` §9 before build | Security Lead | OPEN |
| Whether a pharmacy-initiated read of `block_reason` is disclosable | CSO + legal | OPEN |
| Whether the quarantine queue is visible to a practice user or only to a named operator role | Head of Product | OPEN |
