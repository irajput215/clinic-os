---
doc_id: OZ-FEAT-12-DOD
title: "Pharmacy dispatch — definition of done"
owner: Head of Platform + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-12
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md §6
  - clinic-os-secure-by-design/17-compliance-control-matrix.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Definition of Done

The six parts are from doc 24. Tick only with a link to evidence.

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in `01-requirements.md` has a passing test | [ ] | F1–F8 |
| 2 | Security: deny-by-default webhook path, raw-body signature verification, replay window, payload-routed tenant, RLS with `NULLIF` and `FORCE`, grant block | [ ] | S1–S20 |
| 3 | Security tests pass in CI: the manifest webhook matrix S1–S7 plus S8–S20 | [ ] | CI run |
| 4 | Audit: events emitted and verified; A1–A5; denied, duplicate and quarantined events audited with equal fidelity | [ ] | A1–A5 |
| 5 | Operations & compliance: no PHI in logs, quarantine queue visible, unverified-rate alert live, vendor register updated, outage playbook owned | [ ] | alert and register records |
| 6 | Deployment: image builds, scans clean, migration expand-and-contract, verified in Staging against the provider sandbox | [ ] | Staging report |

**No part is Done with an open High or Critical finding.** A Critical finding blocks deployment outright.

## Gate sign-off & Verification Governance

| Stage / Gate | What is Verified | Verifier (Decision Maker) | Approver | Pass Policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Append-only grants, RLS fail-closed, signature/replay/dedupe manifest matrix, no raw body in logs | CI pipeline (pytest) | Automated gate | **Hard block on failure** |
| **Gate 5 (Integrations)** | Webhook signature verification, replay rejection, dedupe on the provider identifier, idempotency, timeout ⇒ non-terminal, reconciliation, outage playbook, sandbox test, vendor register | **Security Lead** | **CTO** + **Compliance Lead** for the vendor position | Fails the gate; the integration is not enabled in production. **Conditional pass only** for contractual terms under review, marked REQUIRES LEGAL/REGULATORY VALIDATION, with an expiry and no production enablement |
| **Clinical sign-off** | Dispense-confirmation semantics, terminal-state guard, quarantine alert path | **Clinical Safety Officer** | Practice Owner | **Cannot be waived** |
| **Independent compliance** | Quarantine storage, audit integrity, retention position | **Privacy Officer / Compliance Lead** | External auditor | Pre-launch / periodic |
| **Any change to the webhook contract** | Signature scheme, replay window, dedupe key, tenant routing | Security Lead | CTO + CSO | **Gate 5 re-run required** |

**No self-approval.** The person who delivered the work never signs its gate.

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Only a signed provider event can change dispatch state | HMAC/asymmetric verification over the raw body before parsing | `verify_webhook` | S1, S8, S10 | Security Lead | planned |
| A captured event cannot be replayed | 5-minute window plus `UNIQUE (provider, provider_event_id)` | dedupe insert | S2, S7, S18 | Security Lead | planned |
| Tenant is never taken from a path or header | Tenant resolved from the verified payload | `resolve_tenant(payload)` | S3, S9, S16 | Security Lead | planned |
| A no-tenant payload cannot write tenant state | Quarantine, alert, `202` | quarantine path (OPEN-2) | S3 | CTO | planned |
| A terminal state cannot regress | Ordering compare plus terminal guard trigger | `trg_pharmacy_dispatch_terminal` | S4, F8 | Clinical Safety Officer | planned |
| The webhook surface is bounded | 256 KB cap, JSON only, 600/min per provider | request limits | S5, S6, S11 | Head of Platform | planned |
| An outage is never reported as success | Non-terminal state plus reconciliation | `REQUIRES_RECONCILIATION` | S17, A2 | Clinical Safety Officer | planned |
| The event log cannot be altered | `GRANT SELECT, INSERT`; `REVOKE UPDATE, DELETE, TRUNCATE` | `information_schema.role_table_grants` inspection | S15, F7 | Security Lead | planned |
| Clinical content never reaches a log | Raw body in memory only; `payload_sha256` persisted | classification enforcement in CI | S13, A4 | Privacy Officer | planned |
| Health data stays in Australia | Region-pinned storage | `ap-southeast-2` | register entry | Compliance Lead | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 webhook mount point (`10 §7` `/webhooks/:provider` vs `02 §11` `/pharmacy/webhooks/*`) | Head of Platform + Security Lead | OPEN |
| OPEN-2 quarantine storage for a no-tenant payload (sentinel tenant, nullable tenant, or a separate un-scoped table) | Security Lead + CTO | OPEN |
| OPEN-3 reason-code vocabulary and content-type HTTP code | CTO + Security Lead | OPEN |
| OPEN-4 provider contract terms, residency and sub-processor status | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 quarantined-payload retention and raw-body persistence | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-6 proposed audit action names absent from `07 §1` | Compliance Lead + CTO | OPEN |
| OPEN-7 `webhook_events` retention period | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
