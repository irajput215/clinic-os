---
doc_id: OZ-FEAT-12-REQ
title: "Pharmacy dispatch — requirements"
owner: Head of Platform
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-12
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
---

# Pharmacy dispatch: requirements

## Purpose

Receive the prescription that the dispatch gate released, at the pharmacy, and record the dispense
confirmation. FEAT-12 owns the inbound pharmacy surface: the signature-verified webhook receiver, the
`pharmacy_dispatches` receipt record, and the pharmacy's confirm/reject action.

The dispatch decision is **not re-specified here**. The gate pipeline, the approval grain and
`dispatch_attempts` live in [03-design.md](../10-prescription-safety-gate/03-design.md) (FEAT-10, source
`09-prescription-safety-gate.md` §2, §7). Provider transport lives in FEAT-13.

Source: `10-integration-boundaries.md` §5, §7, §8, §9, §10; `09-prescription-safety-gate.md` §7, §8.

## Scope boundary

| In FEAT-12 | Owner elsewhere |
| --- | --- |
| Webhook receiver: signature, replay, tenant routing, ordering | — |
| `pharmacy_dispatches` receipt record and terminal state | — |
| Pharmacy confirm / reject of a dispense | — |
| Provider adapter, retry, breaker, egress allow-list | FEAT-13 |
| The dispatch gate, reason codes and `dispatch_attempts` | FEAT-10 |
| Prescription authoring and signing | FEAT-11 |

## Functional requirements

| ID | Requirement | Acceptance criterion (testable) | Source |
| --- | --- | --- | --- |
| R1 | Verify the provider signature over the **raw body before parsing** | Forged or absent signature returns `401`, writes no state | `10 §7` |
| R2 | A signed timestamp outside a **5-minute** window is refused as a replay | Old-timestamp request refused; no state change | `10 §7` |
| R3 | A duplicate `(provider, provider_event_id)` returns `200` with **no state change** | Second identical event changes nothing and creates no second dispatch | `10 §7` |
| R4 | Tenant is routed from the **verified payload**, never a path parameter or header | Payload naming tenant B on tenant A's path affects tenant B only | `10 §7` |
| R5 | A payload mapping to **no tenant** is quarantined, alerted and returns `202` | Quarantine record exists, alert emitted, zero tenant rows written | `10 §7` |
| R6 | Out-of-order events never regress a terminal state | Stale event is recorded; `DISPENSED` does not move back | `10 §7` |
| R7 | Body cap is **256 KB**; larger is `413` | Oversized body refused before parsing | `10 §7` |
| R8 | Content type is `application/json` only, strict schema | Other content types refused; unknown fields rejected | `10 §7` |
| R9 | `200` only after the state change **commits**; processing failure returns `500` | Injected failure leaves no state change and returns `500` | `10 §7` |
| R10 | Unverified webhooks dropped `401`, counted, alerted above threshold | Counter increments; alert fires above threshold | `10 §7` |
| R11 | IP allow-listing is a **second** control only | Allow-listed IP with a bad signature still returns `401` | `10 §7` |
| R12 | At most one receipt per provider dispatch reference | `UNIQUE (tenant_id, provider, provider_dispatch_ref)` rejects a second | `10 §7` |
| R13 | Pharmacy confirms dispense under permission and step-up; state is terminal | Confirm returns `200`; no later webhook regresses it | `09 §7`; `02 §11` |
| R14 | A provider outage is never reported as success | Non-terminal `REQUIRES_RECONCILIATION`, never `DISPENSED` | `10 §9`; `09 §8` |
| R15 | Pharmacy reads are tenant-scoped; cross-tenant returns `404`, never `403` | Cross-tenant receipt lookup returns `404` | `05 §2`; doc index |
| R16 | The handler never dereferences a URL contained in a payload | Payload URL never fetched; test asserts zero egress | `10 §8` |
| R17 | No stack trace and no clinical payload in any webhook error body | Error body carries a request id only | `02 §7` |

## Explicit negative decision matrix

| Condition | HTTP | State change | Reason code (proposed — OPEN-3) |
| --- | --- | --- | --- |
| Forged / absent / bad signature | `401` | none | `WEBHOOK_SIGNATURE_INVALID` |
| Valid signature, timestamp older than 5 min | `401` | none | `WEBHOOK_TIMESTAMP_STALE` |
| Duplicate `(provider, provider_event_id)` | `200` | **none** | `WEBHOOK_DUPLICATE` |
| Payload maps to no tenant | `202` | quarantine record only | `WEBHOOK_TENANT_UNKNOWN` |
| Payload maps to a foreign tenant | `200` | affects that tenant only | `WEBHOOK_ROUTED_BY_PAYLOAD` |
| Body larger than 256 KB | `413` | none | `WEBHOOK_BODY_TOO_LARGE` |
| Content type not `application/json` | `415` | none | `WEBHOOK_CONTENT_TYPE_UNSUPPORTED` |
| Stale / out-of-order event | `200` | event recorded; terminal state unchanged | `WEBHOOK_STALE_IGNORED` |
| State change fails to commit | `500` | none; parked after the retry budget | `WEBHOOK_PROCESSING_FAILED` |
| Unknown field in payload | `422` | none | `WEBHOOK_SCHEMA_INVALID` |
| Provider connection refused on reconciliation | `—` | `REQUIRES_RECONCILIATION` | `PROVIDER_UNAVAILABLE` |
| Cross-tenant receipt read | `404` | none | `NO_SUCH_DISPATCH` |

## Out of scope for the MVP

- Hosting any provider component, or accepting an inbound clinical query (`10` assumption)
- Barcode / eScript minting and prescription signing (`10 §5`)
- The dispatch gate and the outbound adapter (FEAT-10, FEAT-13)
- Patient-facing dispense notifications

## Open items

| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | Webhook mount point conflict: `10 §7` mounts provider callbacks at `/webhooks/:provider`; `02 §11` rates `/pharmacy/webhooks/*`. This feature adopts `POST /api/v1/pharmacy/webhooks/{provider}` | Head of Platform + Security Lead | OPEN |
| OPEN-2 | A no-tenant payload must be quarantined and return `202`, but every event table carries `tenant_id NOT NULL` under RLS. Sentinel tenant vs nullable tenant with a policy exception vs a separate un-scoped quarantine table — undecided | Security Lead + CTO | OPEN |
| OPEN-3 | Reason-code vocabulary and the HTTP code for a wrong content type (`10 §7` names none) | CTO + Security Lead | OPEN |
| OPEN-4 | Provider contract terms, processing residency and sub-processor status | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 | Retention of a quarantined payload and of the raw body | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
