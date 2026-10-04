---
doc_id: OZ-SDLC-01-TASKS
title: Phase 1 — Foundations task list
owner: Delivery Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
phase: 1
gate: Gate 1 Architecture · Gate 2 Database · Gate 3 Authentication
source:
  - ../../clinic-os-secure-by-design/23-sprint-plan.md
  - ../../clinic-os-secure-by-design/05-tenant-isolation.md
  - ../../clinic-os-secure-by-design/07-audit-architecture.md
  - ../../clinic-os-secure-by-design/06-authentication-rbac.md
  - ../../clinic-os-secure-by-design/27-security-testing.md
---

> **The phase specification this list was written against has been superseded** by the numbered feature folders under [`../features/`](../features/). Requirements, design, threats, data handling, tests and the Definition of Done now live there, one folder per feature.

# Phase 1 — Foundations task list

Tasks are grouped by workstream and ordered by dependency. A task is **one session and at most ~5
files**. No task starts until [spec.md](../features/README.md) is approved. Commands run from `backend/` per
[`docs/reference/build-contract.md`](../reference/build-contract.md) §8.

**Control numbers** used in the `Controls:` field are the twelve controls of
[`docs/reference/build-contract.md`](../reference/build-contract.md) §6: **1** Authentication · **2** Authorisation · **3** Tenant
isolation · **4** Input validation · **5** Output validation · **6** Audit logging · **7** Encryption ·
**8** Secrets management · **9** Error handling · **10** Abuse protection · **11** Security testing ·
**12** Compliance evidence.

**Blocked-by values:** `D-003`, `D-004`, `O3`, `permission-catalogue`, `care-relationships`,
`lockout-threshold`, or `none`.

**Test file naming.** [`gates.md`](../reference/gates.md) names two isolation artefacts exactly —
`backend/tests/isolation/test_pool_reuse.py` and
`backend/tests/isolation/test_rls_holds_without_app_filter.py`. The remaining isolation test file names
below are derived by the same rule from the test ids in `05-tenant-isolation.md` §8 (`rls.no_context_returns_zero_rows`
→ `test_rls_no_context_returns_zero_rows.py`, and so on). The id in parentheses is the authoritative
reference; the file name is the repo-side artefact.

---

## Workstream A — Data plane

- [ ] **T1-01 — Migration: `tenants` and `clinics` with RLS, indexes and grants in one file**
  - Acceptance: `tenants` is global with column-level grants (no `retention_profile` read, no write); `clinics` is tenant-scoped with `tenant_id NOT NULL`, `FORCE ROW LEVEL SECURITY`, and `pol_clinics_tenant_isolation` with `USING` and `WITH CHECK`.
  - Verify: `uv run alembic upgrade head` then `uv run pytest tests/isolation/test_every_tenant_table_has_policy.py -v`
  - Files: `backend/app/alembic/versions/<rev>_tenants_clinics.py`; `backend/app/modules/identity_tenancy/models.py`
  - Controls: 3 Tenant isolation · 7 Encryption (at-rest via RDS) · 12 Compliance evidence
  - Evidence: migration revision id; `pg_policies` listing for `clinics`
  - Blocked by: none

- [ ] **T1-02 — Migration: `roles`, `permissions`, `role_permissions`, `user_roles` with RLS and grants**
  - Acceptance: `permissions` is global and read-only to the application role; the four tables carry the keys, indexes and constraints in [spec.md](../features/README.md) §2.2.
  - Verify: `uv run alembic upgrade head` then `uv run pytest tests/isolation/test_every_tenant_table_has_policy.py -v`
  - Files: `backend/app/alembic/versions/<rev>_users_roles.py`; `backend/app/modules/users_roles/models.py`
  - Controls: 3 Tenant isolation · 12 Compliance evidence
  - Evidence: migration revision id; policy listing
  - Blocked by: none

- [ ] **T1-03 — Migration: `users` (shape depends on D-003)**
  - Acceptance: **Option A** — `04-database-erd.md` §3.2 shape, `subject_id` and no credential column. **Option B** — the same plus a password verifier column (Argon2id, never exported), MFA enrolment state and lockout counters, per `docs/features/01-tenancy-and-clinics/05-data-and-audit.md`.
  - Verify: `uv run alembic upgrade head`; the chosen shape recorded against the D-003 decision record
  - Files: `backend/app/alembic/versions/<rev>_users.py`; `backend/app/modules/users_roles/models.py`
  - Controls: 1 Authentication · 3 Tenant isolation · 7 Encryption · 8 Secrets management
  - Evidence: migration revision id; the D-003 record showing `Accepted`
  - Blocked by: **D-003** — do not start; the column shape is not decidable

