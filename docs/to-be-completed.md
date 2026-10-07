---
doc_id: OZ-PENDING-SCOPE
title: ClinicOS Remaining Scope & Implementation Backlog
owner: CTO (interim: Ishu Rajput)
status: APPROVED — Active Roadmap
last_reviewed: 2026-10-06
classification: RESTRICTED
repo_docs:
  - README.md
  - progress.md
  - reference/build-contract.md
  - reference/gates.md
  - reference/control-matrix.md
  - reference/open-questions.md
  - tasks/00-phase-0-foundation.md
  - tasks/01-phase-1-foundations.md
  - tasks/02-phase-2-tga-approval-engine.md
  - tasks/03-phase-3-eprescribing.md
  - tasks/04-phase-4-pilot-go-live.md
---

# ClinicOS Remaining Scope & Implementation Backlog

This document provides a single, exhaustive inventory of all features, technical controls, database tables,
and compliance gates that remain **to be completed** across the ClinicOS repository. It is mapped directly
against [`docs/reference/build-contract.md`](reference/build-contract.md), the 186 numbered delivery tasks in
[`docs/tasks/`](tasks/), the 17 feature specifications in [`docs/features/`](features/), and the security gates in
[`docs/reference/gates.md`](reference/gates.md).

---

## 1. Executive Summary of Scope

```
Total Project Scope: 186 Tasks across 5 Phases · 17 Feature Modules · 7 Security Gates · 6 Invariants
Current Progress:    ~25% (Foundations, Patients CRUD with RLS, RBAC Decision Engine & Admin UI, 184 Tests)
Remaining Scope:     ~75% (Security Hardening, Audit Trail, TGA Engine, Safety Gate, Prescribing, Dispatch, Ops)
```

### High-Level Delivery Phasing
* **Immediate Stream 1 (Pre-Production Hardening)**: Close 5 critical security/integrity gaps in existing code (P1–P5).
* **Phase 0 (Foundations - Completion)**: CI security scanning (Trivy, Gitleaks), branch protections, and Gate 1 architecture packet.
* **Phase 1 (Core Foundations - Completion)**: Clinical records, document storage, and the append-only cryptographic audit trail.
* **Phase 2 (Regulatory TGA Engine)**: Approvals register at grain, GiST exclusion constraints, verification workflows, and TGA inbox.
* **Phase 3 (e-Prescribing & Safety Gate)**: Fail-closed prescription safety gate, digital signing, and Parchment pharmacy dispatch.
* **Phase 4 (Pilot Go-Live & Platform Operations)**: Redacted structured logging, standard error envelopes, data retention jobs, and external penetration testing.

---

## 2. Immediate Pre-Production Hardening (Existing Code Gaps)

These five items address discrepancies between currently deployed code and the design contracts before
handling live Australian patient health information (PHI):

| # | Item | Document Reference | Description | Target Files |
|:---:|---|---|---|---|
| **P1** | **Tenant Status Enforcement** | `01-tenancy-and-clinics` (R10) | Verify `tenant.status == 'ACTIVE'` on every request in `get_actor`. Currently, suspended or closed clinics can still query patient records. | [`backend/app/api/deps.py`](../backend/app/api/deps.py)<br>[`backend/app/modules/users_roles/service.py`](../backend/app/modules/users_roles/service.py) |
| **P2** | **Session Lifetime & Password Reset Rate Limit** | `02-authentication` (R3)<br>`reference/build-contract` (Control 1) | Reduce `ACCESS_TOKEN_EXPIRE_MINUTES` from 8 days to 15 minutes. Add sliding-window rate limiting (5/min) to `POST /api/v1/reset-password/`. | [`backend/app/core/config.py`](../backend/app/core/config.py)<br>[`backend/app/api/routes/login.py`](../backend/app/api/routes/login.py) |
| **P3** | **Atomic Clinic Registration** | `01-tenancy-and-clinics`<br>`reference/business-flow` | Wrap `Tenant` creation, `User` creation, and `Role` provisioning into a single atomic database transaction. Catch slug collisions with deterministic retry. | [`backend/app/api/routes/users.py`](../backend/app/api/routes/users.py)<br>[`backend/app/modules/identity_tenancy/service.py`](../backend/app/modules/identity_tenancy/service.py) |
| **P4** | **Safe User Deactivation** | `03-users-and-roles` (R11) | Replace hard `session.delete(user)` on `DELETE /api/v1/users/{id}` with `user.is_active = False` to prevent foreign key violation crashes on `user_roles` and preserve clinical attribution. | [`backend/app/api/routes/users.py`](../backend/app/api/routes/users.py) |
| **P5** | **Activate `clinos_app` in Production** | `reference/build-contract` (INV-1)<br>`reference/gates` (Gate 2) | Cloud `DATABASE_URL` connects as `neondb_owner` (`rolbypassrls = true`), bypassing RLS. Grant `clinos_app` `INSERT ON tenants` & `SELECT ON user.hashed_password`, then switch connection. | [`backend/app/alembic/versions/`](../backend/app/alembic/versions/)<br>FastAPI Cloud Env |

