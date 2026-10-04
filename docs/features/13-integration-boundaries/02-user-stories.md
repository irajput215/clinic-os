---
doc_id: OZ-FEAT-13-STORY
title: "Integration boundaries — user stories"
owner: Head of Product
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-13
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md §1–§9
  - clinic-os-secure-by-design/16-vendor-register.md §1–§3
  - clinic-os-secure-by-design/26-security-gates.md §6
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A). Role names are the governance
roles named in the source registers, not application user roles.

## Head of Platform

**US-1 — Onboarding a provider.** As the Head of Platform, I want a new provider admitted only when its
register rows and evidence exist, so that no rail reaches production unregistered.
- Acceptance: the ten-step onboarding gate (`16` §3) is complete; integration, residency and vendor
  registers each carry a row; the adapter cannot be enabled without an allow-listed destination.
- S: credentials per environment in Secrets Manager with a named owner and a rotation procedure; no
  credential in an image, task definition or repository.
- A: `integration.request` on the first production call, carrying `provider` and `correlation_id`.

**US-2 — Proving a data flow.** As the Head of Platform, I want one written data-flow record per rail so
that any auditor can answer *what is sent, what is received, where it is processed and who holds the
credential* without reading code.
- Acceptance: `03-design.md` § register row for the provider is complete, including sub-processor status
  marked **REQUIRES LEGAL/REGULATORY VALIDATION** where unresolved.
- S: the payload is checked against the minimum-data allow-list; a new field fails the test until the
  list is updated (`16` §1.1).
- A: `integration.request` carries outcome class and latency, never payload.

**US-3 — Surviving a provider outage.** As the Head of Platform, I want a named outage position per rail
with a clinical fallback, so that a dead rail degrades predictably instead of failing silently.
- Acceptance: the circuit breaker opens, calls fail fast with no retry storm, the failure state is
  user-visible, and the fallback procedure names its clinical owner (`10` §9; `29` §10).
- S: the breaker and bulkhead isolate the failing provider from clinical read paths.
- A: `prescription.dispatch_failed` with `result = FAILED` and `error_class`; alert on breaker open.

**US-4 — Environment separation.** As the Head of Platform, I want Production to share no credential,
queue or bucket with Development, so that a lower environment cannot act on production data.
- Acceptance: a configuration assertion proves no shared secret, bucket or queue (`10` §4).
- S: per-environment Secrets Manager entries scoped to the task role.
- A: none beyond configuration-change logging; the assertion is the evidence.

## Security Lead

**US-5 — Reconciling an ambiguous result.** As the Security Lead, I want a timed-out provider call to
become an explicit non-terminal state that the reconciliation job resolves, so that nothing is reported
as sent that was never confirmed and no duplicate is created.
- Acceptance: timeout or malformed body → `REQUIRES_RECONCILIATION`; the job resolves both directions
  within 5 minutes and escalates at 24 hours; every resolution writes `reason = RECONCILED`.
- S: the retry reuses the same idempotency key; a retry without one is impossible through the adapter.
- A: `prescription.dispatch_failed` with `result = UNKNOWN` at timeout; `prescription.dispatch` with
  `reason = RECONCILED` on resolution (`09` §9).

**US-6 — Rejecting a forged or replayed callback.** As the Security Lead, I want every webhook fully
validated before it changes state, so that an attacker cannot inject a dispensing event.
- Acceptance: bad signature `401`; replayed event `200` with no second state change; timestamp outside
  5 minutes refused; unknown tenant quarantined `202` and alerted.
- S: signature over the raw body before parsing; tenant from the verified payload, never the path;
  dedupe unique on `(provider, provider_event_id)`.
- A: `integration.request` with `result = DENIED` and a reason for every rejected webhook, at the same
  fidelity as accepted ones.

**US-7 — Blocking server-side request forgery.** As the Security Lead, I want a supplied URL never
dereferenced, so that an application defect or compromised dependency cannot pivot into the VPC.
- Acceptance: unregistered destination fails at the network layer; private, loopback, link-local and
  metadata addresses refused before the request; S3 keys resolved server-side; webhook payload URLs
  never fetched.
- S: egress allow-list fixed at configuration time; DNS through the VPC resolver; metadata service
  restricted to the task role.
- A: a refused destination is logged as a security signal with the resolved address class, no payload.

**US-8 — Rotating a credential without an outage.** As the Security Lead, I want rotation with an
overlap window and a stale-credential refusal, so that rotation neither breaks the rail nor leaves an
old secret usable.
- Acceptance: `status = ROTATING` during overlap; a call with a superseded credential is refused and
  audited; rotation is rehearsed in Staging before Production (`02` §6 rule 4).
- S: the secret value never leaves Secrets Manager; the database holds the ARN only.
- A: credential-reference change event; alert if a stale credential is presented.

## Clinical Safety Officer

**US-9 — No integration writes a gating state.** As the Clinical Safety Officer, I want TGA ingestion to
land `pending_verification`, so that a machine can propose but never permit.
- Acceptance: no integration path can set an approval `active`; manual entry and inbox ingestion both
  require human verification before the safety gate can match (Gate 5 carry).
- S: the verification permission is restricted and the verifier must differ from the creator.
- A: `tga_approval.verify` by the human reviewer; ingestion writes `tga_document.ingest` and
  `tga_approval.match`, never a gating state.

**US-10 — A clinical fallback when the rail is down.** As the Clinical Safety Officer, I want a stated
manual fallback with a named owner, so that patient care continues without bypassing the safety gate.
- Acceptance: the outage playbook names the fallback and its owner; the fallback never mints or signs a
  prescription on the prescriber's behalf.
- S: the gate still blocks dispatch when no `ACTIVE` approval covers the grain; the fallback is
  procedural, not a gate bypass.
- A: every blocked or failed dispatch is audited and appears on the non-terminal dashboard.

## Compliance auditor and Privacy Officer

**US-11 — Read-only vendor assurance.** As the Compliance auditor, I want register rows and evidence
status visible with the gaps named, so that an unexecuted agreement is an open item, not an assumed
control.
- Acceptance: each vendor row carries tier, data categories, contract status and residency; empty
  evidence cells are visible.
- S: the evidence store is access-controlled and separate from the repository; reads are audited.
- A: evidence-store reads logged.

**US-12 — Minimum data to a sub-processor.** As the Privacy Officer, I want a vendor to receive only the
fields its function requires, so that a sub-processor outside the approved region cannot receive PHI.
- Acceptance: the payload allow-list test fails on any field not in `16` §1.1; an unapproved cross-border
  flow cannot be enabled (`13` §3).
- S: field-level minimisation; no clinical content in a notification, an error report or a payment call.
- A: send-time event records the payload field set (names only), never values.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Role names are governance roles; map to application permissions before build | Head of Platform | OPEN |
| Who owns the manual fallback clinically when the rail is unavailable (`10` Open item 6) | Clinical Safety Officer | OPEN |
| Whether Tyro stories are in Phase 3 or a later phase | Head of Product | OPEN |
