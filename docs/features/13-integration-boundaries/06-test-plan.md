---
doc_id: OZ-FEAT-13-TEST
title: "Integration boundaries — test plan"
owner: Security Lead + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-13
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md §10
  - clinic-os-secure-by-design/26-security-gates.md §6
  - clinic-os-secure-by-design/27-security-testing.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md §11
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI on synthetic data and a simulated provider driver. A failing security test blocks
merge. Every test below is executed by its own command, in the form
`cd backend && uv run pytest tests/<area>/<file>.py::<test> -v`.

```bash
# Whole feature, for local iteration
cd backend && uv run pytest tests/integrations tests/security/test_ssrf.py tests/isolation/test_integration_isolation.py -v
```

## Functional tests (F)

| ID | Case | Expected result | Exact command |
|---|---|---|---|
| **F1** | Construct a dispatch request without a key | Refused by the adapter before any call | `cd backend && uv run pytest tests/integrations/test_adapter_contract.py::test_adapter_requires_idempotency_key -v` |
| **F2** | Five simulated transient failures | ≤4 attempts, non-uniform (jittered) delays | `cd backend && uv run pytest tests/integrations/test_adapter_contract.py::test_retry_is_bounded_and_jittered -v` |
| **F3** | Failure threshold exceeded, then recovery | Breaker opens, fails fast, half-opens after 30 s, recovers | `cd backend && uv run pytest tests/integrations/test_circuit_breaker.py::test_circuit_breaker_opens_and_recovers -v` |
| **F4** | Saturate the Parchment pool | Identity provider and payment calls still complete | `cd backend && uv run pytest tests/integrations/test_bulkhead.py::test_bulkhead_isolates_providers -v` |
| **F5** | Provider config absent from the register | Config check fails; rail cannot be enabled | `cd backend && uv run pytest tests/integrations/test_register.py::test_unregistered_provider_fails_config_check -v` |
| **F6** | Registered provider with no outage playbook | Config check fails; playbook must name owner and clinical fallback | `cd backend && uv run pytest tests/integrations/test_register.py::test_every_registered_provider_has_outage_playbook -v` |
| **F7** | Successful outbound call | Intent event is committed **before** the external call is made | `cd backend && uv run pytest tests/integrations/test_ordering.py::test_audit_intent_committed_before_external_call -v` |
| **F8** | External call forced to fail after the intent commit | The committed intent event is still present for reconciliation | `cd backend && uv run pytest tests/integrations/test_ordering.py::test_forced_call_failure_still_leaves_intent_event -v` |
| **F9** | Provider read timeout | State is `REQUIRES_RECONCILIATION`; audit `result = UNKNOWN`; never `DISPATCHED` or `FAILED` | `cd backend && uv run pytest tests/integrations/test_unknown_outcome.py::test_timeout_becomes_non_terminal -v` |
| **F10** | Truncated or unparsable response body | `REQUIRES_RECONCILIATION`, treated as unknown, not failure | `cd backend && uv run pytest tests/integrations/test_unknown_outcome.py::test_malformed_body_is_unknown_not_failure -v` |
| **F11** | Reconciliation over non-terminal rows | Resolves both directions by provider reference and idempotency key; `reason = RECONCILED` | `cd backend && uv run pytest tests/integrations/test_reconciliation.py::test_reconciliation_resolves_both_directions -v` |
| **F12** | Reconciliation run concurrently | Idempotent; no duplicate effect; unresolved rows escalate at 24 h | `cd backend && uv run pytest tests/integrations/test_reconciliation.py::test_reconciliation_is_concurrent_safe -v` |
| **F13** | Duplicate idempotency key retry | Original outcome returned; one dispatch; one attempt row | `cd backend && uv run pytest tests/integrations/test_idempotency.py::test_duplicate_key_returns_original_outcome -v` |
| **F14** | Provider event without a signature | `401`, state unchanged, `integration.request` `DENIED` | `cd backend && uv run pytest tests/integrations/test_webhooks.py::test_webhook_rejects_bad_signature -v` |
| **F15** | Replayed event inside the window | `200` with no second state change; dedupe on `(provider, provider_event_id)` | `cd backend && uv run pytest tests/integrations/test_webhooks.py::test_webhook_rejects_replay -v` |
| **F16** | Signed timestamp older than 5 minutes | Refused; no state change | `cd backend && uv run pytest tests/integrations/test_webhooks.py::test_webhook_rejects_old_timestamp -v` |
| **F17** | Payload names tenant B on tenant A's path | Tenant B is affected; the path is ignored | `cd backend && uv run pytest tests/integrations/test_webhooks.py::test_webhook_routes_by_payload_not_path -v` |
| **F18** | Payload maps to no tenant | `202`, quarantined, alerted; no clinical state change | `cd backend && uv run pytest tests/integrations/test_webhooks.py::test_webhook_unknown_tenant_is_quarantined -v` |
| **F19** | Payload with an unknown field | Strict schema rejects it; not silently ignored | `cd backend && uv run pytest tests/integrations/test_webhooks.py::test_unknown_field_is_rejected -v` |
| **F20** | Body over 256 KB, or wrong content type | `413` for size; `415` for content type | `cd backend && uv run pytest tests/integrations/test_webhooks.py::test_body_size_and_content_type_enforced -v` |
| **F21** | Stale/out-of-order provider event | Terminal state not regressed; event recorded; alert if repeated | `cd backend && uv run pytest tests/integrations/test_webhooks.py::test_stale_event_does_not_regress_terminal_state -v` |
| **F22** | Payload field set vs the approved minimum-data list | A field not on the list fails the test until the list is updated | `cd backend && uv run pytest tests/integrations/test_minimum_data.py::test_payload_contains_only_approved_fields -v` |
| **F23** | TGA ingestion attempts a gating state | Refused; ingestion lands `pending_verification` and requires human verification | `cd backend && uv run pytest tests/integrations/test_human_gate.py::test_ingestion_cannot_write_gating_state -v` |
| **F24** | Configuration across environments | No shared secret, bucket or queue between Development, Staging and Production | `cd backend && uv run pytest tests/integrations/test_environments.py::test_production_and_development_credentials_differ -v` |
| **F25** | Adapter credential lookup | No adapter reads a credential from an environment variable or a file | `cd backend && uv run pytest tests/integrations/test_secrets.py::test_secrets_come_from_secret_store -v` |
| **F26** | Parchment sandbox, seven scenarios | Successful dispatch, rejection, duplicate key, timeout, 5xx, malformed body, webhook replay all behave | `cd backend && uv run pytest tests/integrations/test_sandbox_e2e.py::test_parchment_sandbox_scenarios_pass -v` |