---

## 3. Phase-by-Phase Task Breakdown ([`docs/tasks/`](tasks/))

### Phase 0: Foundation Tasks ([`docs/tasks/00-phase-0-foundation.md`](tasks/00-phase-0-foundation.md))
* [x] **T0-1 … T0-4**: Monorepo layout, backend module skeleton, import-boundary lint, and green test baseline.
* [x] **T0-5 … T0-8**: Docker compose local dev, container healthchecks, non-root user, and lockfile reproducibility.
* [x] **T0-9 … T0-12**: Environment configuration (`.env.example`), Pydantic Settings, secret isolation.
* [x] **T0-13**: SAST linting in CI via `ruff`.
* [ ] **T0-14 — Dependency Vulnerability Scanning**: Add `pip-audit` / `trivy` container scanning into GitHub Actions CI.
* [ ] **T0-15 — Secret Scanning**: Wire automated `gitleaks` scanning into CI to prevent secret commits.
* [x] **T0-16**: CI pipeline failure enforcement on check failure.
* [x] **T0-17**: `AGENTS.md` standing orders and operational guidelines.
* [ ] **T0-18 — Repository Branch Protections**: Enforce signed commits, required PR reviews, and passing CI status checks on `main`.
* [x] **T0-19**: Pull request template with definition-of-done checklist.
* [ ] **T0-20 — Gate 1 Architecture Packet**: Assemble the initial architecture sign-off evidence bundle.

---

### Phase 1: Core Foundations Tasks ([`docs/tasks/01-phase-1-foundations.md`](tasks/01-phase-1-foundations.md))

#### Workstream A: Data Plane & Tenant Isolation
* [x] **T1-01 (Part A)**: `tenants` table with metadata conventions and RLS policies (`134a7201f6d2`).
* [ ] **T1-01 (Part B) — `clinics` Table**: Multi-site practice locations per tenant (`id`, `tenant_id`, `name`, `address`, `phone`).
* [x] **T1-02**: `roles`, `permissions`, `role_permissions`, and `user_roles` with RLS and grants (`f96bc0861b16`, `4d092676eafa`, `a1f2b3c4d5e6`).
* [ ] **T1-03 — Unified `users` Migration**: Migrate legacy template `user` table to normalized `users` model once D-003 is settled.
* [ ] **T1-04 — `care_relationships` Table**: Model practitioner-patient treating relationships with active intervals (`active_from`, `active_to`).
* [x] **T1-05 (Part A)**: RLS policy verification tests (`test_patients_isolation.py`, `test_every_tenant_table_has_policy.py`).
* [ ] **T1-05 (Part B) — Connection Pool Reuse Test**: Assert `test_pool_reuse.py` verifies zero tenant state leakage across pooled connections.
* [x] **T1-06**: `patients` table migration with forced RLS (`134a7201f6d2`).
* [ ] **T1-07 — Identifier Field-Level Encryption**: AES-GCM-256 envelope encryption for `medicare_number` and `ihi`.
* [ ] **T1-08 — Blind Indexing**: HMAC-SHA256 keyed blind index for exact-match patient search without decrypting database columns.
* [ ] **T1-09 — `audit_log` Table Migration**: Append-only table schema with event IDs, actor context, and previous hash columns.
* [ ] **T1-10 — DB Privilege Revocation for Audit Log**: Execute `REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app`.