- [ ] **T1-04 — Migration: `refresh_tokens` and `integration_credentials_refs`**
  - Acceptance: `refresh_tokens` carries the `04` §3.11 column set with `family_id`, `token_hash` unique, `revoked_reason` from the closed set, and the `06` §3 idle/absolute timeout columns; `integration_credentials_refs` stores only a Secrets Manager ARN and never credential material.
  - Verify: `uv run alembic upgrade head`; a schema assertion test that no column in `integration_credentials_refs` holds a secret value
  - Files: `backend/app/alembic/versions/<rev>_sessions_credentials.py`; `backend/app/modules/identity_tenancy/models.py`
  - Controls: 1 Authentication · 3 Tenant isolation · 7 Encryption · 8 Secrets management
  - Evidence: migration revision id; the secrets-column assertion output
  - Blocked by: **D-003** — the revocation and family-semantics design is not decidable

- [ ] **T1-05 — Migration: `patients`, `patient_identifiers`, `consent_records`**
  - Acceptance: `tenant_id NOT NULL` and forced RLS on all three; composite tenant-bound FK from each child to `patients`; `patients` grants `SELECT, INSERT, UPDATE` with **no DELETE**; `consent_records` grants column-level UPDATE on `withdrawn_at`, `withdrawn_reason` with **no DELETE**; the blind-index indexes exist.
  - Verify: `uv run alembic upgrade head` then `uv run pytest tests/isolation/test_every_tenant_table_has_policy.py -v`
  - Files: `backend/app/alembic/versions/<rev>_patients.py`; `backend/app/modules/patients/models.py`
  - Controls: 3 Tenant isolation · 7 Encryption · 12 Compliance evidence
  - Evidence: migration revision id; grant listing; the `patients` vs `patient_identifiers` divergence recorded as an open decision
  - Blocked by: none (the `patient_identifiers` divergence is recorded in [spec.md](../features/README.md) §2.3, not silently resolved)

- [ ] **T1-06 — Migration: `clinical_records` and `clinical_record_versions` (append-only)**
  - Acceptance: both tables are tenant-scoped with forced RLS; `clinical_record_versions` grants `SELECT, INSERT` only — no UPDATE, no DELETE; `UNIQUE (tenant_id, clinical_record_id, version)`; `author_id` is `NOT NULL` on both.
  - Verify: `uv run alembic upgrade head` then `uv run pytest tests/security/test_grant_inspection.py -v`
  - Files: `backend/app/alembic/versions/<rev>_clinical_records.py`; `backend/app/modules/clinical_records/models.py`
  - Controls: 3 Tenant isolation · 6 Audit logging · 12 Compliance evidence
  - Evidence: migration revision id; grant listing for `clinical_record_versions`
  - Blocked by: none

- [ ] **T1-07 — Migration: `audit_log`, monthly partitions, indexes and append-only grants**
  - Acceptance: PK `(event_id, timestamp)`; monthly range partitions on `timestamp` plus an alerting default partition; `tenant_id` nullable; the four tenant-leading indexes exist; `clinos_app` has exactly `SELECT, INSERT`; no UPDATE or DELETE policy exists.
  - Verify: `uv run alembic upgrade head` then `uv run pytest tests/security/test_grant_inspection.py tests/security/test_audit_app_role_cannot_update_or_delete.py -v`
  - Files: `backend/app/alembic/versions/<rev>_audit_log.py`; `backend/app/modules/audit/models.py`
  - Controls: 3 Tenant isolation · 6 Audit logging · 12 Compliance evidence
  - Evidence: migration revision id; the `information_schema.role_table_grants` listing for `audit_log`
  - Blocked by: none

- [ ] **T1-08 — Migration: `documents` table**
  - Acceptance: tenant-scoped with forced RLS; `UNIQUE (tenant_id, object_key)`; `object_key` follows `tenants/{tenant_id}/patients/{patient_id}/{uuid}`; `scan_state` from the closed set; soft delete only.
  - Verify: `uv run alembic upgrade head` then `uv run pytest tests/isolation/test_every_tenant_table_has_policy.py -v`
  - Files: `backend/app/alembic/versions/<rev>_documents.py`; `backend/app/modules/documents/models.py`
  - Controls: 3 Tenant isolation · 7 Encryption
  - Evidence: migration revision id; policy listing
  - Blocked by: none

- [ ] **T1-09 — Seed the `permissions` catalogue and the seven system roles**
  - Acceptance: `permissions` is seeded from a versioned migration with `06-authentication-rbac.md`'s 19 codes; each of the seven role bundles resolves to its permission set per the `06` §9 matrix with every cell an explicit grant or denial; each code added beyond `06`'s 19 is recorded as a named deviation.
  - Verify: `uv run alembic upgrade head` then a seed assertion test that the row count and each role's resolved permission set match the declared matrix
  - Files: `backend/app/alembic/versions/<rev>_seed_permissions_roles.py`
  - Controls: 2 Authorisation · 12 Compliance evidence
  - Evidence: seed migration; the deviation list of added permission codes
  - Blocked by: **permission-catalogue** (the seed content is provisional until the catalogue is reconciled)

