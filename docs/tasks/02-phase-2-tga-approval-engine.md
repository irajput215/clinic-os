---
doc_id: OZ-SDLC-02-TASKS
title: Phase 2 tasks — TGA approval engine
owner: Delivery Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
phase: 2 — TGA approval engine
gate: Gate 4 (APIs) · Gate 5 (Integrations — TGA boundary)
source:
  - clinic-os-secure-by-design/08-tga-approval-model.md
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/07-audit-architecture.md
  - clinic-os-secure-by-design/04-database-erd.md
  - clinic-os-secure-by-design/23-sprint-plan.md
  - clinic-os-secure-by-design/26-security-gates.md
---

> **The phase specification this list was written against has been superseded** by the numbered feature folders under [`../features/`](../features/). Requirements, design, threats, data handling, tests and the Definition of Done now live there, one folder per feature.

# Phase 2 tasks — TGA approval engine

A task starts only when [`spec.md`](../features/08-tga-approvals/01-requirements.md) is approved. Order follows [`plan.md`](../features/08-tga-approvals/01-requirements.md) §2.
`Controls` cites the numbered controls in [`README.md`](../reference/build-contract.md) §6. `Files` are the Python
artefact paths this repo uses ([`gates.md`](../reference/gates.md#artefact-naming-source-contract--this-repo)).

## S1 — Schema and constraint

- [ ] **T2-1 — Land the tenant tables for the phase**
  - Acceptance: `tga_approvals`, `tga_approval_events`, `tga_inbox_messages`, `tga_inbox_attachments`, `tga_extraction_results`, `report_runs`, `export_jobs` exist, each with `tenant_id uuid NOT NULL` and a composite `UNIQUE (tenant_id, id)` so child tables can carry a tenant-bound FK.
  - Verify: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
  - Files: `backend/app/alembic/versions/0021_tga_tables.py`, `backend/app/modules/tga_approvals/models.py`, `backend/app/modules/tga_inbox/models.py`, `backend/app/modules/reports/models.py`
  - Controls: 3 (tenant isolation), 5 (output validation)
  - Evidence: migration output on a fresh database; `\d tga_approvals` capture

- [ ] **T2-2 — RLS enabled and forced on every phase-2 table**
  - Acceptance: each table has `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, and one `AS RESTRICTIVE FOR ALL` policy with `USING` and `WITH CHECK` using `NULLIF(current_setting('app.tenant_id', true), '')::uuid`; the application role is not the owner and has no `BYPASSRLS`; a forged `tenant_id` in an insert is refused by `WITH CHECK`.
  - Verify: `uv run pytest tests/isolation/test_rls_holds_without_app_filter.py tests/isolation/test_pool_reuse.py -v`
  - Files: `backend/app/alembic/versions/0022_tga_rls.py`, `backend/app/core/db.py`
  - Controls: 3 (tenant isolation), 6 (audit logging)
  - Evidence: policy listing, grant listing, isolation and pool-reuse test output

- [ ] **T2-3 — GiST exclusion constraint on overlapping active intervals**
  - Acceptance: `CREATE EXTENSION IF NOT EXISTS btree_gist` and `no_overlapping_active_approvals EXCLUDE USING gist (tenant_id WITH =, patient_id WITH =, tga_category WITH =, dosage_form WITH =, validity_interval WITH &&) WHERE (state = 'ACTIVE')`; a second `ACTIVE` row at the same grain with an overlapping interval is refused by the database and maps to `409 DUPLICATE_APPROVAL_GRAIN`; two tenants may hold the same grain without collision; a `SUPERSEDED` historical row does not collide with its replacement.
  - Verify: `uv run pytest tests/tga/test_grain_exclusion_constraint.py tests/tga/test_same_grain_different_tenant.py -v`
  - Files: `backend/app/alembic/versions/0023_tga_exclusion.py`, `backend/app/modules/tga_approvals/models.py`
  - Controls: 3 (tenant isolation), 4 (input validation), 11 (security testing)
  - Evidence: constraint definition (`pg_get_constraintdef`), exclusion-violation test output; **Gate 2 check "the approval grain is enforced by a GiST exclusion constraint"**

- [ ] **T2-4 — Domain checks: states, window, attribution**
  - Acceptance: `state IN ('PENDING','ACTIVE','EXPIRED','REJECTED','REVOKED','SUPERSEDED')`; `valid_to > valid_from`; `valid_to <= (valid_from + interval '2 years')::date`; `state = 'ACTIVE'` implies `verified_at IS NOT NULL`; `state = 'REVOKED'` implies `revocation_reason IS NOT NULL`.
  - Verify: `uv run pytest tests/tga/test_state_machine.py -v -k check`
  - Files: `backend/app/alembic/versions/0024_tga_checks.py`
  - Controls: 4 (input validation)
  - Evidence: constraint definitions plus the check-violation test output

- [ ] **T2-5 — Append-only grants enforced by privilege, not convention**
  - Acceptance: `tga_approval_events` has `GRANT INSERT, SELECT` only; `tga_extraction_results` has `GRANT INSERT, SELECT, UPDATE (accepted_value, accepted_by, accepted_at)` and no `DELETE`; `tga_approvals` has no `DELETE`; the grant inspection test reads `information_schema.role_table_grants` after every migration and fails on a widened grant.
  - Verify: `uv run pytest tests/tga/test_approval_audit_append_only.py -v`
  - Files: `backend/app/alembic/versions/0025_tga_grants.py`, `backend/tests/tga/test_approval_audit_append_only.py`
  - Controls: 6 (audit logging), 11 (security testing)
  - Evidence: grant listing and the failed-`UPDATE`/`DELETE` test output

- [ ] **T2-6 — Indexes for the grain, the expiry sweep and ingestion**
  - Acceptance: `(tenant_id, patient_id, state)`; `(tenant_id, state, valid_to)`; unique `(tenant_id, provider_message_id)`; `(tenant_id, processing_state, received_at)`; `(tenant_id, message_id)`; `(tenant_id, sha256)`; unique `(tenant_id, attachment_id, field_name, extractor_version)`; `(tenant_id, attachment_id)`; `(tenant_id, approval_id, occurred_at)`; `(tenant_id, report_type, period_start DESC)`.
  - Verify: `uv run pytest tests/tga/test_index_plan.py -v` and `\di` capture
  - Files: `backend/app/alembic/versions/0026_tga_indexes.py`
  - Controls: 3 (tenant isolation)
  - Evidence: index listing and the match/expiry query plans

## S2 — State machine and service

- [ ] **T2-7 — Approval models and one schema per endpoint**
  - Acceptance: `tga_approvals` SQLModel with the columns in [`spec.md`](../features/08-tga-approvals/01-requirements.md) §4.1; Pydantic v2 schemas per endpoint (list query, create, read, verify, revoke, supersede, match in/out); unknown fields rejected; no route returns a raw ORM entity.
  - Verify: `uv run pytest tests/security/test_validation_rejects_unknown_field.py tests/security/test_serialisation_omits_restricted_fields.py -v && uv run mypy app`
  - Files: `backend/app/modules/tga_approvals/models.py`, `schemas.py`
  - Controls: 4 (input validation), 5 (output validation)
  - Evidence: schema listing plus validation and serialisation test output

- [ ] **T2-8 — Table-driven state machine**
  - Acceptance: only the transitions in [`spec.md`](../features/08-tga-approvals/01-requirements.md) §2.3 are permitted; a client cannot set `state`; an unlisted transition returns `409 ILLEGAL_STATE_TRANSITION` and writes a denied event; `REVOKED` and `SUPERSEDED` are terminal; each transition writes `tga_approval.state_change` with `from_state`, `to_state`, `reason`.
  - Verify: `uv run pytest tests/tga/test_state_machine.py tests/tga/test_illegal_transition_returns_409.py -v`
  - Files: `backend/app/modules/tga_approvals/service.py`
  - Controls: 2 (authorisation), 4 (input validation), 6 (audit logging)
  - Evidence: transition test output including the denied-event assertion

- [ ] **T2-9 — Supersede is atomic and leaves one current record**
  - Acceptance: the newer insert and the older `SUPERSEDED` update commit or roll back together; `superseded_by_id` points at the newer row; a chain of three resolves to exactly one non-superseded record.
  - Verify: `uv run pytest tests/tga/test_state_machine.py -v -k supersede`
  - Files: `backend/app/modules/tga_approvals/service.py`
  - Controls: 4 (input validation), 6 (audit logging)
  - Evidence: supersede atomicity and chain-resolution test output

- [ ] **T2-10 — Expiry job is idempotent and uses the database clock**
  - Acceptance: the job selects `state = 'ACTIVE' AND valid_to < CURRENT_DATE` in `Australia/Sydney`, runs at 00:15 Sydney time, moves each row to `EXPIRED`, writes one state-change event and one notification per row, and changes nothing on a second same-day run; application instances do not evaluate expiry from their own clocks.
  - Verify: `uv run pytest tests/tga/test_expiry_job_idempotent.py -v`
  - Files: `backend/app/worker/tga_expiry.py`, `backend/app/modules/tga_approvals/service.py`
  - Controls: 4 (input validation), 6 (audit logging)
  - Evidence: two-run job output showing one state change and one notification

- [ ] **T2-11 — Validity boundary in `Australia/Sydney`**
  - Acceptance: the boundary case in [`spec.md`](../features/08-tga-approvals/01-requirements.md) §2.4 is implemented and covered, and the resolved answer to the inclusive-versus-half-open question is applied consistently by the match, the expiry job and the reporting query.
  - Verify: `uv run pytest tests/tga/test_validity_boundary_is_inclusive_in_sydney.py -v`
  - Files: `backend/app/modules/tga_approvals/service.py`, `backend/tests/tga/test_validity_boundary_is_inclusive_in_sydney.py`
  - Controls: 4 (input validation), 11 (security testing)
  - Evidence: boundary test output, plus the recorded Clinical Safety Officer decision (spec §12 open item 2)

## S3 — Manual entry routes

- [ ] **T2-12 — Create, list and read approvals**
  - Acceptance: `POST /api/v1/tga-approvals` creates `PENDING` at the grain with `source = MANUAL_ENTRY` and a reason, and returns `409 DUPLICATE_APPROVAL_GRAIN` on a duplicate; `GET /api/v1/tga-approvals` is cursor-paginated with bounded `limit`; `GET /api/v1/tga-approvals/{id}` returns the supersede chain; no `tenant_id`, `actor_id` or `role` is accepted from the request.
  - Verify: `uv run pytest tests/tga/test_manual_entry_routes.py -v`
  - Files: `backend/app/modules/tga_approvals/router.py`, `service.py`, `schemas.py`
  - Controls: 2 (authorisation), 4 (input validation), 10 (abuse protection)
  - Evidence: route test output plus the endpoint declaration inventory entries

- [ ] **T2-13 — Verify route: separate permission, application number required, step-up**
  - Acceptance: `POST /api/v1/tga-approvals/{id}/verify` requires `tga_approval:verify` and step-up; `PENDING → ACTIVE` without `tga_application_number` returns `422`; the decision and the verifier are written in one transaction with the state change; a rejection moves to `REJECTED` with a reason.
  - Verify: `uv run pytest tests/tga/test_verify_requires_application_number.py tests/tga/test_manual_entry_routes.py -v -k verify`
  - Files: `backend/app/modules/tga_approvals/router.py`, `service.py`
  - Controls: 1 (authentication), 2 (authorisation), 6 (audit logging)
  - Evidence: test output; step-up is evidenced when D-003 closes (see T2-14)

- [ ] **T2-14 — Revoke route: permission, mandatory reason, step-up**
  - Acceptance: `POST /api/v1/tga-approvals/{id}/revoke` requires `tga_approval:revoke` and step-up; a missing reason is `422`; `revoked_by` and `revoked_at` are set; a revoked record can authorise nothing.
  - Verify: `uv run pytest tests/tga/test_manual_entry_routes.py -v -k revoke`
  - Files: `backend/app/modules/tga_approvals/router.py`, `service.py`
  - Controls: 1 (authentication), 2 (authorisation), 6 (audit logging)
  - Evidence: test output; step-up mechanism tracked under D-003

- [ ] **T2-15 — Separation of duties: `VERIFIER_CANNOT_BE_CREATOR`**
  - Acceptance: an actor who created or entered a record receives `403 VERIFIER_CANNOT_BE_CREATOR` on verify for that record; a different actor with `tga_approval:verify` succeeds; the denial is audited with `result = DENIED`.
  - Verify: `uv run pytest tests/tga/test_separation_of_duties.py -v`
  - Files: `backend/app/modules/tga_approvals/service.py`, `backend/app/core/security.py`
  - Controls: 2 (authorisation), 6 (audit logging)
  - Evidence: test output including the denial event

- [ ] **T2-16 — Cross-cutting API contract: envelope, pagination, idempotency, rate limits**
  - Acceptance: every write accepts an `Idempotency-Key` stored with tenant and route under a unique constraint and returns the original result on retry; every list is cursor-based with an opaque signed cursor; every error uses the single envelope with `request_id`; rate limits return `429` with `Retry-After` and are logged; no response leaks a stack trace.
  - Verify: `uv run pytest tests/security/test_errors_never_leak_internal_detail.py tests/security/test_errors_fail_closed.py -v`
  - Files: `backend/app/core/security.py`, `backend/app/modules/tga_approvals/router.py`
  - Controls: 9 (error handling), 10 (abuse protection)
  - Evidence: error-envelope, idempotency and rate-limit test output

## S4 — Ingestion

- [ ] **T2-17 — Inbox intake route and mailbox-to-tenant mapping**
  - Acceptance: `POST /api/v1/tga-inbox/intake` is the only unauthenticated surface; the tenant is resolved from the mailbox mapping and never from the request; the same `provider_message_id` is deduplicated and no duplicate document or approval is created; SPF, DKIM and DMARC results are recorded and never trusted alone; an unmapped mailbox is refused.
  - Verify: `uv run pytest tests/inbox/test_intake_dedup.py -v`
  - Files: `backend/app/modules/tga_inbox/router.py`, `service.py`, `models.py`
  - Controls: 3 (tenant isolation), 4 (input validation), 6 (audit logging)
  - Evidence: intake and dedup test output; data-flow record for V-04

- [ ] **T2-18 — Attachment validation as untrusted input**
  - Acceptance: extension allow-list (`.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.docx` where contracted); double extensions rejected; declared MIME must be in the allow-list and consistent with the extension; magic bytes must match the declared format; 25 MB per file, 10 files per message, larger bulk request cap; a mismatch quarantines the file and it is never parsed; a matching file is never reachable before `scan_state = 'CLEAN'`.
  - Verify: `uv run pytest tests/inbox/test_upload_validation.py -v`
  - Files: `backend/app/modules/tga_inbox/validation.py`
  - Controls: 4 (input validation), 11 (security testing)
  - Evidence: validation test output including the quarantined cases

- [ ] **T2-19 — Malware scan and quarantine boundary**
  - Acceptance: every file is scanned before it becomes reachable from the clinical record; a positive verdict moves the file to the quarantine bucket behind a separate IAM boundary, notifies the Clinical Safety Officer, stops the pipeline and raises an incident; the verdict and engine version are stored.
  - Verify: `uv run pytest tests/inbox/test_malware_quarantine.py -v`
  - Files: `backend/app/modules/tga_inbox/scanning.py`, `backend/app/core/config.py`
  - Controls: 7 (encryption), 8 (secrets management), 11 (security testing)
  - Evidence: quarantine test output; engine/credential configuration review

- [ ] **T2-20 — Private object storage with hash, versioning and short-lived access**
  - Acceptance: object key generated server-side as `documents/{tenant_id}/{document_id}/v{n}/{sanitised_filename}`; the original filename is stored in the database and sanitised for display only; SSE-KMS; versioning on; content hash recorded at ingest and verified on retrieval; presigned URL with 5-minute expiry, generated per request after an authorisation check, served as `application/octet-stream` with `X-Content-Type-Options: nosniff`; bucket policy denies any principal outside the application and pipeline roles.
  - Verify: `uv run pytest tests/inbox/test_presigned_url_expiry.py tests/inbox/test_object_key_is_server_generated.py -v`
  - Files: `backend/app/modules/documents/service.py`, `backend/app/modules/tga_inbox/service.py`
  - Controls: 7 (encryption), 8 (secrets management), 5 (output validation)
  - Evidence: storage configuration export, key-generation test output, presigned-URL expiry test output

- [ ] **T2-21 — Failure handling routes every document to a terminal, findable state**
  - Acceptance: encrypted, password-protected, unreadable, oversized, macro-bearing, multi-approval and no-text-layer documents each follow the failure behaviour in [`spec.md`](../features/08-tga-approvals/01-requirements.md) §6 and write an audit and a pipeline stage event; a multi-approval letter splits into one review item per candidate grain; silent skipping is impossible.
  - Verify: `uv run pytest tests/inbox/test_failure_routing.py -v`
  - Files: `backend/app/modules/tga_inbox/service.py`, `backend/app/worker/`
  - Controls: 4 (input validation), 6 (audit logging), 9 (error handling)
  - Evidence: per-failure test output

## S5 — OCR and extraction

- [ ] **T2-22 — Text layer first, isolated OCR fallback**
  - Acceptance: text-layer extraction is attempted first; OCR runs only where no text layer exists, in a worker with no network egress and a memory and wall-clock cap; encrypted and password-protected files are not cracked; a parser timeout routes to manual review with the reason.
  - Verify: `uv run pytest tests/inbox/test_extraction_fallback.py -v`
  - Files: `backend/app/modules/tga_inbox/extraction.py`, `backend/app/worker/extract.py`
  - Controls: 4 (input validation), 11 (security testing)
  - Evidence: fallback test output; worker egress and isolation configuration review

- [ ] **T2-23 — Per-field values with page and region provenance**
  - Acceptance: every extracted field stores `method`, `extractor_version`, `page_number`, `region`, `raw_value` and a per-field `confidence`; a field that cannot be extracted is `NOT_FOUND` and never guessed; an ambiguous digit in the application number lowers that field's confidence; nothing is stored only in memory.
  - Verify: `uv run pytest tests/inbox/test_extraction_provenance.py -v`
  - Files: `backend/app/modules/tga_inbox/extraction.py`, `models.py`
  - Controls: 4 (input validation), 5 (output validation), 6 (audit logging)
  - Evidence: provenance test output; a sampled document reconstructable field-by-field

- [ ] **T2-24 — Pattern-plus-pass extraction of the application number**
  - Acceptance: extraction runs a configured pattern set **and** a model pass; never a single method; every candidate carries a per-field confidence; no candidate above the floor routes to manual review.
  - Verify: `uv run pytest tests/inbox/test_application_number_extraction.py -v`
  - Files: `backend/app/modules/tga_inbox/extraction.py`
  - Controls: 4 (input validation), 11 (security testing)
  - Evidence: extraction test output naming the producing method per candidate

- [ ] **T2-25 — Per-layout parser registry**
  - Acceptance: a document layout maps to a parser through a registry entry; an unrecognised layout routes to manual review with the reason rather than failing silently; a layout change is a registry plus golden-set change, not a code fork.
  - Verify: `uv run pytest tests/inbox/test_parser_registry.py -v`
  - Files: `backend/app/modules/tga_inbox/parsers/__init__.py`, `backend/app/modules/tga_inbox/parsers/registry.py`
  - Controls: 4 (input validation)
  - Evidence: registry test output; the registry listing

## S6 — Matching

- [ ] **T2-26 — Patient matching: candidates only, no merge, no cross-tenant key**
  - Acceptance: deterministic matching on strong identifiers first, then configured fuzzy fields; a candidate requires at least two independent identifiers agreeing, one of which is date of birth or a national identifier; the query runs under RLS with tenant context set; a name alone, a partial date of birth alone, a postcode alone and an approval number as patient key are never used; no auto-merge path exists; two candidates within 0.05 present both and require an explicit choice; an unknown patient routes to the manual-resolution queue.
  - Verify: `uv run pytest tests/inbox/test_patient_matching.py tests/inbox/test_matching_never_crosses_tenant_boundaries.py -v`
  - Files: `backend/app/modules/tga_inbox/matching.py`
  - Controls: 3 (tenant isolation), 4 (input validation), 2 (authorisation)
  - Evidence: matching test output including the canary-tenant absence assertion

- [ ] **T2-27 — The point-in-time match service**
  - Acceptance: the service returns `matched`, `reason_code`, `state`, `approval_id`, `validity_interval`, `date_of_service` and `evaluated_timezone = "Australia/Sydney"`; it evaluates at the supplied service date and never at `now()`; it fails closed on a missing tenant context or a lookup error; it writes no clinical state and calls no provider.
  - Verify: `uv run pytest tests/tga/test_point_in_time_match_service.py -v`
  - Files: `backend/app/modules/tga_approvals/service.py`
  - Controls: 2 (authorisation), 3 (tenant isolation), 6 (audit logging)
  - Evidence: service contract test output

- [ ] **T2-28 — The five point-in-time match cases and the negative matrix**
  - Acceptance: the five cases M1–M5 in [`spec.md`](../features/08-tga-approvals/01-requirements.md) §3.2 return exactly the specified results; additionally `APPROVAL_EXPIRED`, `APPROVAL_REVOKED`, `APPROVAL_PENDING_VERIFICATION`, `APPROVAL_REJECTED`, `APPROVAL_SUPERSEDED` and `NO_ACTIVE_TGA_APPROVAL_FOR_CATEGORY_AND_DOSAGE_FORM` are each produced by their own fixture; every block writes `TGA_APPROVAL_MATCH_FAILED` and a pass writes `TGA_APPROVAL_MATCHED`; a cross-tenant attempt returns not-matched and discloses no existence.
  - Verify: `uv run pytest tests/tga/test_point_in_time_match.py -v`
  - Files: `backend/tests/tga/test_point_in_time_match.py`, `backend/tests/tga/fixtures.py`
  - Controls: 11 (security testing), 3 (tenant isolation), 6 (audit logging)
  - Evidence: **negative match matrix** — Gate 4 evidence

- [ ] **T2-29 — Match route with no PHI in the URL**
  - Acceptance: `POST /api/v1/tga-approvals/match` carries `patient_id`, `category`, `dosage_form` and `as_at` in the **body**, never a query string; the tenant comes from the session; a non-match is `200` with `matched = false`, not an error; the route lint `lint.no_phi_in_url` passes.
  - Verify: `uv run pytest tests/tga/test_match_route.py tests/security/test_no_phi_in_url.py -v`
  - Files: `backend/app/modules/tga_approvals/router.py`, `schemas.py`
  - Controls: 4 (input validation), 5 (output validation), 10 (abuse protection)
  - Evidence: route test output; the deliberate divergence from the source's `GET ...?patient_id=` recorded in [`spec.md`](../features/08-tga-approvals/01-requirements.md) §5

## S7 — Confidence scoring

- [ ] **T2-30 — Composite score and the four policy values**
  - Acceptance: the composite is a weighted combination of per-field extraction confidence and match confidence; `tga_inbox_confidence_threshold`, `tga_inbox_auto_create_threshold`, `tga_inbox_field_floor` and `tga_inbox_match_threshold` are read from configuration, writable only with `tenant:configure` and step-up, and every change is audited; the defaults are the conservative recommendations and `tga_inbox_auto_create_threshold` is disabled by default; the values carry recorded Clinical Safety Officer sign-off.
  - Verify: `uv run pytest tests/inbox/test_confidence_scoring.py -v`
  - Files: `backend/app/modules/tga_inbox/confidence.py`, `backend/app/core/config.py`
  - Controls: 2 (authorisation), 4 (input validation), 6 (audit logging), 12 (compliance evidence)
  - Evidence: scoring test output plus the Clinical Safety Officer sign-off record for the threshold set

- [ ] **T2-31 — Low-confidence routing names the failing field**
  - Acceptance: below the composite threshold, or below the per-field floor on any mandatory field, the record stays `PENDING` and enters the human queue with the failing field named; a low-confidence critical field cannot be auto-verified by any route; `TGA_EXTRACTION_LOW_CONFIDENCE` is written.
  - Verify: `uv run pytest tests/inbox/test_low_confidence_routing.py -v`
  - Files: `backend/app/modules/tga_inbox/confidence.py`, `service.py`
  - Controls: 4 (input validation), 6 (audit logging)
  - Evidence: routing test output naming the field and the event

## S8 — Human verification

- [ ] **T2-32 — Verification queue API with a lease**
  - Acceptance: the queue is ordered by arrival time, oldest first; claiming takes a lease and a second concurrent claim returns `409`; the decisions are accept, correct, reject and defer; correct and reject require a reason; a reviewer cannot verify a patient they may not access under the care-relationship rule; an item older than 4 hours raises an alert.
  - Verify: `uv run pytest tests/inbox/test_verification_queue.py -v`
  - Files: `backend/app/modules/tga_inbox/router.py`, `service.py`
  - Controls: 2 (authorisation), 6 (audit logging), 10 (abuse protection)
  - Evidence: queue test output including the lease conflict

- [ ] **T2-33 — No automated path to `ACTIVE`**
  - Acceptance: no code path moves `PENDING → ACTIVE` without a recorded human decision; the pipeline and the workers hold no `UPDATE` on `tga_approvals.state`; the safety-gate interface is unreachable from the pipeline; the test enumerates every writer of `state`.
  - Verify: `uv run pytest tests/tga/test_no_automated_path_to_active.py -v`
  - Files: `backend/app/modules/tga_inbox/service.py`, `backend/app/worker/`, `backend/app/modules/tga_approvals/service.py`
  - Controls: 2 (authorisation), 6 (audit logging), 11 (security testing)
  - Evidence: **Gate 5 check "TGA ingestion cannot write a gating state without a human verification"**

- [ ] **T2-34 — Verification UI presents evidence, not a default**
  - Acceptance: the document renders beside the extracted fields with the source page reachable in one action; per-field confidence and producing method are shown; candidate matches show the agreeing identifiers, score and reason; no candidate is pre-selected; the machine proposal is visible and requires explicit selection.
  - Verify: `bun run test` in `frontend-features/` with the verification-queue spec, plus a usability check recorded by the Clinical Safety Officer
  - Files: `frontend-features/src/routes/tga-inbox/`, `frontend-features/tests/`
  - Controls: 2 (authorisation), 5 (output validation)
  - Evidence: Playwright run record and the usability note

- [ ] **T2-35 — Filing reversal is a designed, audited procedure**
  - Acceptance: a misfiled approval is reversed through an explicit permissioned action; `TGA_FILING_REVERSED` is written with the actor and the reason; the original extraction record is left intact; a reversal cannot be used to reach `ACTIVE` for a different patient or grain.
  - Verify: `uv run pytest tests/inbox/test_filing_reversal.py -v`
  - Files: `backend/app/modules/tga_inbox/service.py`, `router.py`
  - Controls: 2 (authorisation), 6 (audit logging)
  - Evidence: reversal test output and the event sample

## S9 — Reporting

- [ ] **T2-36 — Six-monthly report runs from stored data**
  - Acceptance: `POST /api/v1/reports/six-monthly/run` produces the report in one action from stored `tga_approvals` and `prescriptions`; output is aggregate and contains no patient-identifying row; the run is tenant-scoped; `REPORT_RUN` is written with the period, the prescriber and the approval identifiers; a submitted report is immutable and a correction is a new version referencing it.
  - Verify: `uv run pytest tests/reports/test_six_monthly_run.py -v`
  - Files: `backend/app/modules/reports/service.py`, `router.py`, `models.py`
  - Controls: 3 (tenant isolation), 5 (output validation), 6 (audit logging)
  - Evidence: report run output and the `REPORT_RUN` event sample

- [ ] **T2-37 — Every figure reconciles to the register**
  - Acceptance: the report's approval count and per-category counts equal the register counts for the same period and tenant; the reconciliation is asserted, not asserted-by-eye; the demo's manual on-screen reconciliation uses the same query.
  - Verify: `uv run pytest tests/reports/test_six_monthly_reconciles_to_register.py -v`
  - Files: `backend/app/modules/reports/service.py`, `backend/tests/reports/test_six_monthly_reconciles_to_register.py`
  - Controls: 12 (compliance evidence), 5 (output validation)
  - Evidence: reconciliation test output — the demo evidence for step 5

- [ ] **T2-38 — Report fields, cadence and format marked for validation**
  - Acceptance: every field, the cadence and the submission format are marked **REQUIRES LEGAL/REGULATORY VALIDATION** in the code and documentation, with a named owner; no form number, deadline or fee is invented; a missed period is a dashboard signal and **not** a prescribing block; the unsupported "January and July" claim is removed from the feature ledger or re-marked.
  - Verify: `grep -rn "REQUIRES LEGAL/REGULATORY VALIDATION" backend/app/modules/reports docs/`
  - Files: `backend/app/modules/reports/service.py`, `docs/features/08-tga-approvals/05-data-and-audit.md`
  - Controls: 12 (compliance evidence)
  - Evidence: the grep output plus the open-questions entry with owner TGA Compliance Lead

- [ ] **T2-39 — Export path with step-up and a stated reason**
  - Acceptance: `POST /api/v1/exports` requires `export:aggregate` or, for patient-level data, `export:bulk` plus step-up and a stated reason; a bulk export without step-up is refused; the artefact is watermarked and expires on schedule; `EXPORT_REQUESTED`, `EXPORT_COMPLETED`, `EXPORT_DOWNLOADED` and `EXPORT_EXPIRED` are written.
  - Verify: `uv run pytest tests/reports/test_export_requires_step_up.py -v`
  - Files: `backend/app/modules/reports/router.py`, `service.py`
  - Controls: 1 (authentication), 2 (authorisation), 6 (audit logging), 7 (encryption)
  - Evidence: refusal test output and the export event samples

## S10 — Audit and observability

- [ ] **T2-40 — The TGA event catalogue, written in the same transaction**
  - Acceptance: every event in [`spec.md`](../features/08-tga-approvals/01-requirements.md) §8 is emitted; each uses the fixed envelope from `07-audit-architecture.md` §2; each is written in the same transaction as the change; a failed audit write fails the operation; denied and failed attempts are audited; `TGA_INBOX_REPROCESSED` is registered in the `07-audit-architecture.md` §1 table before use; no payload contains clinical content, a patient name, a document body or a secret.
  - Verify: `uv run pytest tests/security/test_audit_writes_in_same_transaction.py tests/tga/test_audit_event_catalogue.py -v`
  - Files: `backend/app/core/audit.py`, `backend/app/modules/tga_approvals/service.py`, `backend/app/modules/tga_inbox/service.py`
  - Controls: 6 (audit logging), 5 (output validation)
  - Evidence: same-transaction test output, a sample event with the full envelope, and the audit coverage matrix

- [ ] **T2-41 — No PHI in logs, metrics, traces or error responses**
  - Acceptance: a sentinel value seeded into a patient field, a document body, an attachment filename, a mail subject and OCR text never appears in a log, a metric label, a trace or an error body; reasons are captured in the audit store and excluded from application logs.
  - Verify: `uv run pytest tests/security/test_no_phi_in_log_payload.py -v`
  - Files: `backend/app/core/logging.py`, `backend/app/modules/tga_inbox/`
  - Controls: 5 (output validation), 9 (error handling)
  - Evidence: sentinel test output and the redaction unit test output

- [ ] **T2-42 — The two-minute target is measured, not claimed**
  - Acceptance: `tga_inbox_end_to_end_seconds` records per-document latency with the pipeline stage as a label, excluding reviewer think time; `tga_inbox_review_wait_seconds` is tracked separately; a p95 alert fires above 120 s; the median is measured in Staging against synthetic letters only and reported at the sprint review.
  - Verify: Staging metric read for `tga_inbox_end_to_end_seconds` and `tga_inbox_review_wait_seconds`; alert definition review
  - Files: `backend/app/modules/tga_inbox/service.py`, `backend/app/core/metrics.py`
  - Controls: 12 (compliance evidence)
  - Evidence: median and p95 measurement for Staging — the exit criterion in [`phase.md`](../features/08-tga-approvals/01-requirements.md) §10

- [ ] **T2-43 — Import-boundary lint between modules**
  - Acceptance: no module imports another module's `models` or internals; cross-module calls go through `service.py` facades; the lint fails the build on a violation.
  - Verify: `uv run ruff check . && uv run pytest tests/test_import_boundaries.py -v`
  - Files: `backend/pyproject.toml`, `backend/tests/test_import_boundaries.py`
  - Controls: 12 (compliance evidence)
  - Evidence: lint output and the boundary test

- [ ] **T2-44 — Fix the golden set as a tuning artefact**
  - Acceptance: a manifest of synthetic approval letters with labelled ground truth per field and per-field page and region exists under version control; no real patient letter is used; a tuning run reports per-field precision and recall and the human-verification rate; a threshold or parser change cites the golden-set run that justifies it; `tga_inbox_auto_create_threshold` stays disabled while the set is small.
  - Verify: `uv run pytest tests/inbox/test_golden_set_manifest.py -v`
  - Files: `backend/tests/fixtures/tga/golden_set/`, `docs/features/08-tga-approvals/06-test-plan.md`
  - Controls: 12 (compliance evidence), 11 (security testing)
  - Evidence: golden-set tuning log and the Clinical Safety Officer's ownership record

## Gate evidence

- [ ] **T2-45 — Assemble the Gate 4 evidence bundle**
  - Acceptance: the endpoint declaration inventory has no blank declaration; the five security-test categories have been run and reported; the negative match matrix is attached; the separation-of-duties and no-automated-path-to-`ACTIVE` results are attached; the audit grant listing is attached; the CI pipeline run is green on the evidence commit.
  - Verify: `uv run pytest tests/security tests/isolation tests/tga -v` plus the CI run record
  - Files: `docs/reference/gates.md`, milestone evidence bundle `M2/`
  - Controls: 2 (authorisation), 11 (security testing), 12 (compliance evidence)
  - Evidence: Gate 4 sign-off record; **no conditional pass for the safety gate**

- [ ] **T2-46 — Assemble the Gate 5 (TGA boundary) evidence bundle**
  - Acceptance: data-flow records exist for V-04, V-07 and V-08; the credential inventory names an owner and a rotation procedure per environment; the sandbox end-to-end test passed with synthetic letters; the outage playbook names an owner and the manual-entry clinical fallback; the vendor register entries carry the current terms status; the human-verification check is evidenced by T2-33.
  - Verify: `uv run pytest tests/inbox tests/tga -v` plus the Staging run record
  - Files: `docs/reference/gates.md`, milestone evidence bundle `M2/`
  - Controls: 8 (secrets management), 12 (compliance evidence), 11 (security testing)
  - Evidence: Gate 5 sign-off record; conditional pass only for a vendor position marked **REQUIRES LEGAL/REGULATORY VALIDATION**, with an expiry and no production enablement

## Sources

- `clinic-os-secure-by-design/08-tga-approval-model.md` §3–§5, §8 — transitions, expiry job, tests
- `clinic-os-secure-by-design/11-tga-inbox-pipeline.md` §1–§12 — pipeline, thresholds, provenance, verification, two-minute target
- `clinic-os-secure-by-design/09-prescription-safety-gate.md` §3 — the lookup decision table the match matrix reproduces
- `clinic-os-secure-by-design/07-audit-architecture.md` §1, §2, §5 — event catalogue, envelope, transactional write
- `clinic-os-secure-by-design/04-database-erd.md` §3.6–§3.9, §8, §9 — tables, RLS pattern, append-only grants
- `clinic-os-secure-by-design/23-sprint-plan.md` §4 — workstreams, exit criteria, risks
- `clinic-os-secure-by-design/26-security-gates.md` §5, §6 — Gate 4 and Gate 5 checks
- [`gates.md`](../reference/gates.md) — artefact naming map and gate evidence lists
- [`definition-of-done.md`](../reference/definition-of-done.md) — the six-part test
- [`README.md`](../reference/build-contract.md) §6 — the twelve controls cited above