#### Workstream B: Identity, Auth & RBAC
* [x] **T1-11 … T1-14**: RBAC `can()` and `can_grant()` policy evaluation engine, seed roles, and administrative API.
* [ ] **T1-15 — Refresh Token Rotation**: Server-side opaque refresh token storage with automatic family revocation on reuse.
* [ ] **T1-16 — Multi-Factor Authentication (MFA)**: TOTP enrolment and mandatory verification for clinical and administrative users.
* [ ] **T1-17 — Account Lockout Mechanism**: 5 failed login attempts in 15 minutes triggers a 30-minute account lockout.
* [ ] **T1-18 — Step-Up Authentication Tokens**: 5-minute single-use step-up tokens for high-risk clinical and merge operations.
* [ ] **T1-19 — Production Email Delivery**: Integrate transactional email delivery (Amazon SES / SendGrid) for password reset flows.
* [ ] **T1-20 — Gate 3 Evidence Bundle**: Assemble authentication evidence pack (token rotation tests, lockout proofs, MFA flows).

#### Workstream C: Patients & Clinical Records
* [x] **T1-21 … T1-24**: Patients API routes (`POST`, `GET`, `GET /{id}`, `PATCH /{id}`), pagination, and React UI screens.
* [ ] **T1-25 — Patient Identifier Masking**: Enforce `•••• ` + last 3 digits masking on all responses and logs (**INV-5**).
* [x] **T1-26 - Patient Search Endpoint**: `POST /api/v1/patients/search` with JSON body (prohibiting search terms in URL query strings); keyset paging on `GET /api/v1/patients`.
* [ ] **T1-27 — Patient Merge Workflow**: Step-up protected `POST /api/v1/patients/{id}/merge` with audit attribution.
* [ ] **T1-28 — Clinical Encounters & Notes**: Models and APIs for consultation notes with immutable amendment chains.
* [ ] **T1-29 — Document Storage Integration**: AWS S3 client (`ap-southeast-2`) with 15-minute presigned URLs and tenant isolation.
* [ ] **T1-30 — Document Antivirus Scanning**: ClamAV pipeline gating file availability upon upload.

#### Workstream D: Audit Engine & Gate Evidence
* [ ] **T1-31 — Single Writer Facade**: Python `AuditWriter` service committing audit records atomically within domain transactions.
* [ ] **T1-32 — Cryptographic Hash Chaining**: `hash = SHA256(canonical_json(event) + prev_hash)` tamper-evident chain.
* [ ] **T1-33 — Continuous Verification Job**: Scheduled background task verifying audit chain integrity every 15 minutes.
* [ ] **T1-34 — S3 Compliance Outbox**: Asynchronous exporter streaming audit batches to AWS S3 Object Lock (Compliance Mode).
* [ ] **T1-35 … T1-42**: Audit read APIs, RBAC integration, and Gate 2 sign-off evidence bundle.

---

### Phase 2: TGA Approval Engine Tasks ([`docs/tasks/02-phase-2-tga-approval-engine.md`](tasks/02-phase-2-tga-approval-engine.md))