- [ ] **T1-10 — Column classification for every Phase 1 table**
  - Acceptance: every column in every table above carries exactly one level from `12-data-classification.md` §1, as a machine-readable schema annotation, and the coverage check fails when one is missing.
  - Verify: `uv run pytest tests/architecture/test_column_classification.py -v`
  - Files: `backend/app/core/classification.py`; `backend/tests/architecture/test_column_classification.py`
  - Controls: 6 Audit logging · 7 Encryption · 12 Compliance evidence
  - Evidence: classification coverage check output
  - Blocked by: none

## Workstream B — Database roles, grants and tenant context

- [ ] **T1-11 — Migration: the five database roles and their grants**
  - Acceptance: `clinos_migrator` owns the schema; `clinos_app` is a dedicated non-owner with no `BYPASSRLS`, `SELECT/INSERT/UPDATE` on tenant tables limited by `04` §6, `SELECT/INSERT` on append-only tables, and no `clinos_app` `DELETE` where retention applies; `clinos_readonly_audit`, `clinos_extractor` and `clinos_retention` exist with the grants in `05` §4. Credentials are never in the migration; the role is created `PASSWORD NULL`.
  - Verify: `uv run alembic upgrade head` then `uv run pytest tests/isolation/test_app_role_is_not_owner.py -v`
  - Files: `backend/app/alembic/versions/<rev>_database_roles.py`
  - Controls: 3 Tenant isolation · 8 Secrets management · 1 Authentication
  - Evidence: role and grant listing (`pg_roles`, `information_schema.role_table_grants`)
  - Blocked by: none

- [ ] **T1-12 — Tenant-scoped transaction helper using `SET LOCAL`**
  - Acceptance: the only way to obtain a tenant-scoped session; sets `app.tenant_id`, `app.actor_id` and `app.request_id` with `SET LOCAL` inside an explicit transaction; **refuses to open a transaction without a tenant** and raises rather than defaulting; no session-level `SET app.*` exists anywhere in the tree.
  - Verify: `uv run pytest tests/isolation/test_rls_no_context_returns_zero_rows.py tests/architecture/test_no_session_level_set.py -v`
  - Files: `backend/app/core/db.py`; `backend/tests/architecture/test_no_session_level_set.py`
  - Controls: 3 Tenant isolation · 9 Error handling
  - Evidence: the helper's unit test output; the lint result for session-level `SET`
  - Blocked by: none

- [ ] **T1-13 — Schema lint: every tenant table has a forced policy**
  - Acceptance: reads `pg_class` and `pg_policies`; fails when a table with a `tenant_id` column has no policy or no `FORCE`, and when a table without `tenant_id` is not on the global allow-list (`tenants`, `permissions`, `schema_migrations`).
  - Verify: `uv run pytest tests/isolation/test_every_tenant_table_has_policy.py -v` (I-019), plus a deliberately policy-less fixture table that must fail it
  - Files: `backend/tests/isolation/test_every_tenant_table_has_policy.py`
  - Controls: 3 Tenant isolation · 11 Security testing
  - Evidence: lint output; the negative-fixture failure output
  - Blocked by: none

- [ ] **T1-14 — Grant inspection test for every append-only table**
  - Acceptance: reads `information_schema.role_table_grants` after migrations and fails if `audit_log` gains UPDATE or DELETE for the application role, and if `clinical_record_versions` gains either; asserts the exact grant sets.
  - Verify: `uv run pytest tests/security/test_grant_inspection.py -v`
  - Files: `backend/tests/security/test_grant_inspection.py`
  - Controls: 1 Authentication (least privilege) · 6 Audit logging · 11 Security testing
  - Evidence: grant listing artefact attached to the Gate 2 bundle
  - Blocked by: none

- [ ] **T1-15 — `audit_log` UPDATE and DELETE refusal test**
  - Acceptance: `UPDATE audit_log` and `DELETE FROM audit_log` executed as the application role each raise a permission error; the test names the expected error class.
  - Verify: `uv run pytest tests/security/test_audit_app_role_cannot_update_or_delete.py -v`
  - Files: `backend/tests/security/test_audit_app_role_cannot_update_or_delete.py`
  - Controls: 6 Audit logging · 11 Security testing
  - Evidence: test output with the executed statements
  - Blocked by: none

## Workstream C — Isolation mechanics and fixture

- [ ] **T1-16 — Two-tenant isolation fixture with a canary and a suspended tenant**
  - Acceptance: deterministic fixed UUIDs; tenants A and B active, C a canary, D suspended; 3 patients per tenant with a surname that matches across tenants; distinct Medicare number ranges per tenant; structurally identical shapes; 10 audit events per tenant plus 1 null-tenant platform event; the fixture asserts its own row counts so a partial seed fails fast.
  - Verify: `uv run pytest tests/isolation/conftest.py::test_fixture_row_counts -v`
  - Files: `backend/tests/isolation/conftest.py`; `backend/tests/isolation/fixtures.py`
  - Controls: 3 Tenant isolation · 11 Security testing
  - Evidence: fixture self-assertion output
  - Blocked by: none