## Security tests (S)

| ID | Case | Expected result | Exact command |
|---|---|---|---|
| **S1** | Supplied URL resolves to a private address | Refused before the request is made | `cd backend && uv run pytest tests/security/test_ssrf.py::test_supplied_private_address_is_refused -v` |
| **S2** | Supplied URL resolves to loopback | Refused before the request is made | `cd backend && uv run pytest tests/security/test_ssrf.py::test_loopback_address_is_refused -v` |
| **S3** | Supplied URL targets the instance metadata endpoint | Refused; metadata service unreachable from the task | `cd backend && uv run pytest tests/security/test_ssrf.py::test_metadata_endpoint_is_refused -v` |
| **S4** | Call to an unregistered destination | Fails at the network layer; no route | `cd backend && uv run pytest tests/security/test_ssrf.py::test_unregistered_destination_has_no_route -v` |
| **S5** | Tenant-supplied callback URL | Never dereferenced; allow-listed by hostname at configuration time only | `cd backend && uv run pytest tests/security/test_ssrf.py::test_tenant_callback_url_is_not_fetched -v` |
| **S6** | URL inside a webhook payload | Never dereferenced by the handler | `cd backend && uv run pytest tests/security/test_ssrf.py::test_webhook_payload_url_is_not_dereferenced -v` |
| **S7** | Integration log and error telemetry | No patient identifier, medicine name, address or full payload (sentinel scan) | `cd backend && uv run pytest tests/security/test_integration_logs.py::test_logs_contain_no_phi -v` |
| **S8** | Provider offers TLS 1.1 | Handshake refused; TLS 1.2 is the floor, certificate validation on | `cd backend && uv run pytest tests/security/test_tls.py::test_tls_below_1_2_is_refused -v` |
| **S9** | Call presented with a superseded credential after rotation | Refused and audited; rotation overlap handled | `cd backend && uv run pytest tests/security/test_rotation.py::test_stale_credential_after_rotation_is_refused -v` |
| **S10** | Grant inspection on `integration_credentials_refs` | No `DELETE`/`TRUNCATE` for `clinos_app`; no column holds credential material; `webhook_events` is append-only | `cd backend && uv run pytest tests/security/test_integration_grants.py::test_credential_ref_and_webhook_grants -v` |
| **S11** | Clinic A requests a clinic B credential reference or webhook row | `404 Not Found` (no existence leak); denial audited | `cd backend && uv run pytest tests/isolation/test_integration_isolation.py::test_cross_tenant_integration_access_returns_404 -v` |
| **S12** | Missing tenant setting on the connection | Zero rows returned (fail-closed `NULLIF`), never all rows | `cd backend && uv run pytest tests/isolation/test_integration_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` |
| **S13** | Webhook replay spike / sensitive-write limit exceeded | `429`; a burst of invalid signatures is counted and alerted | `cd backend && uv run pytest tests/security/test_integration_rate_limits.py::test_webhook_burst_and_sensitive_write_limits -v` |
| **S14** | Static import rule | No application module imports a provider client directly | `cd backend && uv run pytest tests/security/test_integration_imports.py::test_no_module_imports_provider_client -v` |

## Audit tests (A)

| ID | Case | Expected result | Exact command |
|---|---|---|---|
| **A1** | Each outbound provider call | One `integration.request` with the full envelope (`provider`, `outcome`, `latency_ms`, `correlation_id`) | `cd backend && uv run pytest tests/integrations/test_audit.py::test_each_outbound_call_emits_integration_request -v` |
| **A2** | Each refused webhook | `integration.request` `result = DENIED` with a reason, at the same fidelity as a success | `cd backend && uv run pytest tests/integrations/test_audit.py::test_denied_webhook_audited_with_equal_fidelity -v` |
| **A3** | Audit write fails | The operation does not complete (fail closed) and an alert is raised | `cd backend && uv run pytest tests/integrations/test_audit.py::test_audit_write_failure_fails_the_operation -v` |

## CI pipeline hooks

SAST, dependency scan, container scan and secret scan run on every pull request; the S-series and the
grant-inspection test run on every pull request; the sandbox suite (F26) runs in Staging before any
adapter change reaches Production.

## Traceability

F1–F26 cover R1–R19 in `01-requirements.md`; S1–S14 cover the security criteria in `02-user-stories.md`
and the controls in `04-threat-model.md` (T-13.1–T-13.16); A1–A3 cover the event catalogue in
`05-data-and-audit.md`. Every row in the F/S/A tables maps to at least one requirement or threat.