* [ ] **T2-1 — Database Tables**: `tga_approvals`, `tga_approval_events`, `tga_inbox_messages`, `tga_inbox_attachments`, `tga_extraction_results`.
* [ ] **T2-2 — RLS Policies**: Force RLS with tenant isolation on all Phase 2 tables.
* [ ] **T2-3 — GiST Exclusion Constraint**: `EXCLUDE USING gist (tenant_id WITH =, patient_id WITH =, tga_category WITH =, dosage_form WITH =, validity_interval WITH &&) WHERE (state = 'ACTIVE')` (**INV-2**).
* [ ] **T2-4 — Domain Check Constraints**: Enforce 2-year maximum validity (`valid_to <= valid_from + INTERVAL '2 years'`) and valid state transitions.
* [ ] **T2-5 — Privilege Restrictions**: Revoke `DELETE` and restrict update grants on extraction and approval tables.
* [ ] **T2-6 … T2-12 — TGA Service Engine**: State machine transitions (`PENDING` $\rightarrow$ `ACTIVE` $\rightarrow$ `SUPERSEDED` / `EXPIRED` / `REVOKED`), supersede chaining, and point-in-time validity matching.
* [ ] **T2-13 … T2-18 — TGA Approval APIs**: Endpoints for approval creation, querying, amendment, revocation, and four-eyes verification.
* [ ] **T2-19 … T2-24 — TGA Inbox Ingestion**: Webhook intake for regulator decision letters, PDF parsing, OCR extraction, and extraction confidence scoring.
* [ ] **T2-25 … T2-30 — Clinician Verification UI**: Two-person rule verification UI allowing clinical staff to review extracted fields against source PDFs.
* [ ] **T2-31 … T2-35 — Gate 4 Evidence Packet**: Complete negative decision matrix test suite (100% pass rate) and Gate 4 sign-off bundle.

---

### Phase 3: e-Prescribing & Safety Gate Tasks ([`docs/tasks/03-phase-3-eprescribing.md`](tasks/03-phase-3-eprescribing.md))

* [ ] **T3-1 … T3-5 — Parchment Adapter Boundary**: Resilient adapter interface with exponential backoff, circuit breaking, bulkheading, and redacted logging.
* [ ] **T3-6 … T3-10 — Prescription Schema & State Machine**: `prescriptions`, `prescription_items`, and `dispense_records` tables with state machine (`DRAFT` $\rightarrow$ `PENDING_GATE` $\rightarrow$ `SAFETY_VERIFIED` $\rightarrow$ `SIGNED` $\rightarrow$ `DISPATCHED`).
* [ ] **T3-11 … T3-16 — Prescription Safety Gate Engine**: Hard fail-closed check refusing dispensing (`BLOCKED`) without an active, matching TGA approval at `date_of_service` (**INV-2**).
* [ ] **T3-17 … T3-22 — Negative Decision Matrix**: Implement 14 negative decision codes (`TGA_CATEGORY_MISMATCH`, `TGA_APPROVAL_EXPIRED`, `TGA_APPROVAL_REVOKED`, etc.) with mandatory audit event emission.
* [ ] **T3-23 … T3-26 — Cryptographic Digital Signing**: Authorised Prescriber cryptographic signing using client certificates and step-up auth.
* [ ] **T3-27 … T3-30 — Transactional Outbox & Dispatch Worker**: Guaranteed at-least-once prescription dispatch with `Idempotency-Key` headers.
* [ ] **T3-31 … T3-32 — Gate 5 Evidence Packet**: Comprehensive safety gate refusal proofs and Gate 5 sign-off packet.

---

### Phase 4: Pilot Go-Live & Operations Tasks ([`docs/tasks/04-phase-4-pilot-go-live.md`](tasks/04-phase-4-pilot-go-live.md))

* [ ] **T4-1 … T4-3 — Decision Closure & Secret Rotation**: Formally close D-003 and D-004; rotate committed `.env` secrets across all environments.
* [ ] **T4-4 … T4-8 — Structured Observability**: `structlog` JSON logging with automated PHI redaction filter (**INV-5**), and `CorrelationIdMiddleware` propagating `X-Request-ID`.
* [ ] **T4-9 … T4-12 — Uniform Error Envelope**: Standard RFC 7807 error format preventing database errors or tracebacks from leaking to API clients (Control 9).
* [ ] **T4-13 … T4-17 — Automated Data Retention Jobs**: Scheduled worker enforcing 7-year adult and 25-year pediatric medical record retention rules.
* [ ] **T4-18 … T4-22 — Disaster Recovery & Backup Restore Drill**: Documented and verified database restore drill from Neon/S3 snapshots in AWS Sydney.
* [ ] **T4-23 … T4-25 — External Penetration Testing**: Independent CREST-accredited penetration test remediating all High/Critical findings.
* [ ] **T4-26 … T4-28 — Gates 6 & 7 Sign-Off**: Operational readiness review, clinical safety sign-off, and pilot clinic onboarding approval.