- [ ] **T1-17 — RLS holds without an application filter (I-016) and the policy-drop negative control**
  - Acceptance: a raw query with no tenant predicate, run as `clinos_app` with A's context, returns only A's rows; a scratch-database job then drops the policy and asserts that the same test **fails**, proving it can detect the regression it exists for.
  - Verify: `uv run pytest tests/isolation/test_rls_holds_without_app_filter.py tests/isolation/test_rls_policy_drop_detected.py -v`
  - Files: `backend/tests/isolation/test_rls_holds_without_app_filter.py`; `backend/tests/isolation/test_rls_policy_drop_detected.py`
  - Controls: 3 Tenant isolation · 11 Security testing
  - Evidence: both outputs, including the asserted failure
  - Blocked by: none

- [ ] **T1-18 — No tenant context returns zero rows (I-017)**
  - Acceptance: a raw query as `clinos_app` with no `app.tenant_id` set returns zero rows and raises no error, and the test asserts the negative explicitly rather than asserting an empty list is acceptable.
  - Verify: `uv run pytest tests/isolation/test_rls_no_context_returns_zero_rows.py -v`
  - Files: `backend/tests/isolation/test_rls_no_context_returns_zero_rows.py`
  - Controls: 3 Tenant isolation · 11 Security testing
  - Evidence: test output
  - Blocked by: none

- [ ] **T1-19 — `WITH CHECK` refuses a forged tenant write (I-018)**
  - Acceptance: inserting a row with tenant B's `tenant_id` while A's context is set is rejected by the database with a row-level security violation.
  - Verify: `uv run pytest tests/isolation/test_rls_with_check_blocks_cross_tenant_insert.py -v`
  - Files: `backend/tests/isolation/test_rls_with_check_blocks_cross_tenant_insert.py`
  - Controls: 3 Tenant isolation · 11 Security testing
  - Evidence: test output naming the violation
  - Blocked by: none

- [ ] **T1-20 — Connection-pool reuse test (I-015)**
  - Acceptance: 200 concurrent requests alternating tenants through the pooler, with a pool of at least 5 connections; every response is checked against its own tenant and no response contains another tenant's row.
  - Verify: `uv run pytest tests/isolation/test_pool_reuse.py -v`
  - Files: `backend/tests/isolation/test_pool_reuse.py`
  - Controls: 3 Tenant isolation · 11 Security testing
  - Evidence: test output; the named CI job definition
  - Blocked by: none

## Workstream D — Audit foundation

- [ ] **T1-21 — Append-only audit writer that joins the caller's transaction**
  - Acceptance: `audit.write(event)` is the only code that inserts into `audit_log`; it writes inside the caller's transaction with the exact envelope of [spec.md](../features/README.md) §5.1; a failed write raises and **fails the operation**; a rolled-back business write leaves no audit row.
  - Verify: `uv run pytest tests/security/test_audit_writes_in_same_transaction.py -v`
  - Files: `backend/app/core/audit.py`; `backend/tests/security/test_audit_writes_in_same_transaction.py`
  - Controls: 6 Audit logging · 9 Error handling
  - Evidence: test output including the rollback case
  - Blocked by: none

- [ ] **T1-22 — Audit `metadata` allow-list with a failing rejection path**
  - Acceptance: `metadata` keys are allow-listed per action; a key outside the allow-list raises and the request fails with `500 AUDIT_PAYLOAD_REJECTED`; clinical keys such as `directions`, `medicine_name` and `patient_name` are rejected before insert.
  - Verify: `uv run pytest tests/security/test_audit_payload_allowlist.py -v`
  - Files: `backend/app/core/audit.py`; `backend/tests/security/test_audit_payload_allowlist.py`
  - Controls: 5 Output validation · 6 Audit logging
  - Evidence: test output showing each rejected key
  - Blocked by: none

- [ ] **T1-23 — Audit event coverage test for the Phase 1 event set**
  - Acceptance: every Phase 1 event in [spec.md](../features/README.md) §5.4 is emitted by its operation, including `DENIED` and `FAILED` outcomes; the vocabulary is a single closed enumeration in code; the duplicate-candidate addition is registered in the vocabulary before use.
  - Verify: `uv run pytest tests/security/test_audit_event_coverage.py -v`
  - Files: `backend/app/core/audit_actions.py`; `backend/tests/security/test_audit_event_coverage.py`
  - Controls: 6 Audit logging · 12 Compliance evidence
  - Evidence: coverage test output; the action vocabulary diff against `07` §1
  - Blocked by: none

## Workstream E — Identity, sessions and step-up (D-003 blocked)

- [ ] **T1-24 — Login, token issuance and session creation for the chosen D-003 branch**
  - Acceptance: **Option A** — PKCE login and `/api/v1/auth/callback` verifying JWKS, `iss`, `aud`, `exp` and `nonce`. **Option B** — password login with Argon2id verification, breached-credential check, and a locally signed short-lived token. Either branch keeps the access token out of browser storage.
  - Verify: `uv run pytest tests/security/test_auth_login.py -v`
  - Files: `backend/app/modules/identity_tenancy/service.py`; `backend/app/modules/identity_tenancy/router.py`; `backend/tests/security/test_auth_login.py`
  - Controls: 1 Authentication · 8 Secrets management
  - Evidence: auth test output; (Option A) provider configuration export / (Option B) Argon2id parameter record
  - Blocked by: **D-003**

