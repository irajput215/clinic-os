---
doc_id: OZ-FEAT-13-REQ
title: "Integration boundaries — requirements"
owner: Head of Platform
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-13
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md
  - clinic-os-secure-by-design/16-vendor-register.md
  - clinic-os-secure-by-design/26-security-gates.md §6
  - clinic-os-secure-by-design/02-security-architecture.md §6, §11
repo_docs:
  - 02-user-stories.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Integration boundaries: requirements

## Purpose

Every third-party flow is **documented, authenticated, bounded and reconciled**, and **no integration
can write clinical state without a human decision**. Every external provider is untrusted, including
one under contract: a provider on a private link is still untrusted, and its response is validated as
untrusted input.

Source: `10-integration-boundaries.md` §1, §3; `26-security-gates.md` §6 Gate 5.

## Requirements and test traceability

| ID | Requirement | Acceptance criterion | Verified by (pytest path) |
|---|---|---|---|
| **R1** | Register before merge | A new integration is not merged until the integration register (`03-design.md`), the residency register (`13-data-residency.md` §3) and the vendor register (`16-vendor-register.md` §2) each carry a row. Absence fails the config check | `tests/integrations/test_register.py::test_unregistered_provider_fails_config_check` |
| **R2** | Fixed sequence | Every outbound call that changes clinical or financial state runs internal validation → security check → domain (TGA approval) check → audit write → external call, in that order. Reversing the order is a defect | `tests/integrations/test_ordering.py::test_audit_intent_committed_before_external_call` |
| **R3** | One adapter per provider | One interface per provider; no module imports a provider client directly; a simulated driver serves CI | `tests/integrations/test_adapter_contract.py::test_no_module_imports_provider_client` |
| **R4** | Bounded calls | Connect and read timeout per provider, overall deadline (20 s user-facing, 60 s background), ≤4 attempts, exponential backoff with full jitter, transient failures only | `tests/integrations/test_adapter_contract.py::test_retry_is_bounded_and_jittered` |
| **R5** | Idempotency key mandatory | Every state-changing outbound call carries a server-derived key; the adapter refuses to construct a request without one, or with a key that does not match its attempt row | `tests/integrations/test_adapter_contract.py::test_adapter_requires_idempotency_key` |
| **R6** | Circuit breaker and bulkhead | Per provider and per operation: opens after 10 failures in 30 s or a 50% failure rate over 20 calls; 30 s open; 3-request half-open probe. Separate pool per provider | `tests/integrations/test_circuit_breaker.py::test_circuit_breaker_opens_and_recovers` |
| **R7** | Unknown outcome is non-terminal | A timeout or unparsable body becomes an explicit non-terminal state (`REQUIRES_RECONCILIATION`), **never** success and never failure | `tests/integrations/test_unknown_outcome.py::test_timeout_becomes_non_terminal` |
| **R8** | Reconciliation | A 5-minute job resolves every non-terminal outbound write in both directions by provider reference and idempotency key, writes `reason = RECONCILED`, and escalates anything unresolved after 24 h | `tests/integrations/test_reconciliation.py::test_reconciliation_resolves_both_directions` |
| **R9** | Webhook validation before state change | Signature verified over the raw body before parsing; signed timestamp within 5 minutes; dedupe on `(provider, provider_event_id)`; tenant from the verified payload, never the path or a header; unknown tenant quarantined with `202` | `tests/integrations/test_webhooks.py::test_webhook_rejects_replay` |
| **R10** | No SSRF | The platform never fetches a tenant-, patient- or provider-supplied URL; egress is allow-listed at configuration time; private, loopback, link-local and metadata addresses are refused before the request | `tests/security/test_ssrf.py::test_metadata_endpoint_is_refused` |
| **R11** | Secrets | Credentials and signing secrets live only in Secrets Manager, referenced by ARN in `integration_credentials_refs`; never in an image, task definition, environment variable, log or repository. Per-environment credentials with a named owner and a rotation procedure | `tests/integrations/test_secrets.py::test_secrets_come_from_secret_store` |
| **R12** | Redacted integration logging | The integration log carries correlation ID, provider, operation, outcome class, latency and error class only — no patient identifier, prescription payload, address, medicine name, token or secret | `tests/security/test_integration_logs.py::test_logs_contain_no_phi` |
| **R13** | Human decision before clinical state | TGA ingestion cannot write a gating state without a human verification; no integration writes `active` approval state | `tests/integrations/test_human_gate.py::test_ingestion_cannot_write_gating_state` |
| **R14** | Environment isolation | Development, Staging and Production hold separate credentials, queues and buckets; no shared provider account where the provider supports separation | `tests/integrations/test_environments.py::test_production_and_development_credentials_differ` |
| **R15** | Transit floor | TLS 1.2 minimum, certificate validation on; no certificate pinning without a published rotation plan; request signing (HMAC or mTLS) where the provider supports it | `tests/integrations/test_tls.py::test_tls_below_1_2_is_refused` |
| **R16** | Strict inbound schema | Every inbound payload is validated against a strict schema before use; unknown fields are rejected, not ignored; body ≤256 KB (`413`) and `application/json` only | `tests/integrations/test_webhooks.py::test_unknown_field_is_rejected` |
| **R17** | Tenant boundary | Cross-tenant access returns `404`, never `403`; denied and failed attempts are audited with the same fidelity as successes | `tests/integrations/test_isolation.py::test_cross_tenant_integration_read_returns_404` |
| **R18** | Outage playbook | Each rail has a written outage position naming an owner and the clinical fallback; a provider outage never silently stalls a clinical workflow | `tests/integrations/test_register.py::test_every_registered_provider_has_outage_playbook` |
| **R19** | Vendor onboarding gate | No vendor receives data before the ten-step gate (`16` §3) passes; the minimum-data rule is enforced by a payload allow-list test | `tests/integrations/test_minimum_data.py::test_payload_contains_only_approved_fields` |