---

## 4. Feature-by-Feature Specification Backlog ([`docs/features/`](features/))

Detailed breakdown of the 17 numbered feature specifications in `docs/features/`:

### Feature 00: Foundations ([`features/00-foundations/`](features/00-foundations/01-requirements.md))
- [ ] Add dependency vulnerability scanning (`trivy` / `pip-audit`) to CI.
- [ ] Add automated secret scanning (`gitleaks`) to GitHub Actions.
- [ ] Enforce branch protection rules on `main` (signed commits, passing CI, 1 approval).

### Feature 01: Tenancy & Clinics ([`features/01-tenancy-and-clinics/`](features/01-tenancy-and-clinics/01-requirements.md))
- [ ] Model `clinics` table (multi-site locations within a tenant).
- [ ] Administrative tenant management API (`GET /api/v1/tenants/current`, `PATCH /api/v1/tenants/current`).
- [ ] Enforce tenant status (`ACTIVE` check in auth pipeline, R10).
- [ ] Atomic organization registration transaction with automatic slug collision retry.

### Feature 02: Authentication & Identity ([`features/02-authentication/`](features/02-authentication/01-requirements.md))
- [ ] Settle Decision D-003 (Managed OIDC vs Hardened PyJWT).
- [ ] Shorten access token expiry to 15 minutes.
- [ ] Implement database-backed single-use refresh token rotation with family reuse revocation (R4, R5).
- [ ] Time-based One-Time Password (TOTP) MFA enrollment and verification (R2).
- [ ] Account lockout after 5 consecutive failed login attempts (R8).
- [ ] Step-up authentication tokens for destructive/clinical actions (R9).
- [ ] Session revocation API revoking active token families within 60 seconds (R6).
- [ ] Configure production transactional email provider (SES / SendGrid).

### Feature 03: Users & Roles ([`features/03-users-and-roles/`](features/03-users-and-roles/01-requirements.md))
- [ ] Replace hard delete `DELETE /api/v1/users/{id}` with soft deactivation (`user.is_active = False`, R11).
- [ ] Transition from template `user` table to normalized `users` model once D-003 is settled.
- [ ] Create `care_relationships` table modeling doctor-patient relationships.
- [ ] Incorporate active care relationship check into clinical authorization rules (R7).
- [ ] Support custom role definitions composed by Practice Owners from the permission catalog (OPEN-2).

### Feature 04: Append-Only Audit Log ([`features/04-audit-log/`](features/04-audit-log/01-requirements.md)) — *Top Priority (INV-4)*
- [ ] Create `audit_log` table with hash chaining metadata (`prev_hash`, `hash`).
- [ ] Enforce append-only grants: `REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app`.
- [ ] Implement transactional `AuditWriter` facade guaranteeing atomic event emission with business logic.
- [ ] Cryptographic SHA-256 hash chaining over canonical JSON representations of events.
- [ ] Background verification worker validating chain integrity every 15 minutes.
- [ ] S3 Object Lock compliance export worker streaming audit batches to immutable cloud storage.
- [ ] Keyset-paginated audit read API (`GET /api/v1/audit/events`) with mandatory audit logging of audit reads.

### Feature 05: Patients ([`features/05-patients/`](features/05-patients/01-requirements.md))
- [ ] Implement AES-GCM-256 field-level envelope encryption for `medicare_number` and `ihi` (R8).
- [ ] Implement HMAC-SHA256 keyed blind indexing for exact-match patient search (R8).
- [ ] Mask patient health identifiers in all API responses and logs (`•••• ` + last 3 digits, R9, INV-5).
- [ ] Two-identifier demographic duplicate detection on patient creation (R4).
- [ ] Reversible patient record merge workflow (`POST /api/v1/patients/{id}/merge`) with step-up auth (R10).
- [ ] Dedicated patient search endpoint (`POST /api/v1/patients/search`) with JSON payload (R12).
- [ ] Patient data export API requiring step-up auth and typed clinical purpose (R14).