- [ ] **T1-25 — MFA enforcement for clinical and administrative roles**
  - Acceptance: no session is created without a second factor for any of the seven roles; a session without an enrolled factor reaches only the enrolment route and `GET /api/v1/auth/session`; MFA cannot be asserted by a client flag on a direct API call.
  - Verify: `uv run pytest tests/security/test_auth_mfa_enforcement.py tests/security/test_auth_mfa_bypass_attempt.py -v`
  - Files: `backend/app/modules/identity_tenancy/mfa.py`; `backend/tests/security/test_auth_mfa_enforcement.py`
  - Controls: 1 Authentication · 2 Authorisation
  - Evidence: test output; the MFA policy per role
  - Blocked by: **D-003**

- [ ] **T1-26 — Refresh rotation with family revocation and reuse detection**
  - Acceptance: two consecutive refreshes return different tokens and the first is rejected afterwards; replaying a rotated token revokes the whole family and writes the reuse-detection event; a revoked session is refused before token expiry; offboarding revokes all families within 60 seconds.
  - Verify: `uv run pytest tests/security/test_auth_refresh_rotation.py tests/security/test_auth_revoked_session.py -v`
  - Files: `backend/app/modules/identity_tenancy/service.py`; `backend/tests/security/test_auth_refresh_rotation.py`
  - Controls: 1 Authentication · 6 Audit logging
  - Evidence: test output for rotation, reuse and revocation
  - Blocked by: **D-003**

- [ ] **T1-27 — Step-up mechanism, single-use and resource-bound**
  - Acceptance: a step-up token is bound to user, session, operation and resource id; it is consumed on use; it cannot be replayed on another resource; a failed step-up is audited; the mechanism covers the five operations in [spec.md](../features/README.md) §4.5.
  - Verify: `uv run pytest tests/security/test_auth_step_up.py -v`
  - Files: `backend/app/core/security.py`; `backend/tests/security/test_auth_step_up.py`
  - Controls: 1 Authentication · 2 Authorisation · 6 Audit logging
  - Evidence: step-up test results including the replay rejection
  - Blocked by: **D-003**

- [ ] **T1-28 — Account lockout and the audited release path**
  - Acceptance: the confirmed threshold is enforced in the authentication path, never the UI; a locked account returns the same user-facing message as a wrong credential; the reason is written to the audit trail; an administrator release requires step-up and is audited.
  - Verify: `uv run pytest tests/security/test_auth_lockout.py -v`
  - Files: `backend/app/modules/identity_tenancy/service.py`; `backend/tests/security/test_auth_lockout.py`
  - Controls: 1 Authentication · 6 Audit logging · 10 Abuse protection
  - Evidence: lockout test output; the confirmed threshold recorded against the source conflict
  - Blocked by: **D-003**, plus **lockout-threshold** for the assertion value

## Workstream F — RBAC and the central policy layer

- [ ] **T1-29 — The central policy layer `can(actor, permission, resource)`**
  - Acceptance: one module owns every decision; evaluation order is fail-closed → resource-tenant match (`404` on mismatch) → permission held → resource rules; controllers never compare a role name or an actor id; permissions are resolved from roles at login, never from the request.
  - Verify: `uv run pytest tests/security/test_authz_recomputes_server_side.py tests/security/test_policy_layer.py -v`
  - Files: `backend/app/core/security.py`; `backend/app/core/policy.py`; `backend/tests/security/test_policy_layer.py`
  - Controls: 2 Authorisation · 9 Error handling
  - Evidence: policy-layer unit and integration test output
  - Blocked by: none

- [ ] **T1-30 — Access-control matrix test over every Phase 1 protected route**
  - Acceptance: for each route, an unauthenticated request returns `401` and a user without the permission returns `403`; every denial writes a denied audit event; the matrix is the `27-security-testing.md` §5 table restricted to Phase 1 routes.
  - Verify: `uv run pytest tests/security/test_authz_matrix.py -v`
  - Files: `backend/tests/security/test_authz_matrix.py`
  - Controls: 2 Authorisation · 6 Audit logging · 11 Security testing
  - Evidence: matrix run output
  - Blocked by: **permission-catalogue** for the permission values under test

- [ ] **T1-31 — Import-boundary lint (D-002)**
  - Acceptance: fails the build when one module imports another module's `models` or internals; cross-module access goes through the other module's `service.py` facade; modules communicate in-process only.
  - Verify: `uv run pytest tests/architecture/test_import_boundaries.py -v`
  - Files: `backend/tests/architecture/test_import_boundaries.py`
  - Controls: 2 Authorisation · 11 Security testing
  - Evidence: lint output; Gate 1 evidence (D-002 substitutes the lint for TypeScript project references)
  - Blocked by: none

## Workstream G — Patient register