## Out of scope for this feature (Phase 3)

| Item | Why |
|---|---|
| Tyro payments and its webhooks | `10-integration-boundaries.md` §6; not in the Phase 3 sprint (`23-sprint-plan.md` §5) |
| Production enablement of any rail | Gate 7 owns release; Phase 3 builds production but does not enable it |
| Real-time prescription monitoring integration | Jurisdiction matrix **REQUIRES LEGAL/REGULATORY VALIDATION** (`09-prescription-safety-gate.md` Open item 3) |
| OCR service onboarding | Vendor `V-07`; owned by FEAT-09 (TGA inbox). It is a registered sub-processor flow, not a rail in the `10` §2 integration register |
| Minting eScript barcodes or signing on the prescriber's behalf | `10-integration-boundaries.md` §5 — ClinicOS transmits, it does not mint |
| Reconciliation UI and webhook replay tooling | Named scope-cut items in `23-sprint-plan.md` §7 |

## Open items

| # | Item | Owner | Status |
|---|---|---|---|
| OPEN-1 | OCR service appears in the vendor register (`16` §2 V-07) and residency register (`13` §3 DR-07) but **not** in the `10` §2 integration register — a registered data flow with no integration-register row | Head of Platform | OPEN |
| OPEN-2 | Contract terms (rate limits, processing location, liability) for Parchment, Tyro, notifications and the identity provider | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-3 | Whether request signing is supported by each provider, and the exact scheme | Head of Integrations | OPEN |
| OPEN-4 | Residency and support locations for every provider; no row in `13` §3 is `OFFSHORE-APPROVED` today | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 | No source document defines the provider-outage playbook artefact required by Gate 5 | Head of Platform + CSO | OPEN |
| OPEN-6 | Webhook path conflict: `/webhooks/:provider` (`10` §7) vs `/pharmacy/webhooks/*` (`02` §11) | Head of Platform | OPEN |