### Feature 06: Clinical Records ([`features/06-clinical-records/`](features/06-clinical-records/01-requirements.md))
- [ ] Database models: `encounters`, `consultation_notes`, `diagnoses`, `allergies` tables with forced RLS.
- [ ] Append-only consultation note amendments (prohibiting in-place mutation of clinical notes).
- [ ] Tag note bodies as `HIGHLY_SENSITIVE` data classification (redacted from logs, encrypted at rest).

### Feature 07: Documents ([`features/07-documents/`](features/07-documents/01-requirements.md))
- [ ] AWS S3 document bucket configuration pinned to Sydney (`ap-southeast-2`) with tenant prefix isolation.
- [ ] 15-minute time-limited pre-signed upload and download URLs gated by tenant authorization.
- [ ] Asynchronous ClamAV malware scanning pipeline gating document availability upon upload.

### Feature 08: TGA Approvals Engine ([`features/08-tga-approvals/`](features/08-tga-approvals/01-requirements.md)) — *Milestone M2 (INV-2)*
- [ ] Database schema: `tga_approvals`, `tga_approval_events` with forced RLS.
- [ ] GiST exclusion constraint rejecting overlapping active intervals on `[tenant_id, patient_id, tga_category, dosage_form]` (D-006, R11).
- [ ] 2-year maximum approval duration check constraint (`valid_to <= valid_from + INTERVAL '2 years'`).
- [ ] Controlled state machine transitions (`PENDING` $\rightarrow$ `ACTIVE` $\rightarrow$ `SUPERSEDED` / `EXPIRED` / `REVOKED`).
- [ ] Enforce four-eyes principle: approval creator cannot verify their own manual entry (R5).
- [ ] Point-in-time validity matching against consultation `date_of_service`.

### Feature 09: TGA Inbox & Ingestion ([`features/09-tga-inbox/`](features/09-tga-inbox/01-requirements.md))
- [ ] Webhook intake endpoint receiving digital decision letters from the regulator.
- [ ] PDF document parsing and OCR extraction pipeline for approval numbers, categories, and patient names.
- [ ] Staff review UI screen for validating extracted data against the original PDF before activation.

### Feature 10: Prescription Safety Gate ([`features/10-prescription-safety-gate/`](features/10-prescription-safety-gate/01-requirements.md)) — *Milestone M3 (INV-2)*
- [ ] Hard clinical dispensing block: script dispensing refused (`BLOCKED`) without an active, in-window matching TGA approval.
- [ ] Negative decision matrix evaluating 14 distinct rejection codes with fail-closed semantics.
- [ ] Mandatory audit event emission for every safety gate evaluation (capturing actor, patient, and decision reason).

### Feature 11: Prescribing ([`features/11-prescribing/`](features/11-prescribing/01-requirements.md))
- [ ] Database schema: `prescriptions`, `prescription_items`, and `dispense_records`.
- [ ] Prescription lifecycle state machine: `DRAFT` $\rightarrow$ `PENDING_GATE` $\rightarrow$ `SAFETY_VERIFIED` $\rightarrow$ `SIGNED` $\rightarrow$ `DISPATCHED`.
- [ ] Cryptographic digital signing for Authorised Prescribers using client certificates and step-up auth.

### Feature 12: Pharmacy Dispatch ([`features/12-pharmacy-dispatch/`](features/12-pharmacy-dispatch/01-requirements.md))
- [ ] Transactional outbox pattern for asynchronous prescription transmission.
- [ ] Idempotency enforcement via `Idempotency-Key` headers preventing duplicate script orders.
- [ ] Resilient Parchment adapter with circuit breaking, timeouts, jittered backoff, and bulkheading.

### Feature 13: Integration Boundaries ([`features/13-integration-boundaries/`](features/13-integration-boundaries/01-requirements.md))
- [ ] Outbound webhook delivery engine with HMAC-SHA256 signatures and automated retry.
- [ ] External API circuit breakers, bulkheads, and timeouts isolating third-party healthcare services.