- [ ] **T1-32 — Patient service and the four Phase 1 routes**
  - Acceptance: `GET /patients`, `POST /patients`, `GET /api/v1/patients/{id}`, `PATCH /api/v1/patients/{id}` each match the declaration in [spec.md](../features/README.md) §6.1; reads and writes go through the tenant-scoped transaction helper; responses are serialised through declared schemas and never a raw ORM entity; identifiers are masked on output.
  - Verify: `uv run pytest tests/api/test_patients.py -v`
  - Files: `backend/app/modules/patients/service.py`; `backend/app/modules/patients/router.py`; `backend/app/modules/patients/schemas.py`; `backend/tests/api/test_patients.py`
  - Controls: 2 Authorisation · 3 Tenant isolation · 4 Input validation · 5 Output validation · 6 Audit logging
  - Evidence: route test output; the four endpoint declarations
  - Blocked by: none

- [ ] **T1-33 — Duplicate candidate detection on create**
  - Acceptance: an exact name-plus-DOB match or an exact Medicare blind-index match raises a candidate; a two-identifier match refuses the create with a duplicate candidate rather than a second chart; the concurrent-create case rejects the second and returns a candidate; both outcomes are audited.
  - Verify: `uv run pytest tests/api/test_patients_duplicates.py -v`
  - Files: `backend/app/modules/patients/service.py`; `backend/tests/api/test_patients_duplicates.py`
  - Controls: 4 Input validation · 6 Audit logging
  - Evidence: test output including the negative (no second chart) case
  - Blocked by: none for the union rule; the refusal threshold is **OPEN** (Head of Product)

- [ ] **T1-34 — Treating-relationship rule and the care-relationship source**
  - Acceptance: a clinician with no active care relationship receives `403` with the care-relationship reason class and an audited denial; an accepted read records the relationship id and the purpose; the rule runs under the same RLS policy as the request and never widens to the tenant.
  - Verify: `uv run pytest tests/api/test_patients_relationship.py -v`
  - Files: `backend/app/core/policy.py`; `backend/app/modules/patients/service.py`; `backend/tests/api/test_patients_relationship.py`
  - Controls: 2 Authorisation · 3 Tenant isolation · 6 Audit logging
  - Evidence: test output; the `care_relationships` table specification
  - Blocked by: **care-relationships** — the table is not defined in the source schema contract

- [ ] **T1-35 — Cursor pagination, closed sort map and search filters**
  - Acceptance: every list is cursor-based; the cursor is opaque and signed and cannot be replayed across tenants; `limit` is capped at the server maximum; sort columns come from a closed mapping; `LIKE` wildcards are escaped before binding; the result cap is 25 on the patient list.
  - Verify: `uv run pytest tests/api/test_pagination.py tests/api/test_patient_search_isolation.py -v`
  - Files: `backend/app/core/pagination.py`; `backend/tests/api/test_pagination.py`
  - Controls: 3 Tenant isolation · 4 Input validation · 10 Abuse protection
  - Evidence: pagination and cross-tenant cursor test output
  - Blocked by: none

- [ ] **T1-36 — Medicare identifier validation, encryption and masking**
  - Acceptance: the Medicare number is validated with the confirmed check-digit algorithm, stored field-level encrypted with a keyed blind index for exact match only, and masked on output; the number never appears in a log, an error response or an audit payload.
  - Verify: `uv run pytest tests/api/test_patient_identifiers.py tests/security/test_no_phi_in_log_payload.py -v`
  - Files: `backend/app/modules/patients/identifiers.py`; `backend/tests/api/test_patient_identifiers.py`
  - Controls: 4 Input validation · 5 Output validation · 7 Encryption
  - Evidence: validation test output; the field-level encryption decision record
  - Blocked by: none for the mechanism; the algorithm and mask format are **REQUIRES VALIDATION** (repo-side source only)

## Workstream H — Clinical records

- [ ] **T1-37 — Clinical-record service with immutable versions and the amendment path**
  - Acceptance: a record and its versions are created through the module facade; no route mutates a version row; a signed note cannot be updated in place by any API path; an amendment with a reason creates a new version referencing the superseded version and increments `current_version`; the version ordering is deterministic under concurrent amendment.
  - Verify: `uv run pytest tests/api/test_clinical_records.py -v`
  - Files: `backend/app/modules/clinical_records/service.py`; `backend/app/modules/clinical_records/router.py`; `backend/tests/api/test_clinical_records.py`
  - Controls: 2 Authorisation · 4 Input validation · 6 Audit logging
  - Evidence: test output including the rejected in-place update
  - Blocked by: none

- [ ] **T1-38 — Clinical-record immutability at the database level**
  - Acceptance: an `UPDATE` and a `DELETE` against `clinical_record_versions` executed as the application role both raise a permission error; the original version remains retrievable after an amendment.
  - Verify: `uv run pytest tests/security/test_clinical_record_immutability.py -v`
  - Files: `backend/tests/security/test_clinical_record_immutability.py`
  - Controls: 6 Audit logging · 11 Security testing
  - Evidence: test output with the executed statements
  - Blocked by: none

