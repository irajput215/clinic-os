---
doc_id: OZ-FEAT-10-THREAT
title: "Prescription safety gate — STRIDE threat model"
owner: Security Lead + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-10
phase: 03-phase-3-eprescribing
gate: [4, 6]
source:
  - clinic-os-secure-by-design/03-threat-model.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 06-test-plan.md
---

# Threat model

## Scope and assets

**Assets.** The prescription and its payload; the prescriber's identity and signature; the TGA approval
the dispatch depends on; the dispatch record; the pharmacy notification; the patient's safety.

**Entry points.** `POST /api/v1/prescriptions`, `POST /api/v1/prescriptions/{id}/sign`,
`POST /api/v1/prescriptions/{id}/dispatch`, `/pharmacy/dispatches`, provider callbacks on the eScript
rail. Source: `03-threat-model.md` §6.

**Risk scoring.** `Likelihood × Impact`, each 1–5, banded **Low ≤4 · Medium 5–9 · High 10–16 · Critical ≥17**.
The source scores "dispatch without an active approval" as **Critical (1×5) if the gate is absent** and
Low once implemented.

## STRIDE

| ID | STRIDE | Threat & attack path | Control / mitigation | Residual | Owner | Source |
| --- | --- | --- | --- | --- | --- | --- |
| **T-10.1** | **Elevation of privilege** | Dispatch without an active approval — a direct API call bypassing the UI, or a stale approval | Server-side gate **inside the dispatch transaction**; grain = patient + category + dosage form; approval row read `FOR SHARE`; no bypass flag; `test_gate_blocked_without_approval` | **Critical (5×5)=25 if absent** → Low (1×5)=5 implemented | Clinical Safety Officer | `09` §1, §10; `03` §6 |
| **T-10.2** | **Tampering** | Expired or superseded approval treated as active — service date outside the window, or a newer grant replaced the old one | Window evaluated at **`date_of_service`** in `Australia/Sydney`; `SUPERSEDED` is not `ACTIVE`; revocation intermediate state tested | Low (2×5)=10 → 5 | Clinical Safety Officer | `08` §5; `09` §3 |
| **T-10.3** | **Spoofing** | Prescriber impersonation — one clinician signs as another | Signing identity-bound to the authenticated session; step-up required; signature event records actor and session; prescriber identity matched to the prescription | Medium (2×5)=10 | Security Lead | `06` §8; `03` §6 |
| **T-10.4** | **Tampering** | Modification of a signed prescription after the fact | `SIGNED` immutable; corrections are new versions referencing the original; version table append-only; no `UPDATE` grant on event history | Low (2×4)=8 | CTO | `03` §6; FEAT-11 |
| **T-10.5** | **Tampering** | Duplicate dispatch from a retry or double-click | Server-computed idempotency key; `UNIQUE (tenant_id, idempotency_key)`; provider event id deduplication | Low (3×3)=9 | CTO | `09` §7 |
| **T-10.6** | **Spoofing** | Replay of a provider webhook to mark a dispatch confirmed | Signature verification over the raw body before parsing; 5-minute timestamp window; dedupe on `(provider, provider_event_id)`; duplicate returns `200` with no state change | Low (2×4)=8 | Security Lead | `10` §7 |
| **T-10.7** | **Information disclosure** | Tampering in transit to the rail — modified payload to the pharmacy | TLS 1.2+, certificate validation, no plaintext provider call, signed payloads where the rail supports it | Low (1×5)=5 | Head of Platform | `03` §6 |
| **T-10.8** | **Repudiation / clinical safety** | Non-terminal state interpreted as success — a timeout treated as sent | Explicit `REQUIRES_RECONCILIATION`; reconciliation job; alert on non-terminal age; **never mark sent without confirmation** | Medium (3×5)=15 → 9 | Clinical Safety Officer | `09` §8 |
| **T-10.9** | **Elevation of privilege** | Unauthorised role dispatching — a pharmacy account acting for another tenant | Permission **plus** tenant ownership **plus** RLS; cross-tenant dispatch rejected `403`; `test_dispatch_cross_tenant_rejected` | Low (1×5)=5 | Security Lead | `03` §6 |
| **T-10.10** | **Elevation of privilege** | Gate bypassed by a code path that never calls it — a new route, worker, CLI or migration | One exported entry point; repository import lint fails the build on any other import **including a test**; token search for `skip`/`force`/`override` runs in CI | **Critical (4×5)=20 if the lint is absent** → Low (1×5)=5 | CTO | `09` §10 |
| **T-10.11** | **Repudiation** | A refusal returned without its audit event, hiding blocked attempts | The gate writes its own event **before** returning any decision; an audit write failure rolls the transaction back | Low (2×4)=8 | Security Lead | `09` §9 |
| **T-10.12** | **Information disclosure** | Prescription payload leaked into logs, telemetry or the audit trail | Prescription payload fields are `HIGHLY_SENSITIVE` — never in logs, analytics or error telemetry; the audit records the action, not the content; `request_payload_hash` only | Low (2×4)=8 | Security Lead | `12` §5.2 |
| **T-10.13** | **Tampering** | Concurrent revocation interleaves between the approval check and the dispatch insert | `SELECT … FOR SHARE` on the approval row inside the transaction; `test_gate_concurrent_revocation_blocks` | Low (1×5)=5 | CTO | `02` §2.1 |
| **T-10.14** | **Elevation of privilege** | The reconciliation job runs unscoped and crosses tenants | Jobs run with **explicit tenant context and fail loudly without it**; resolution by unique key; `test_reconciliation_requires_tenant_context` | Low (2×4)=8 | Head of Platform | `21` §2 |
| **T-10.15** | **Spoofing** | SSRF through a provider- or payload-supplied URL | The platform never fetches a tenant-, patient- or provider-supplied URL; egress allow-list set at configuration time; private, loopback, link-local and metadata responses refused before the request; the webhook handler never dereferences a payload URL | Low (2×4)=8 | Head of Platform | `10` §8 |
| **T-10.16** | **Denial of service** | Unverified webhook flood | Unverified webhooks dropped `401`, counted, alerted when the rate exceeds threshold; 600/min per provider; 256 KB body cap | Low (2×3)=6 | Head of Platform | `10` §7 |

## Failure modes this feature forbids

| Forbidden | The control that prevents it |
| --- | --- |
| A prescription bypassing a regulatory approval | Gate at the grain inside the dispatch transaction; window evaluated at the service date; row lock against concurrent revocation |
| UI-only enforcement of a clinical rule | Deny-by-default pipeline; a hand-crafted request is refused identically |
| A timeout reported as a completed action | Explicit `REQUIRES_RECONCILIATION`; reconciliation job; never mark sent without confirmation |
| A duplicate clinical action from a retry | Server-computed idempotency key with a unique constraint |
| An unauditable state change | Audit write in the same transaction; failure rolls back |
| A second implementation of the gate | One exported entry point; import lint; a pharmacist path calls the same gate |

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Import-lint coverage must include tests, scripts and migrations | CTO | OPEN |
| Signing key custody once D-003 is decided | CTO + Security Lead | OPEN |
| Provider sandbox behaviour differs from production; only production observation retires it | Head of Platform | OPEN |