### Feature 14: Reports and Regulatory Exports ([`features/14-reports-and-exports`](features/14-reports-and-exports/01-requirements.md))
- [ ] Automated 6-monthly TGA compliance export of unapproved therapeutic goods prescribing.
- [ ] Machine-readable patient record export format (Australian Privacy Principle APP 12 DSAR compliance).

### Feature 15: Admin, Config & Retention ([`features/15-admin-and-config`](features/15-admin-and-config/01-requirements.md))
- [ ] Clinic configuration management (operating hours, consultation fee schedules, legal contacts).
- [ ] Automated health data retention enforcement (7 years adult, 25 years pediatric; no hard deletes).
- [ ] Break-glass emergency clinical access procedure with dual executive authorization and high-priority audit alerts.

### Feature 16: Operations & Observability ([`features/16-operations-and-observability`](features/16-operations-and-observability/01-requirements.md))
- [ ] Structured JSON logging via `structlog` with automated PHI redaction filter (**INV-5**).
- [ ] `CorrelationIdMiddleware` injecting `X-Request-ID` across HTTP requests, application logs, and database sessions.
- [ ] Standard RFC 7807 error envelopes guaranteeing zero SQL queries, parameters, or tracebacks leak to clients.
- [ ] Verified disaster recovery restore drill from automated Neon/S3 backup snapshots.

---

## 5. Architectural Invariants & Security Controls Status

### The 6 Core Architectural Invariants ([`reference/build-contract.md` §5](reference/build-contract.md))

| Invariant | Description | Current Status | Remaining Action to Complete |
|:---:|---|:---:|---|
| **INV-1** | **Tenant isolation via Postgres RLS** | ⚠️ Partial | RLS active on `patients` and RBAC tables in local dev, but bypassed in cloud because `DATABASE_URL` connects as `neondb_owner`. Must grant privileges and switch to `clinos_app`. |
| **INV-2** | **TGA approval safety gate** | ❌ Not Started | Approvals table, GiST exclusion constraint, and fail-closed prescription safety gate remain to be implemented (Phases 2 & 3). |
| **INV-3** | **Fail-closed authorization** | ⚠️ Partial | RBAC engine evaluates `can()` deny-by-default, but auth pipeline lacks tenant `ACTIVE` check (P1) and registration is non-atomic (P3). |
| **INV-4** | **Tamper-evident audit trail** | ❌ Not Started | `audit_log` table with SHA-256 hash chaining, privilege revocation, and S3 Object Lock streaming remain to be implemented (Feature 04). |
| **INV-5** | **Zero raw PHI in logs** | ❌ Not Started | Structured logging with regex PHI redaction filters and Medicare/IHI masking remain to be implemented. |
| **INV-6** | **Sydney data residency** | ✅ Verified | Neon PostgreSQL database instance is strictly provisioned in AWS Sydney (`ap-southeast-2`). |

### The 12 Technical Controls ([`reference/build-contract.md` §6](reference/build-contract.md))

* **Control 1 (Authentication)**: ⚠️ Partial. Password auth exists, but needs 15-min token expiry, refresh token rotation, and MFA.
* **Control 2 (Authorisation)**: ✅ Complete for core. RBAC engine `can()` and 19-permission catalog implemented. Needs care-relationship rule.
* **Control 3 (Tenant Isolation)**: ⚠️ Partial. RLS policies implemented; needs cloud activation of `clinos_app` and `clinics` table.
* **Control 4 (Input Validation)**: ✅ Complete. Pydantic v2 schemas strictly validate every endpoint.
* **Control 5 (Output Validation)**: ⚠️ Partial. Patient schemas implemented; needs PHI masking (`•••• ` + last 3 digits).
* **Control 6 (Audit Logging)**: ❌ Not Started. Append-only `audit_log` writer and hash chaining pending.
* **Control 7 (Encryption)**: ⚠️ Partial. TLS 1.3 in transit and AES-256 at rest; needs field-level envelope encryption for Medicare/IHI.
* **Control 8 (Secrets Management)**: ⚠️ Partial. `.env` untracked; needs automated secret scanning in CI (Gitleaks) and secret rotation.
* **Control 9 (Error Handling)**: ⚠️ Partial. 401/403/404 handling clean; needs uniform RFC 7807 error envelopes across all routes.
* **Control 10 (Abuse Protection)**: ⚠️ Partial. Login/recovery rate limiting in place; needs rate limit on reset-password and proxy-safe IP resolution.
* **Control 11 (Security Testing)**: ⚠️ Partial. 184 backend isolation/RBAC tests passing; needs SAST/SCA in CI and external pen testing.
* **Control 12 (Compliance Evidence)**: ⚠️ Partial. Test suites and documentation maintained; needs formal gate evidence bundles.