## Workstream I — Security baseline middleware

- [ ] **T1-39 — Deny-by-default request pipeline in the literal handler order**
  - Acceptance: every sensitive handler runs deny-by-default → explicitly authorise → audit → validate → execute; there is no unprotected branch; a missing or erroring tenant resolution denies and fails closed; no handler reads `tenant_id`, `actor_id` or `role` from body, header or query.
  - Verify: `uv run pytest tests/security/test_errors_fail_closed.py tests/security/test_tenant_from_request_rejected.py -v`
  - Files: `backend/app/api/deps.py`; `backend/app/core/security.py`; `backend/tests/security/test_tenant_from_request_rejected.py`
  - Controls: 2 Authorisation · 3 Tenant isolation · 9 Error handling
  - Evidence: pipeline test output; the middleware order in code
  - Blocked by: none

- [ ] **T1-40 — The one error envelope and the no-internal-detail tests**
  - Acceptance: every error response is `{"error": {"code", "message", "request_id", "details"}}`; a message never contains clinical content, a secret, a stack trace, a SQL fragment or a table name; denials return `403` with a reason class and `404` where existence would leak; `request_id` appears in the response, every log line and every audit event for the request.
  - Verify: `uv run pytest tests/security/test_errors_never_leak_internal_detail.py -v`
  - Files: `backend/app/core/errors.py`; `backend/app/main.py`; `backend/tests/security/test_errors_never_leak_internal_detail.py`
  - Controls: 9 Error handling · 5 Output validation
  - Evidence: error-envelope test output; the recorded divergence from the source's flatter envelope
  - Blocked by: none

- [ ] **T1-41 — Request size limits and per-endpoint-class rate limits**
  - Acceptance: a global request maximum and a smaller clinical-write maximum are enforced as middleware constants; the nine rate-limit classes in [spec.md](../features/README.md) §9.4 are keyed per the table; a breach returns `429` with `Retry-After` and is logged; forwarded headers are not trusted for the client key.
  - Verify: `uv run pytest tests/security/test_rate_limits.py tests/security/test_request_size.py -v`
  - Files: `backend/app/core/limits.py`; `backend/tests/security/test_rate_limits.py`
  - Controls: 10 Abuse protection · 4 Input validation
  - Evidence: rate-limit test output; the two size constants recorded (values are **OPEN**)
  - Blocked by: none for the mechanism; the size values are **OPEN** (Security Lead)

- [ ] **T1-42 — No-PHI logging, redaction boundary and security headers**
  - Acceptance: structured logs carry request id, tenant id, service, route, action, latency and error class and **no clinical content**; sentinel patient identifiers, medicine names, tokens and document content never appear in a log, an error response, a metric or a bundle; every response carries HSTS, `X-Content-Type-Options`, `Referrer-Policy` and the other required headers.
  - Verify: `uv run pytest tests/security/test_no_phi_in_log_payload.py tests/security/test_security_headers.py -v`
  - Files: `backend/app/core/logging.py`; `backend/tests/security/test_no_phi_in_log_payload.py`
  - Controls: 9 Error handling · 11 Security testing
  - Evidence: sentinel leak test output; header assertion output
  - Blocked by: none

## Workstream J — Legacy state surface

- [ ] **T1-43 — `/api/state` freeze and contract snapshot — conditional on O3**
  - Acceptance: if a legacy `GET /api/state` surface exists, it is marked frozen, accepts no new fields, and a contract snapshot test is green in CI; a change requires CTO approval, and a compatibility adapter serves it from the same modular services with no business logic and no bypass of authorisation, tenant resolution or audit.
  - Verify: `uv run pytest tests/contract/test_api_state_snapshot.py -v`
  - Files: `backend/tests/contract/test_api_state_snapshot.py` (only if the surface exists)
  - Controls: 2 Authorisation · 3 Tenant isolation · 11 Security testing
  - Evidence: either the snapshot test output, or the recorded O3 finding that no such route exists
  - Blocked by: **O3** — the route does not exist in this repository; do not build an adapter for a route nothing calls

## Workstream K — Docker and CI security scanning

- [ ] **T1-44 — CI security stages in the fixed order with a critical-finding block**
  - Acceptance: the pipeline runs lint → typecheck → unit → integration → security tests → SAST → dependency → container → secret → build → deploy; a Critical finding blocks deploy without exception; a High finding blocks Done unless formally accepted with a compensating control and an expiry; suppression requires a recorded justification and expiry; the pipeline fails on a planted secret and a planted vulnerable dependency.
  - Verify: the repository's CI workflow run record on a branch with both planted fixtures
  - Files: `.github/workflows/test-backend.yml`; the security-scan workflow(s)
  - Controls: 11 Security testing · 8 Secrets management
  - Evidence: pipeline run records for the planted-fixture failure and a green run
  - Blocked by: none

