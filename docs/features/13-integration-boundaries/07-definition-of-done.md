---
doc_id: OZ-FEAT-13-DOD
title: "Integration boundaries — definition of done"
owner: Head of Platform + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-13
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/26-security-gates.md §6
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/17-compliance-control-matrix.md
  - clinic-os-secure-by-design/16-vendor-register.md §3, §5, §6
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Definition of Done

The six parts are from `24`. Tick only with a link to evidence.

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | **Functional:** every acceptance criterion in `01-requirements.md` R1–R19 has a passing test; the register row, adapter interface and simulated driver exist | [ ] | F1–F26 output |
| 2 | **Security:** five-step sequence enforced, deny-by-default path, RLS, idempotency, SSRF allow-list, redaction and per-environment credentials implemented | [ ] | S1–S14 output; adapter test report |
| 3 | **Security tests pass in CI:** S1–S14 and the grant-inspection test, with no Critical finding | [ ] | CI run record; `information_schema.role_table_grants` extract |
| 4 | **Audit:** `integration.request` and provider-effect events emitted with the full envelope; A1–A3 | [ ] | A1–A3 output |
| 5 | **Operations & compliance:** classification applied, no PHI in logs, residency and vendor registers updated, outage playbook written per rail, logs/metrics/alerts present | [ ] | Register rows; outage playbooks; dashboards |
| 6 | **Deployment:** image builds, scans clean, migration expand-and-contract, verified in Staging, and **not enabled** in Production | [ ] | Staging verification; scan reports |

**No part is Done with an open High or Critical finding.** T-13.1, T-13.2, T-13.3, T-13.4, T-13.5,
T-13.6, T-13.8, T-13.9, T-13.10, T-13.12, T-13.13 and T-13.15 are inherent High; each must carry a
residual band and a passing control test before Gate 5.

## Gate sign-off & Verification Governance

Who verifies these controls and signs the gate. **The person who delivered the work never signs its
gate** (no self-approval).

| Stage / Gate | What is verified | Verifier (decision maker) | Approver | Pass policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Grant inspection on `integration_credentials_refs` and `webhook_events` (S10), redaction sentinel (S7), import rule (S14), SSRF suite (S1–S6) | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 5 (Integrations)** | Data-flow record per provider; credentials per environment with a named owner and rotation; webhook signature and replay; idempotency; timeouts become non-terminal and reconcile; **the provider-outage playbook names an owner and a clinical fallback**; sandbox test passes end to end; vendor terms, region and sub-processor status recorded; **TGA ingestion cannot write a gating state without a human verification** | **Security Lead** | **CTO**, plus the **Compliance Lead** for the vendor position | No conditional pass for the SSRF, idempotency or human-verification checks |
| **Conditional pass** | A provider whose data-flow record is complete but whose contractual terms are under review | Security Lead | CTO + Compliance Lead | Permitted only with an expiry and **no production enablement**, marked **REQUIRES LEGAL/REGULATORY VALIDATION**; Parchment contract terms are exactly this case |
| **Independent compliance** | Vendor evidence, residency position, sub-processor list, exit and deletion terms | Privacy Officer / Compliance Lead | External auditor | Pre-launch and annual |

**The human-decision rule.** TGA ingestion cannot write a gating state without a human verification.
A failed verification, a refused webhook and a blocked dispatch are all audited with the same fidelity as
a success, and a failure to write the audit event fails the operation.

## Control-matrix rows fed by this feature

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| No integration bypasses internal validation | Fixed sequence: validation → security → domain → audit → external call | Adapter interface; request path in `03-design.md` | F7, F8 | Head of Platform | planned |
| Provider credentials live only in a managed secret store | Per-environment secrets with rotation; no secret in an image, task definition or repo | Secret-store adapter; `integration_credentials_refs` ARN only | F25, S9, S10 | Security Lead | planned |
| Every provider call is bounded and idempotent | Timeouts, capped retry with jitter, breaker, bulkhead, idempotency key | Adapter configuration | F1–F3, F13 | Head of Platform | planned |
| Inbound events are validated before any state change | Signature, replay window, payload-derived tenant routing, strict schema | `/webhooks/:provider`; `webhook_events` | F14–F21 | Security Lead | planned |
| No patient information in an integration log | Structured logs with correlation ID and outcome class only | Redaction allow-list; sentinel scan | S7 | Privacy Officer | planned |
| A forged request cannot reach an internal service | Egress allow-list, resolver checks, metadata restricted, no supplied URL fetched | Outbound HTTP client policy | S1–S6 | Security Lead | planned |
| Production shares nothing with development | Separate credentials, queues, buckets, databases | Per-environment configuration | F24 | CTO | planned |
| The conformant party for the e-prescribing rail is identified | Adapter behind one interface; conformance stays with the certified party | Parchment adapter | Sandbox report (F26) | CTO | REQUIRES LEGAL/REGULATORY VALIDATION |
| Vendor onboarding gate and evidence standard | Residency check, contractual flow-down, tiered evidence before onboarding | Onboarding gate; vendor register; evidence store | Register rows; five-condition test | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Data return and deletion on exit | Decommissioning procedure with a deletion certificate | `16` §5 procedure | Deletion certificates | Compliance Lead | planned |
| The TGA correspondence channel is an untrusted boundary | Mailbox restricted; transport, retention and handling obligations recorded | Inbox pipeline; mailbox configuration | Register row; F23 | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| Parchment contract terms, rate limits, processing location and liability (`10` Open item 1) | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| Provider residency and support-access locations; no register row is `OFFSHORE-APPROVED` | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Sub-processor lists for every provider | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| No source document defines the provider-outage playbook artefact required by Gate 5 | Head of Platform + CSO | OPEN |
| OCR service has a vendor and residency row but no `10` §2 integration-register row | Head of Platform | OPEN |
| `payment.*` and standalone webhook actions are named in `10` §7 but absent from the `07` §1 catalogue | Security Lead | OPEN |
| `webhook_events` quarantine for a payload mapping to no tenant | Security Lead | OPEN |
| Webhook path `/webhooks/:provider` vs `/pharmacy/webhooks/*` | Head of Platform | OPEN |
| `secret_arn` SECRET (`04` §3.12) vs CONFIDENTIAL (`12` §5.1) | Privacy Officer | OPEN |