---

## 6. Security Gates Sign-Off Backlog ([`docs/reference/gates.md`](reference/gates.md))

No security gate has yet been formally signed. The evidence bundles required to exit each gate are:

| Gate | Phase | Key Exit Criteria Remaining | Required Signer |
|:---:|:---:|---|---|
| **Gate 1** | Foundations | Settle D-003 (Identity model) and D-004 (FastAPI Cloud + Neon deployment architecture). | CTO + Security Lead |
| **Gate 2** | Database & Isolation | Switch production connection to `clinos_app`; verify zero cross-tenant reads under raw SQL; implement append-only `audit_log`. | Security Lead |
| **Gate 3** | Authentication | Enforce MFA, 15-minute token expiry, session revocation, and account lockout. | Security Lead |
| **Gate 4** | Clinical APIs & TGA | Pass 100% of TGA negative decision matrix tests; prove GiST exclusion constraint on active intervals. | Clinical Safety Officer |
| **Gate 5** | Prescribing & Safety Gate | Prove Prescription Safety Gate refuses dispensing without active approval; test cryptographic signing. | Clinical Safety Officer |
| **Gate 6** | Production Readiness | External penetration test report with zero High/Critical findings; automated secret scanning in CI (T0-13–T0-15). | Security Lead |
| **Gate 7** | Pilot Go-Live | Clinical governance sign-off; manual fallback procedure verified; disaster restore drill completed. | CEO / Practice Owner |

---

## 7. Open Architectural Decisions & Questions ([`docs/reference/`](reference/))

### Blocking Architectural Decisions ([`reference/decisions/`](reference/decisions/))
* **[D-003](reference/decisions/D-003-identity-model.md) — Identity Model (Managed OIDC vs Self-Hosted Password Auth)**:
  * *Status*: 🔴 **OPEN** (Blocks Gate 3).
  * *Options*: Option A (Auth0/Cognito managed identity) vs Option B (Hardened self-hosted PyJWT + Argon2id + TOTP MFA).
* **[D-004](reference/decisions/D-004-deployment-target.md) — Deployment Architecture Target**:
  * *Status*: 🔴 **OPEN on paper** (Blocks Gate 6 & 7). Settled in practice by FastAPI Cloud + Neon Sydney; needs a formal decision record.
* **[D-006](reference/decisions/D-006-approval-grain-and-validity-boundary.md) — TGA Validity Window Boundary**:
  * *Status*: 🔴 **OPEN (Clinical Safety Officer)**. Settled provisionally as half-open `[valid_from, valid_to)` as a fail-safe.

### Regulatory & Clinical Validation Items ([`reference/open-questions.md`](reference/open-questions.md))
* **OPEN-1 (Clinics vs Tenants Hierarchy)**: Whether a clinic is a physical site under an organisation tenant or an organisation itself.
* **OPEN-2 (Custom Roles)**: Permissibility of custom role bundles by Practice Owners vs fixed statutory roles.
* **OPEN-3 (SAS-B Notification Archival)**: Statutory retention requirement for TGA electronic acknowledgment receipts.
* **OPEN-4 (Parchment Dispatch Retry Limits)**: Maximum retry duration before marking script dispatch as failed and alerting prescriber.
* **OPEN-5 (Break-Glass Protocol)**: Dual-authorization requirements for emergency clinical chart access.
* **OPEN-6 (Audit Log Retention Window)**: Minimum duration for retaining raw audit log events in S3 Object Lock (mandated $\ge 7$ years).
