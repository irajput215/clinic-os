---
doc_id: OZ-FEAT-11-THREAT
title: "Prescribing — STRIDE threat model"
owner: Security Lead + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-11
phase: 03-phase-3-eprescribing
gate: [4, 5]
source:
  - clinic-os-secure-by-design/03-threat-model.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md §6, §9
  - clinic-os-secure-by-design/26-security-gates.md §5
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 06-test-plan.md
---

# Threat model

## Scope and assets

**Assets.** The prescription and its clinical payload; the prescriber's identity and signature; the state
machine and its history; the audit event log; the patient's safety.

**Entry points.** `POST /api/v1/prescriptions`, `PATCH /api/v1/prescriptions/{id}`,
`POST /api/v1/prescriptions/{id}/sign`, `POST /api/v1/prescriptions/{id}/addendum`,
`POST /api/v1/prescriptions/{id}/dispatch`, `POST /api/v1/prescriptions/{id}/cancel`.
Source: `03-threat-model.md` §6; `21-technical-design.md` §7.

**Risk scoring.** `Likelihood × Impact`, each 1–5. Residual is quoted as `L×I = n (Band)` where
**Low ≤4 · Medium 5–9 · High 10–16 · Critical ≥17**.

## STRIDE

| ID | STRIDE | Threat & attack path | Inherent | Control / mitigation | Residual | Owner | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **T-11.1** | **Spoofing** | **Prescriber impersonation** — a hijacked or shared session signs as another clinician, or a Nurse signs without `prescription:sign` | Critical (4×5=20) | Signature bound to the authenticated session; signer must equal `prescriber_id`; `prescription:sign` is never grantable; fresh step-up; one `prescription.sign` event naming actor and prescriber | Medium (1×5=5) | Security Lead | `03 §6; 06 §8; 20 §7` |
| **T-11.2** | **Tampering** | **Modification after signing** — an insider or rogue endpoint alters medicine, dose, quantity or signature after `SIGNED` | Critical (4×5=20) | `SIGNED` immutable; `trg_prescriptions_lock_signed` raises `SIGNED_IS_IMMUTABLE`; correction is an addendum referencing the original; the original bytes stay unchanged | Medium (1×5=5) | Clinical Safety Officer | `09 §6; 03 §6` |
| **T-11.3** | **Tampering** | **Invalid state transition** — a caller moves `DRAFT→DISPATCHED`, revives `CANCELLED`, or re-signs a `SIGNED` row | High (3×5=15) | Server-managed transition table; anything outside the allowed set returns `409 INVALID_STATE_TRANSITION`; the refusal is audited | Medium (1×5=5) | CTO | `09 §6; 21 §7` |
| **T-11.4** | **Tampering / Elevation of privilege** | **Client forces a state** — a request body, header or query parameter asserts `state = "SIGNED"` or `"QUEUED"` | Critical (4×5=20) | Strict Pydantic schema rejects unknown fields (`422`); no route takes a target state; the server recomputes the transition from the persisted row | Medium (1×5=5) | Security Lead | `09 §6; 21 §7; US-23` |
| **T-11.5** | **Tampering** | **Quantity or repeat manipulation** — a draft is inflated to obtain more of a controlled medicine, or `schedule8_flag` is cleared | High (4×4=16) | Server-side bounds (`quantity > 0`, `repeats BETWEEN 0 AND 12`); `schedule8_flag` derived from the medicine catalogue, not the request; changes after signing are refused; every modify records changed field names | Low (1×4=4) | Clinical Safety Officer | `12 §3; 09 §6` |
| **T-11.6** | **Tampering** | **Draft edited during a concurrent sign** — an edit commits between the signer's read and the signature write, so the signed payload differs from what was reviewed | High (3×4=12) | Sign reads the draft `FOR UPDATE`; the payload hash is captured in the same transaction; a row modified after the signer's read is refused with `409`; concurrent sign yields exactly one `SIGNED` row | Medium (2×4=8) | CTO | `20 §7; 09 §6` |
| **T-11.7** | **Repudiation** | **Audit-event suppression** — a state change or refusal returns without its event, hiding who acted | High (3×4=12) | Events written in the same transaction as the transition; an audit write failure aborts the operation; denied attempts audited with equal fidelity | Low (1×4=4) | Security Lead | `07 §1, §5; 09 §9` |
| **T-11.8** | **Information disclosure** | **Cross-tenant IDOR** — a caller probes prescription ids to learn another clinic's prescribing | High (3×4=12) | RLS with `NULLIF(current_setting('app.tenant_id', true), '')::uuid` and `FORCE`; cross-tenant returns `404`, never `403` | Low (1×4=4) | Security Lead | `04 §8; 05` |
| **T-11.9** | **Information disclosure** | **PHI in logs or telemetry** — medicine, dose, quantity or repeat values leak to a log sink or a crash report | High (4×4=16) | `HIGHLY_SENSITIVE` fields never reach a log, analytics pipeline or error telemetry; audit records field **names**, not values; redaction pipeline before sink write | Medium (2×4=8) | Privacy Officer | `12 §3, §5.2` |
| **T-11.10** | **Denial of service** | **Write flood on staging or signing** — bulk creation exhausts the connection pool | Medium (3×3=9) | Per-identity, per-tenant and per-route rate limits; cursor pagination ceiling; request-size limit on clinical writes | Medium (2×3=6) | Head of Platform | `21 §7; 02 §11` |

## Failure modes this feature forbids

| Forbidden | The control that prevents it |
| --- | --- |
| A signature applied to an unreviewed payload | `FOR UPDATE` read plus payload hash at sign; concurrent edits refused |
| A clinical instruction rewritten after signing | Immutability trigger plus addendum-as-new-version |
| A caller choosing the next state | Transition table server-side; target state is an unknown field |
| An unauditable transition | Event in the same transaction; failure aborts the operation |
| A refused action that leaves no trace | Denied attempts audited with equal fidelity |
| A prescription hard-deleted to hide a mistake | `REVOKE DELETE, TRUNCATE`; no delete endpoint |

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| `schedule8_flag` derivation from the medicine catalogue is not yet sourced | Clinical Safety Officer | OPEN |
| Whether a step-up is required for `PATCH` on a draft in a Schedule 8 pathway | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Concurrency control choice (`FOR UPDATE` vs optimistic version) must be confirmed at Gate 2 | CTO | OPEN |
