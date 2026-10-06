---
doc_id: OZ-SDLC-03-TASKS
title: Phase 3 — e-Prescribing task list
owner: Delivery Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
phase: 3 — e-Prescribing
gate: Gate 4 (APIs, prescribing) · Gate 5 (Integrations, Parchment complete) · Gate 6 (preparation)
source:
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/10-integration-boundaries.md
  - clinic-os-secure-by-design/27-security-testing.md
  - clinic-os-secure-by-design/26-security-gates.md
---

> **The phase specification this list was written against has been superseded** by the numbered feature folders under [`../features/`](../features/). Requirements, design, threats, data handling, tests and the Definition of Done now live there, one folder per feature.

# Phase 3 — e-Prescribing Tasks

A task is not started until `spec.md` is approved (`docs/reference/build-contract.md` §4). Control numbers refer to
the twelve controls in [`docs/reference/build-contract.md`](../reference/build-contract.md#6-the-twelve-controls-every-feature-implements).
Every task adds its negative path first.

## A. Parchment adapter boundary

- [ ] **T3-1 — Parchment adapter interface and one concrete adapter**
  - Acceptance: One interface `dispatch(request, idempotency_key, deadline) -> Confirmed | Rejected | ExplicitUnknown | AdapterError`; one concrete adapter implements it; no other module declares a dispatch method; the adapter refuses to construct a request without an idempotency key and refuses a key that does not match the `dispatch_attempts` row it is dispatching
  - Verify: `cd backend && uv run pytest tests/unit/test_parchment_adapter_contract.py -v`
  - Files: `backend/app/modules/pharmacy/parchment_adapter.py`, `backend/app/modules/pharmacy/parchment_types.py`
  - Controls: 4 Input validation, 9 Error handling, 11 Security testing
  - Evidence: Adapter contract test output; the interface definition in the pull request

- [ ] **T3-2 — Per-environment credentials with a named owner and rotation procedure**
  - Acceptance: Credentials are read from the secret store, never from an environment variable, an image, a file or the repository; per environment and per organisation; a named owner and a documented rotation procedure exist; Development and Staging share no credential with Production
  - Verify: `cd backend && uv run pytest tests/security/test_secrets_come_from_secret_store.py -v` plus a credential inventory artefact
  - Files: `backend/app/core/config.py`, `backend/app/core/secrets.py`, credential inventory under the milestone evidence bundle
  - Controls: 8 Secrets management, 7 Encryption, 12 Compliance evidence
  - Evidence: Credential inventory (environment, secret-store reference, owner, rotation date) — Gate 5

- [ ] **T3-3 — Timeout, bounded retry with jitter, circuit breaker and bulkhead**
  - Acceptance: Connect 3 s and read 15 s with an overall deadline of 20 s user-facing and 60 s background; at most 4 attempts on transient failures only with full jitter (1 s, 4 s, 16 s, 64 s cap); a validation failure is never retried; the breaker opens after 10 failures in 30 s or 50 % over 20 calls, stays open 30 s and half-opens with 3 probes; a saturated provider pool does not block other providers; a provider `429` is respected with `Retry-After`
  - Verify: `cd backend && uv run pytest tests/unit/test_parchment_resilience.py -v`
  - Files: `backend/app/modules/pharmacy/parchment_adapter.py`, `backend/app/core/resilience.py`
  - Controls: 9 Error handling, 10 Abuse protection
  - Evidence: Resilience test output (`integration.retry_is_bounded_and_jittered`, `integration.circuit_breaker_opens_and_recovers`, `integration.bulkhead_isolates_providers`)

- [ ] **T3-4 — Redacted request and response logging**
  - Acceptance: The integration log carries correlation id, provider, operation, outcome class, latency and error class only; no patient identifier, prescription payload, address or medicine name; the request body is never a log argument at any level; the sentinel scan finds zero hits
  - Verify: `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py -v`
  - Files: `backend/app/modules/pharmacy/parchment_adapter.py`, `backend/app/core/logging.py`
  - Controls: 5 Output validation, 9 Error handling, 7 Encryption
  - Evidence: Sentinel test output (`integration.logs_contain_no_phi`)

- [ ] **T3-5 — Simulated Parchment driver for CI**
  - Acceptance: A simulated driver implements the same interface and returns scripted `Confirmed`, `Rejected`, `ExplicitUnknown`, timeout, 5xx and malformed-body outcomes; it records every call so a no-outbound-call assertion is possible; no test imports the real Parchment client
  - Verify: `cd backend && uv run pytest tests/integration/test_dispatch_flow_simulated.py -v`
  - Files: `backend/tests/fakes/parchment_driver.py`
  - Controls: 11 Security testing, 4 Input validation
  - Evidence: Simulated-flow test output; call log used by the negative dispatch matrix

## B. Prescription workflow and state machine

- [ ] **T3-6 — `prescriptions`, `prescription_events`, `prescription_state_history` migrations**
  - Acceptance: Every table has `tenant_id NOT NULL`, RLS enabled and `FORCED` with `USING` and `WITH CHECK`; the state column is constrained to the canonical state set; the indexes in `spec.md` §4.1–§4.3 exist; the application role owns nothing and has no `BYPASSRLS`; migrations round-trip
  - Verify: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
  - Files: `backend/app/modules/prescribing/models.py`, `backend/app/alembic/versions/*`
  - Controls: 3 Tenant isolation, 6 Audit logging, 4 Input validation
  - Evidence: Migration output; RLS policy listing; schema lint output

- [ ] **T3-7 — Server-side state machine with history**
  - Acceptance: Only the canonical transitions in `phase.md` §6 are accepted; an illegal transition is refused and audited; every accepted transition writes `prescription_state_history` and `prescription_events` in the same transaction as the state change; `SIGNED` is immutable and a correction is an addendum
  - Verify: `cd backend && uv run pytest tests/unit/test_prescription_state_machine.py -v`
  - Files: `backend/app/modules/prescribing/service.py`, `backend/app/modules/prescribing/state_machine.py`
  - Controls: 2 Authorisation, 4 Input validation, 6 Audit logging
  - Evidence: State-machine test output; a sample history row set

- [ ] **T3-8 — `POST /prescriptions` and `POST /api/v1/prescriptions/{id}/sign`**
  - Acceptance: Both endpoints match their declarations in `spec.md` §5; sign requires `prescription:sign`, the prescriber of record, state `DRAFT`, and a fresh 2-minute single-use resource-bound step-up; a nurse cannot sign; an unauthenticated request is refused; unknown fields are rejected; responses serialise through the declared schema
  - Verify: `cd backend && uv run pytest tests/integration/test_prescription_workflow.py -v`
  - Files: `backend/app/modules/prescribing/router.py`, `backend/app/modules/prescribing/schemas.py`, `backend/app/api/routes/prescriptions.py`
  - Controls: 1 Authentication, 2 Authorisation, 4 Input validation, 5 Output validation, 6 Audit logging
  - Evidence: Workflow test output; endpoint declaration inventory row — Gate 4

- [ ] **T3-9 — `GET /prescriptions`, `GET /api/v1/prescriptions/{id}`, `GET /api/v1/prescriptions/{id}/dispatch`, `POST /api/v1/prescriptions/{id}/cancel`**
  - Acceptance: Read routes are cursor-paginated with signed tenant-bound cursors and a bounded `limit`; `approval_status` is exposed on the detail response for the frontend caution message; cancel requires a reason and refuses a `CONFIRMED` prescription (reversal is separate); the permission gaps in `spec.md` §14 O1 are recorded and the interim mapping is used, not a new permission name
  - Verify: `cd backend && uv run pytest tests/integration/test_prescription_reads.py tests/integration/test_prescription_cancel.py -v`
  - Files: `backend/app/modules/prescribing/router.py`, `backend/app/modules/prescribing/schemas.py`
  - Controls: 2 Authorisation, 3 Tenant isolation, 5 Output validation, 9 Error handling
  - Evidence: Read/cancel test output; cursor-replay-across-tenants test output — Gate 4

## C. The prescription safety gate

- [ ] **T3-10 — The gate module with one entry point and the fixed order**
  - Acceptance: One module exports `evaluate_dispatch_gate(ctx) -> GateResult`; the order is exactly `authenticate → authorise → patient access → medication → category → dosage form → approval lookup → validity → clinical checks → audit → dispatch`; the function takes no `skip`, `force` or `override` parameter and no feature flag gates it; every block path returns before the adapter is reached
  - Verify: `cd backend && uv run pytest tests/unit/test_gate_pipeline_order.py -v`
  - Files: `backend/app/modules/prescribing/safety_gate.py`
  - Controls: 2 Authorisation, 4 Input validation, 9 Error handling
  - Evidence: Pipeline-order test output; the single entry-point definition — Gate 4, Clinical Safety Officer

- [ ] **T3-11 — Approval lookup and validity at the grain and `date_of_service`**
  - Acceptance: The lookup is one tenant-scoped query on `patient_id + tga_category + dosage_form`; validity requires `ACTIVE` and `valid_from <= date_of_service <= valid_to` in `Australia/Sydney` at day granularity; the application clock is not used for expiry; each row of the decision table in `spec.md` §2.6 yields its distinct block reason; a supersede chain resolves to the current record and the audit names it
  - Verify: `cd backend && uv run pytest tests/unit/test_approval_lookup_decision_table.py tests/unit/test_validity_boundary_sydney.py -v`
  - Files: `backend/app/modules/prescribing/safety_gate.py`, `backend/app/modules/tga_approvals/read_service.py`
  - Controls: 2 Authorisation, 3 Tenant isolation, 4 Input validation
  - Evidence: Decision-table test output; Sydney boundary test (`23:59` on `valid_to` passes, `00:01` fails)

- [ ] **T3-12 — `SELECT ... FOR SHARE` on the approval row**
  - Acceptance: The approval row is locked `FOR SHARE` inside the same transaction that inserts `dispatch_attempts` and moves the state to `SUBMITTING`; the lock is taken before the state change and released only at commit; a `SELECT` outside the transaction is a defect and is caught by review
  - Verify: `cd backend && uv run pytest tests/security/test_dispatch_concurrent_revocation_blocks.py -v`
  - Files: `backend/app/modules/prescribing/safety_gate.py`
  - Controls: 3 Tenant isolation, 2 Authorisation
  - Evidence: Raced-revocation test output — Gate 4

- [ ] **T3-13 — Blocked-attempt audit and fail-closed audit write**
  - Acceptance: Every gate step 4–9 block writes `prescription.dispatch_blocked` with `result = DENIED`, the specific `block_reason` and the missing dimension, exactly once per refused request, even when the caller cannot see the approval state; if the audit insert fails, the transaction rolls back, no dispatch attempt exists and no provider call is made; an unauditable dispatch never happens
  - Verify: `cd backend && uv run pytest tests/security/test_blocked_dispatch_audited.py tests/security/test_audit_write_failure_rolls_back_dispatch.py -v`
  - Files: `backend/app/modules/prescribing/safety_gate.py`, `backend/app/core/audit.py`
  - Controls: 6 Audit logging, 9 Error handling, 2 Authorisation
  - Evidence: Blocked-audit test output; rollback test output — Gate 4

- [ ] **T3-14 — No-bypass static rules**
  - Acceptance: A repository import rule fails the build when the Parchment dispatch client is imported by any module other than the safety gate, including from a test; a code search for `skip`, `force` and `override` in the gate module reports zero matches; the static test reports zero violations
  - Verify: `cd backend && uv run pytest tests/security/test_no_other_module_imports_parchment_client.py -v` and `cd backend && uv run ruff check .`
  - Files: `backend/pyproject.toml` (import-restriction configuration), `backend/tests/security/test_no_other_module_imports_parchment_client.py`
  - Controls: 11 Security testing, 2 Authorisation, 12 Compliance evidence
  - Evidence: Static test output with zero violations — Gate 4

- [ ] **T3-15 — `POST /api/v1/prescriptions/{id}/dispatch`**
  - Acceptance: The endpoint matches its declaration in `spec.md` §5; it requires `prescription:dispatch` and a fresh 2-minute single-use resource-bound step-up; the body schema accepts no approval, tenant, role or state field and rejects unknown fields; a pass commits the attempt and audit before any external call; the response is `202`/`502`/`422`/`409`/`500` per `spec.md` §2.2; the frontend message is rendered from the response, never from a local copy
  - Verify: `cd backend && uv run pytest tests/integration/test_dispatch_endpoint.py -v`
  - Files: `backend/app/modules/prescribing/router.py`, `backend/app/modules/prescribing/schemas.py`, `backend/app/api/routes/prescriptions.py`
  - Controls: 1 Authentication, 2 Authorisation, 4 Input validation, 5 Output validation, 6 Audit logging
  - Evidence: Dispatch endpoint test output; endpoint declaration inventory row — Gate 4

## D. Mandatory safety tests

- [ ] **T3-16 — Negative dispatch matrix**
  - Acceptance: Every negative case — no approval; each of `EXPIRED`, `REVOKED`, `PENDING`, `REJECTED`, `SUPERSEDED`; window not covering `date_of_service`; future validity; wrong dosage form; wrong category; wrong patient; canary-tenant approval — is blocked with the failing dimension named, writes one `prescription.dispatch_blocked`, and makes **no** outbound call; the matrix is data-driven so a new row is one case, not one function
  - Verify: `cd backend && uv run pytest tests/security/test_negative_dispatch_matrix.py -v`
  - Files: `backend/tests/security/test_negative_dispatch_matrix.py`, `backend/tests/fixtures/approval_grain.py`
  - Controls: 11 Security testing, 2 Authorisation, 6 Audit logging
  - Evidence: Negative dispatch matrix output — Gate 4 evidence (`gates.md`)

- [ ] **T3-17 — Forged approval flag is ignored and audited**
  - Acceptance: A request that sets an approval flag, an `approval_id`, a `tenant_id`, a `role` or a `state` in the body, a header or the query string has every one of those ignored; the server recomputes from the database; the outcome follows the database state; the bypass attempt is audited as a blocked dispatch with a bypass reason and raises a security signal metric
  - Verify: `cd backend && uv run pytest tests/security/test_forged_approval_flag_ignored.py -v`
  - Files: `backend/tests/security/test_forged_approval_flag_ignored.py`
  - Controls: 2 Authorisation, 4 Input validation, 6 Audit logging
  - Evidence: Forged-flag test output — Gate 4 (US-23)

- [ ] **T3-18 — Direct API call bypassing the UI**
  - Acceptance: A hand-crafted request with a valid access token and a fresh step-up factor, with no browser session that rendered the prescription, is refused identically when no approval exists, and the response message is exactly `"Active TGA Approval Required"`
  - Verify: `cd backend && uv run pytest tests/security/test_safety_gate_direct_api_call.py -v`
  - Files: `backend/tests/security/test_safety_gate_direct_api_call.py`
  - Controls: 2 Authorisation, 11 Security testing
  - Evidence: Direct-call test output (`safety_gate.direct_api_call_bypassing_ui_is_blocked`)

- [ ] **T3-19 — Audit-write failure rolls back and calls nothing**
  - Acceptance: With the audit insert forced to fail, the dispatch transaction rolls back, no `dispatch_attempts` row exists, the prescription state is unchanged and the simulated adapter records zero calls; the response is `500` with the standard envelope and no internals
  - Verify: `cd backend && uv run pytest tests/security/test_audit_write_failure_rolls_back_dispatch.py -v`
  - Files: `backend/tests/security/test_audit_write_failure_rolls_back_dispatch.py`
  - Controls: 6 Audit logging, 9 Error handling
  - Evidence: Rollback test output — Gate 4

- [ ] **T3-20 — Exactly one blocked event per refused request**
  - Acceptance: A refused dispatch writes exactly one `prescription.dispatch_blocked` with the correct reason; a refusal at step 4 does not also write a step 7 event; a repeated identical request writes a second event (each attempt is a security event) but never duplicates one attempt
  - Verify: `cd backend && uv run pytest tests/security/test_blocked_attempt_audited_once.py -v`
  - Files: `backend/tests/security/test_blocked_attempt_audited_once.py`
  - Controls: 6 Audit logging, 11 Security testing
  - Evidence: Audit-count test output

## E. Dispatch queue

- [ ] **T3-21 — `pharmacy_dispatches` and `dispatch_attempts` with the unique constraints**
  - Acceptance: `UNIQUE (tenant_id, idempotency_key)` and `UNIQUE (tenant_id, prescription_id, attempt_seq)` exist; `request_payload_hash` is stored and the payload is not; `attempt_seq` increments only for a new clinical intent; every tenant table has RLS and `FORCE`
  - Verify: `cd backend && uv run pytest tests/integration/test_dispatch_attempt_constraints.py -v`
  - Files: `backend/app/modules/pharmacy/models.py`, `backend/app/alembic/versions/*`
  - Controls: 3 Tenant isolation, 4 Input validation, 6 Audit logging
  - Evidence: Constraint test output; migration and policy listing

- [ ] **T3-22 — Queue port, visibility timeout and dead-letter alert**
  - Acceptance: Dispatch is queued through a port that carries no broker type; the queue is at-least-once and ordered per idempotency key; the visibility timeout exceeds the expected job duration; a permanently failing dispatch reaches the dead-letter queue and fires an alert with a runbook link and a named owner
  - Verify: `cd backend && uv run pytest tests/integration/test_dispatch_queue.py -v`
  - Files: `backend/app/modules/pharmacy/queue.py`, `backend/app/worker/dispatch_worker.py`
  - Controls: 9 Error handling, 10 Abuse protection, 12 Compliance evidence
  - Evidence: Queue test output; dead-letter alert definition — Gate 5

## F. Idempotency

- [ ] **T3-23 — `Idempotency-Key` on every client-initiated write**
  - Acceptance: Every write accepts an `Idempotency-Key`, stored as `key_hash` under `UNIQUE (tenant_id, route, key_hash)`; a retry returns the original status code and body; the same key with a different request hash is refused `409`; a missing key on a write is refused `422`
  - Verify: `cd backend && uv run pytest tests/integration/test_idempotency.py -v`
  - Files: `backend/app/core/idempotency.py`, `backend/app/api/dependencies.py`
  - Controls: 10 Abuse protection, 4 Input validation, 9 Error handling
  - Evidence: Idempotency test output — Gate 4/Gate 5

- [ ] **T3-24 — Server-computed dispatch key and the duplicate-request test**
  - Acceptance: The dispatch key is `sha256(tenant_id || prescription_id || intent_seq)` computed server-side; a client header is hashed into it rather than used raw; a transport retry reuses the key; a duplicate request reads the existing row and returns the recorded outcome; exactly one provider call and one attempt row result
  - Verify: `cd backend && uv run pytest tests/integration/test_duplicate_dispatch.py -v`
  - Files: `backend/app/modules/pharmacy/dispatch_service.py`
  - Controls: 10 Abuse protection, 6 Audit logging
  - Evidence: Duplicate test output (`safety_gate.double_dispatch_same_key_dispatches_once`)

- [ ] **T3-25 — Provider event identifier deduplication**
  - Acceptance: The provider event identifier is extracted by the adapter and stored on `dispatch_attempts.provider_event_id`; a repeated provider event updates the same row and does not create a second dispatch; the dedup index is `UNIQUE (provider, provider_event_id)`
  - Verify: `cd backend && uv run pytest tests/integration/test_provider_dedup.py -v`
  - Files: `backend/app/modules/pharmacy/webhook_service.py`, `backend/app/modules/pharmacy/parchment_adapter.py`
  - Controls: 10 Abuse protection, 4 Input validation
  - Evidence: Provider-dedup test output — Gate 5

## G. Webhooks

- [ ] **T3-26 — Signature verification and replay window**
  - Acceptance: The signature is verified over the raw body **before** parsing; the signed timestamp must be within 5 minutes of server time; an unsigned or wrongly signed payload returns `401`, changes no state and is counted; an old timestamp is refused; a burst of invalid signatures raises an alert
  - Verify: `cd backend && uv run pytest tests/integration/test_webhook_signature.py -v`
  - Files: `backend/app/modules/pharmacy/webhook_router.py`, `backend/app/modules/pharmacy/signature.py`
  - Controls: 1 Authentication, 4 Input validation, 10 Abuse protection
  - Evidence: Webhook signature test output (`integration.webhook_rejects_bad_signature`, `integration.webhook_rejects_old_timestamp`) — Gate 5

- [ ] **T3-27 — Dedup index, payload-derived tenant routing, fast acknowledgement, raw payload**
  - Acceptance: A duplicate event returns `200` with no second state change; the tenant is resolved from the verified payload and never from the path or a header, and a request to another tenant's path affects the payload's tenant only; `200` is returned only after the state change commits and a processing failure returns `500`; the raw payload is retained for verification and never logged; body over 256 KB returns `413` and a non-JSON body returns `415`
  - Verify: `cd backend && uv run pytest tests/integration/test_webhook_processing.py -v`
  - Files: `backend/app/modules/pharmacy/webhook_service.py`, `backend/app/modules/pharmacy/models.py`
  - Controls: 3 Tenant isolation, 5 Output validation, 9 Error handling
  - Evidence: Webhook processing test output (`integration.webhook_rejects_replay`, `integration.webhook_routes_by_payload_not_path`)

- [ ] **T3-28 — Forged and replayed webhook tests**
  - Acceptance: A forged signature is rejected with `401` and no state change; a replayed event inside the window is deduplicated with no second state change; an event outside the window is refused; a terminal state is not regressed by a stale event; an unmapped tenant is quarantined and returns `202` with no clinical state change
  - Verify: `cd backend && uv run pytest tests/security/test_webhook_forgery_and_replay.py -v`
  - Files: `backend/tests/security/test_webhook_forgery_and_replay.py`
  - Controls: 1 Authentication, 3 Tenant isolation, 11 Security testing
  - Evidence: Forgery/replay test output — Gate 5

## H. Reconciliation

- [ ] **T3-29 — Reconciliation job with explicit tenant context**
  - Acceptance: Runs every 5 minutes; selects attempts in `REQUIRES_RECONCILIATION`/`SUBMITTING` older than 60 s and prescriptions not terminal beyond 15 minutes; resolves both directions by `provider_reference` and idempotency key; writes `reason = RECONCILED` with the original `correlation_id`; escalates after 24 hours to the Clinical Safety Officer; is idempotent and concurrency-safe; runs with explicit tenant context and **fails loudly** without it
  - Verify: `cd backend && uv run pytest tests/integration/test_reconciliation_job.py -v`
  - Files: `backend/app/worker/reconciliation_job.py`, `backend/app/modules/pharmacy/reconciliation_service.py`
  - Controls: 3 Tenant isolation, 6 Audit logging, 9 Error handling, 12 Compliance evidence
  - Evidence: Reconciliation test output; runbook; failure alert definition — Gate 5

- [ ] **T3-30 — Forced timeout becomes `REQUIRES_RECONCILIATION`**
  - Acceptance: A simulated timeout, an absent response and a malformed body each move the prescription to `REQUIRES_RECONCILIATION`, write `prescription.dispatch_failed` with `result = UNKNOWN`, and **never** record success or a definitive failure; a 4xx and a 5xx-after-retries move it to `FAILED` instead
  - Verify: `cd backend && uv run pytest tests/integration/test_timeout_semantics.py -v`
  - Files: `backend/app/modules/pharmacy/dispatch_service.py`, `backend/tests/fakes/parchment_driver.py`
  - Controls: 9 Error handling, 6 Audit logging, 10 Abuse protection
  - Evidence: Timeout test output (`safety_gate.timeout_produces_requires_reconciliation`, `audit.timeout_writes_unknown_not_success`)

- [ ] **T3-31 — Reconciliation resolves the unknown state and does not duplicate**
  - Acceptance: When the provider confirms, the row moves to `CONFIRMED` with `reason = RECONCILED`; when the provider has no record, it moves to `FAILED` and alerts for human review; a resolved row is never re-dispatched; two concurrent job runs produce one resolution
  - Verify: `cd backend && uv run pytest tests/integration/test_reconciliation_resolution.py -v`
  - Files: `backend/app/modules/pharmacy/reconciliation_service.py`
  - Controls: 6 Audit logging, 9 Error handling, 11 Security testing
  - Evidence: Resolution test output (`safety_gate.reconciliation_resolves_unknown_outcome`, `safety_gate.reconciliation_does_not_duplicate`)

## I. Sandbox and end-to-end security

- [ ] **T3-32 — Parchment sandbox end-to-end**
  - Acceptance: The seven sandbox scenarios pass as a suite in Staging — successful dispatch, rejected dispatch, duplicate idempotency key, timeout, 5xx, malformed response, webhook replay — with synthetic data only and no production credential
  - Verify: `cd backend && uv run pytest tests/e2e -m sandbox -v` against Staging
  - Files: `backend/tests/e2e/test_parchment_sandbox.py`
  - Controls: 11 Security testing, 8 Secrets management, 7 Encryption
  - Evidence: Sandbox integration test report — Gate 5, Gate 6 preparation

- [ ] **T3-33 — The five security test categories with the access-control matrix**
  - Acceptance: Authentication, authorisation, prescription-gate, documents and API-abuse categories all pass; the access-control matrix in `27` §5 is executed as `authz.matrix` against the built endpoint inventory; horizontal and vertical escalation, cross-tenant read/list/write/export, injection, SSRF, rate-limit bypass, BOLA and mass assignment all fail to escalate
  - Verify: `cd backend && uv run pytest tests/security -v`
  - Files: `backend/tests/security/`
  - Controls: 11 Security testing, 2 Authorisation, 3 Tenant isolation, 10 Abuse protection
  - Evidence: Security test report for the five categories — Gate 4, Gate 6 preparation

- [ ] **T3-34 — Dispatch entry-point enumeration**
  - Acceptance: A test enumerates every route and every service function that can reach the dispatch adapter and asserts that exactly **one** entry point exists and that it is the gate; adding a second caller fails the test; a module-level import outside the gate fails the static rule (T3-14)
  - Verify: `cd backend && uv run pytest tests/security/test_dispatch_entry_points.py -v`
  - Files: `backend/tests/security/test_dispatch_entry_points.py`
  - Controls: 11 Security testing, 2 Authorisation, 12 Compliance evidence
  - Evidence: Enumeration test output — Gate 4 (Phase 3 risk R2 mitigation)

- [ ] **T3-35 — No PHI in logs, metrics, traces or error responses**
  - Acceptance: `SENTINEL-PATIENT-7F3A`, `SENTINEL-TOKEN-9C1D` and `SENTINEL-CLINICAL-4B2E` appear in no application log, audit event, metric label, trace span, error response or frontend bundle after the dispatch, block, webhook and reconciliation journeys
  - Verify: `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py -v` and `cd frontend && bun run test --grep storage-no-phi`
  - Files: `backend/tests/security/test_no_phi_in_log_payload.py`, `frontend-features/tests/security/storage-no-phi.spec.ts`
  - Controls: 5 Output validation, 9 Error handling, 7 Encryption, 11 Security testing
  - Evidence: Sentinel scan output (INV-5)

- [ ] **T3-36 — Frontend caution and server-side refusal are independent**
  - Acceptance: The Dispatch control is disabled while `approval_status` is not active and renders the message verbatim from the response; with the control disabled, a direct request is still refused; the disabled state is never the enforcement point; no approval or prescription clinical content is stored in browser storage
  - Verify: `cd frontend && bun run test --grep dispatch-approval` and `cd backend && uv run pytest tests/security/test_safety_gate_direct_api_call.py -v`
  - Files: `frontend-features/src/`, `frontend-features/tests/security/`
  - Controls: 5 Output validation, 2 Authorisation, 11 Security testing
  - Evidence: Frontend E2E output; storage-no-PHI output (INV-3)

## J. Gate evidence

- [ ] **T3-37 — Gate 4 evidence bundle**
  - Acceptance: The endpoint declaration inventory is complete for every Phase 3 route; the five-category security report, the negative dispatch matrix, the raced-revocation output, the entry-point enumeration output and the access-control matrix are assembled and each links to the control it proves; no open High or Critical finding; **no conditional pass is requested for the safety gate**
  - Verify: `ls docs/evidence/m3/gate-4/` and the signed
    [gate sign-off record](../reference/gates.md#gate-sign-off-record-template)
  - Files: milestone evidence bundle `docs/evidence/m3/gate-4/`
  - Controls: 11 Security testing, 12 Compliance evidence, 2 Authorisation, 6 Audit logging
  - Evidence: Gate 4 record, decision by the Security Lead, approved by the CTO and the Clinical Safety Officer

- [ ] **T3-38 — Gate 5 evidence bundle**
  - Acceptance: The Parchment data-flow record, the credential inventory with the rotation procedure, the sandbox test report, the webhook signature/replay/dedup output, the idempotency output, the reconciliation output and the provider-outage playbook are assembled; the vendor register entry records terms, region and sub-processor status; any item still under review is marked **REQUIRES LEGAL/REGULATORY VALIDATION** with an owner
  - Verify: `ls docs/evidence/m3/gate-5/` and the signed gate sign-off record
  - Files: milestone evidence bundle `docs/evidence/m3/gate-5/`
  - Controls: 8 Secrets management, 12 Compliance evidence, 10 Abuse protection, 7 Encryption
  - Evidence: Gate 5 record, decision by the Security Lead, approved by the CTO and the Compliance Lead

- [ ] **T3-39 — Gate 6 preparation bundle (no release)**
  - Acceptance: The security test report, the four scan reports, the environment-separation checklist for the Parchment credentials/queue/buckets, the migration expansion/contraction review and the new alert definitions are assembled; the bundle explicitly states that Gate 6 is **not** claimed and that production is **not** released; the D-004 blocker is recorded
  - Verify: `ls docs/evidence/m3/gate-6-prep/`
  - Files: milestone evidence bundle `docs/evidence/m3/gate-6-prep/`
  - Controls: 11 Security testing, 12 Compliance evidence, 7 Encryption, 9 Error handling
  - Evidence: Gate 6 preparation checklist and the recorded D-004 blocker; release decision deferred to Gate 7

---

## Sources

- `clinic-os-secure-by-design/09-prescription-safety-gate.md` §2 gate pipeline, §3 decision table, §5
  acceptance scenarios, §7 idempotency, §8 reconciliation, §9 audit, §10 no-bypass, §11 test matrix
- `clinic-os-secure-by-design/10-integration-boundaries.md` §4 controls, §5 Parchment, §7 webhooks,
  §10 integration tests
- `clinic-os-secure-by-design/27-security-testing.md` §2 catalogue, §5 access matrix, §6 test data,
  §7 negative and adversarial testing
- `clinic-os-secure-by-design/26-security-gates.md` §5–§7
- `clinic-os-secure-by-design/07-audit-architecture.md` §1, §5, §12
- `clinic-os-secure-by-design/23-sprint-plan.md` §5–§7
- [`docs/reference/build-contract.md`](../reference/build-contract.md) — the twelve controls, commands, boundaries
- [`docs/reference/definition-of-done.md`](../reference/definition-of-done.md) — the six-part test,
  endpoint declaration standard, evidence storage
- [`docs/reference/gates.md`](../reference/gates.md) — Gate 4, Gate 5, Gate 6 evidence lists
- [`spec.md`](../features/10-prescription-safety-gate/01-requirements.md), [`plan.md`](../features/10-prescription-safety-gate/01-requirements.md), [`phase.md`](../features/10-prescription-safety-gate/01-requirements.md)
