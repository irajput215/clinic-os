---
doc_id: OZ-FEAT-12-THREAT
title: "Pharmacy dispatch — STRIDE threat model"
owner: Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-12
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md
  - clinic-os-secure-by-design/03-threat-model.md §6, §12
  - clinic-os-secure-by-design/26-security-gates.md §6
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 06-test-plan.md
---

# Threat model and residual risk register

## Scope and scoring

**Assets.** The prescription and its payload; the dispatch receipt; the provider signing secret; the
quarantine queue; the pharmacy's dispense confirmation; the patient's safety.

**Entry points.** `POST /api/v1/pharmacy/webhooks/{provider}`; `/api/v1/pharmacy/dispatches*`; the
reconciliation job. Source: `03 §6`; `10 §7`.

**Scoring.** `Likelihood × Impact`, each 1–5, banded **Low ≤4 · Medium 5–9 · High 10–16 · Critical ≥17**.

## STRIDE

| ID | STRIDE | Threat & attack path | Inherent | Control / mitigation | Residual | Owner | Source |
| --- | --- | --- | :---: | --- | :---: | --- | --- |
| **T-12.1** | **Spoofing** | **Forged webhook signature** — attacker posts a fabricated `DISPENSED` to mark a prescription complete | High (4×4=16) | HMAC/asymmetric verification over the **raw body before parsing**; per-provider, per-environment secret in Secrets Manager; failure drops `401` and alerts | **Low (1×4=4)** | Security Lead | `10 §7`; `26 §6` |
| **T-12.2** | **Spoofing** | **Replayed webhook** — a captured valid callback resent to re-confirm or double-dispense | High (4×4=16) | 5-minute signed-timestamp window; `UNIQUE (provider, provider_event_id)`; duplicate returns `200` with no state change | **Low (1×4=4)** | Security Lead | `10 §7`; `03 §6` |
| **T-12.3** | **Elevation / Info disclosure** | **Webhook maps to no tenant** — a forged or absent organisation reference probes for a writable path | High (3×4=12) | Tenant resolved from the verified payload only; no mapping ⇒ quarantine, alert, `202`, zero tenant rows written | **Medium (2×4=8)** — quarantine storage undecided (OPEN-2) | Security Lead + CTO | `10 §7` |
| **T-12.4** | **Tampering** | **Out-of-order events regress a terminal state** — a late `RECEIVED` reopens a dispensed prescription | High (3×4=12) | Compare the provider sequence/timestamp; `trg_pharmacy_dispatch_terminal` guard; stale event recorded `STALE`, terminal state unchanged | **Low (1×4=4)** | Clinical Safety Officer | `10 §7`; `10 §9` |
| **T-12.5** | **Elevation / Info disclosure** | **Cross-tenant webhook routing** — a payload naming tenant B sent to tenant A's URL, or receipt probing | Critical (4×5=20) | Router ignores path and header; RLS `FORCE` with `NULLIF`; tenant ownership checked; cross-tenant read returns `404` | **Low (1×5=5)** | Security Lead | `10 §7`; `05 §2` |
| **T-12.6** | **Denial of service** | **Body-size and content-type abuse** — an oversized or non-JSON body exhausts parsing memory or CPU | Medium (3×3=9) | 256 KB cap ⇒ `413`; `application/json` only; strict schema with unknown fields rejected; WAF plus 600/min per provider | **Low (1×3=3)** | Head of Platform | `10 §7`; `02 §11` |
| **T-12.7** | **Repudiation / clinical safety** | **Provider outage mis-reported as success** — a timeout or missing callback treated as dispensed | Critical (4×5=20) | Explicit non-terminal `REQUIRES_RECONCILIATION`; `200` only after commit; reconciliation resolves both directions; `DISPENSED` requires an explicit event or confirmation | **Low (1×5=5)** | Clinical Safety Officer | `10 §9`; `09 §8` |
| **T-12.8** | **Tampering** | **Deduplication failure creates a second dispatch** — a race or missing constraint lets one provider event create two receipts | Critical (4×5=20) | `UNIQUE (provider, provider_event_id)` resolved with `ON CONFLICT DO NOTHING`; `UNIQUE (tenant_id, provider, provider_dispatch_ref)`; dedupe and effect in one transaction | **Low (1×5=5)** | CTO | `10 §7`; `09 §7` |
| **T-12.9** | **Spoofing** | **Unverified webhook flood** — signature-oracle or brute-force attempts absorbed silently | Medium (3×3=9) | Unverified events dropped `401`, counted, alerted above threshold; 600/min per provider; IP allow-list second control only | **Low (1×3=3)** | Head of Platform | `10 §7`; `02 §11` |
| **T-12.10** | **Info disclosure** | **Quarantine queue leaks a payload, or the raw body reaches a log sink** | High (3×4=12) | Raw body never logged, `payload_sha256` only; quarantine access restricted to a named operator role; `HIGHLY_SENSITIVE` handling rules | **Medium (2×4=8)** — storage and access undecided (OPEN-2) | Privacy Officer + Security Lead | `10 §7`; `12 §5.2`; `07 §7` |
| **T-12.11** | **Spoofing** | **Pharmacy impersonates a dispense confirmation** — an account confirms dispense for another pharmacy or tenant | High (3×4=12) | Permission **plus** tenant ownership **plus** RLS; step-up; `404` across a tenant boundary; actor recorded on the receipt | **Low (1×4=4)** | Security Lead | `02 §11`; `03 §6` |
| **T-12.12** | **Tampering** | **Provider signing-secret compromise** — the attacker can now forge any event | High (3×5=15) | Secret in Secrets Manager only, per provider and environment, no env var/file/image; documented rotation with an overlap window; secret scanning in CI | **Low (1×4=4)** | Head of Platform | `10 §7`, `10 §4` |
| **T-12.13** | **Info disclosure** | **PHI in webhook error telemetry** — a payload or identifier captured in an error or stack trace | High (3×4=12) | Generic error bodies with a request id; no stack trace; `HIGHLY_SENSITIVE` never in logs, APM or crash reports | **Low (1×4=4)** | Security Lead | `07 §7`; `12 §5.2` |
| **T-12.14** | **Spoofing** | **SSRF through a payload-supplied URL** — the handler dereferences a URL in the event | Medium (2×4=8) | The handler never fetches a payload URL; egress allow-list; VPC resolver; metadata unreachable; refusal before the request | **Low (1×4=4)** | Head of Platform | `10 §8` |

## Failure modes this feature forbids

| Forbidden | The control that prevents it |
| --- | --- |
| Dispatch state changed by an unsigned or replayed event | Raw-body signature verification plus a 5-minute window |
| One provider event producing two receipts | Global unique constraint on `(provider, provider_event_id)` |
| A terminal dispense state regressing | Ordering compare plus a terminal-state guard trigger |
| A payload routed to a tenant by path or header | Tenant resolved from the verified payload only |
| An outage reported as a completed dispense | Non-terminal state, reconciliation, never success |
| An unrecorded refusal or quarantine | Every drop, duplicate and quarantine audited with equal fidelity |

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Source banding conflict: `03 §6` and `09 §8` label `3×5` as "Medium" while the standard band makes `10–16` High. This register applies the standard band and scores the outage row High inherent | Security Lead | OPEN |
| Quarantine storage and access model (OPEN-2) keeps T-12.3 and T-12.10 at Medium | Security Lead + CTO | OPEN |
| Provider sandbox behaviour differs from production; only production observation retires T-12.1 | Head of Platform | OPEN |
| Whether an inbound webhook surface needs mutual TLS in addition to the signature | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