- [ ] **T1-45 — Container image build and scan, pinned dependencies**
  - Acceptance: the backend image builds multi-stage, non-root, minimal base, pinned dependencies; the container scan and the dependency scan are clean of Critical findings; the image tag is immutable; `Dependabot` (or equivalent) is enabled at pull-request level.
  - Verify: `docker build` locally, then `docker compose up -d --wait db mailpit` and the CI container-scan stage
  - Files: `backend/Dockerfile`; `.github/dependabot.yml`
  - Controls: 7 Encryption (image hygiene) · 8 Secrets management · 11 Security testing
  - Evidence: image scan report; dependency scan report
  - Blocked by: none

## Workstream L — Gate evidence bundles

- [ ] **T1-46 — Gate 1 evidence bundle**
  - Acceptance: every Gate 1 check has a named artefact in [plan.md](../features/README.md) §6.1; the environment-separation item is recorded as blocked by D-004 rather than omitted; residual risks R1–R7 have named owners; the CI pipeline definition is attached with a green run.
  - Verify: the sign-off record template in [`gates.md`](../reference/gates.md) completed with the evidence locations
  - Files: `docs/evidence/gate-1.md`
  - Controls: 11 Security testing · 12 Compliance evidence
  - Evidence: signed Gate 1 record (CTO decision maker, Security Lead approver)
  - Blocked by: **D-004** for the environment-separation check only

- [ ] **T1-47 — Gate 2 evidence bundle**
  - Acceptance: isolation test report, pool-reuse output, grant listing, schema lint output, `WITH CHECK` test, no-context test and the app-role-not-owner output are all attached; the approval-grain check is recorded as not applicable to the Phase 1 schema and deferred to Phase 2 with a named owner; **no conditional pass is requested or recorded**.
  - Verify: the sign-off record template completed; each check line points at a `backend/tests/isolation/**` or `backend/tests/security/**` artefact
  - Files: `docs/evidence/gate-2.md`
  - Controls: 3 Tenant isolation · 6 Audit logging · 11 Security testing · 12 Compliance evidence
  - Evidence: signed Gate 2 record (Security Lead decision maker, CTO approver)
  - Blocked by: none

- [ ] **T1-48 — Gate 3 evidence bundle and the D-003 statement**
  - Acceptance: the auto-provable checks (RBAC matrix, no shared accounts, session-expiry and revocation tests where the branch allows) are attached; the MFA, step-up and account-recovery checks are recorded as **blocked by D-003** with the branch named; the bundle explicitly states that Gate 3 cannot be signed while D-003 is open and that MFA and step-up have no conditional pass.
  - Verify: the sign-off record template completed as `FAIL — blocked by D-003`, or `PASS` only after D-003 closes
  - Files: `docs/evidence/gate-3.md`
  - Controls: 1 Authentication · 2 Authorisation · 6 Audit logging · 11 Security testing · 12 Compliance evidence
  - Evidence: Gate 3 record with the blocker and the auto-provable evidence attached (Security Lead decision maker, CTO approver)
  - Blocked by: **D-003**

---

## Dependency-ordered execution summary

| Order | Tasks | Gate advanced |
|:--:|---|---|
| 1 | T1-01…T1-10 | Gate 2 schema entry criteria |
| 2 | T1-11…T1-15 | Gate 2 grants and roles |
| 3 | T1-16…T1-20 | Gate 2 isolation suite |
| 4 | T1-21…T1-23 | Gate 2 audit foundation |
| 5 | T1-29, T1-31, T1-39…T1-42 | Gate 1 and Gate 3 authorisation and baseline |
| 6 | T1-32…T1-38 | Gate 4 preparation |
| 7 | T1-24…T1-28 | Gate 3 — **blocked by D-003** |
| 8 | T1-30 | Gate 3 RBAC |
| 9 | T1-43 | Conditional on O3 |
| 10 | T1-44, T1-45 | Gate 1 supply chain |
| 11 | T1-46…T1-48 | Gate records |

## Sources

- `clinic-os-secure-by-design/23-sprint-plan.md` §3, §6, §7 — the ten workstreams, the dependency table, the scope-cut order
- `clinic-os-secure-by-design/05-tenant-isolation.md` §4, §5, §8, §9 — roles and grants, the policy pattern, the isolation test list and fixture
- `clinic-os-secure-by-design/07-audit-architecture.md` §1–§3, §12 — the envelope, the mandatory events and the audit tests
- `clinic-os-secure-by-design/06-authentication-rbac.md` §2, §3, §6, §8, §9, §13 — MFA, sessions, lockout, step-up, the matrix, the revocation tests
- `clinic-os-secure-by-design/27-security-testing.md` §4, §5, §6 — the CI order, the access-control matrix, the sentinel rules
- `clinic-os-secure-by-design/04-database-erd.md` §3–§9 — table specifications, migration strategy, grants, append-only enforcement
- Repo: [`README.md`](../reference/build-contract.md) §6 and §8, [`gates.md`](../reference/gates.md), [`definition-of-done.md`](../reference/definition-of-done.md), [`decisions/D-002-repo-layout.md`](../reference/decisions/D-002-repo-layout.md), [`decisions/D-003-identity-model.md`](../reference/decisions/D-003-identity-model.md)
