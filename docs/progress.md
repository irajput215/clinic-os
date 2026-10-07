---
doc_id: OZ-PROGRESS
title: Build progress against the contract
owner: CTO (interim: Ishu Rajput)
status: DRAFT — for review
last_reviewed: 2026-10-06
next_review: 2026-11-06
classification: RESTRICTED
repo_docs:
  - README.md
  - reference/build-contract.md
  - reference/gates.md
  - reference/decisions/README.md
  - to-be-completed.md
---

# Build progress

One page answering three questions: **what is actually built**, **what is verified**, and **what the rest
of this set now says that is no longer true**.

[`README.md`](README.md) states that "nothing is implemented". That is no longer accurate. The foundations,
the first tenant-scoped clinical table (`patients`) with forced RLS, the central RBAC authorization engine,
and the management UI are built and verified.

Everything below is stated against an artefact. `README.md`'s evidence discipline applies here too: a
claim with no artefact is a gap, not progress.

---

## 1. The board

Read this first. **Done** means merged to `main` and verified; **Next** is ordered.

### ✅ Done — merged and verified

| # | Item | Evidence |
|:---:|---|---|
| D1 | `.env` untracked, ignored, and replaced by `.env.example` | PR #11 |
| D2 | Standing orders for contributors and agents — `AGENTS.md` | PR #12 |
| D3 | Tenant-scoped transaction helper: `SET LOCAL`, refuses to open without a tenant | [`core/db.py`](../backend/app/core/db.py) |
| D4 | `tenants` table, migration, and an opt-in demo seed | `706856e36a80` |
| D5 | pytest refuses to run against a non-local database | [`tests/conftest.py`](../backend/tests/conftest.py) |
| D6 | One constraint naming convention, one model registry | PR #13 · `fb0ce1f1fff5` |
| D7 | `updated_at` is actually maintained | PR #13 |
| D8 | Demo seed opt-in (`SEED_DEMO_TENANT`, default false) | PR #13 |
| D9 | Unauthenticated `POST /private/users/` removed | PR #13 |
| D10 | Self-registration closed by default; the signup page removed | PR #14 |
| D11 | `item` domain dropped — table, API, UI and tests | PR #15 · `89d27ee38a6f` |
| D12 | Rate limiting: login 20/min, password recovery 5/min | [`core/rate_limit.py`](../backend/app/core/rate_limit.py) |
| D13 | Recovery HTML enumeration oracle removed | PR #15 |
| D14 | Six defects corrected in this document set | commit `57c5878` |
| D15 | This board, and the index corrections beside it | PR #16 |
| D16 | clinicOS branding replaces the template's | PR #18 |
| D17 | Self-registration reopened as **organisation registration**: one signup creates one tenant and makes the signer its administrator — supersedes D10 | PR #19 |
| D18 | Readiness probe `GET /api/v1/health/ready/` — boolean only, never tenant-routed; liveness deliberately left independent of the database | PR #20 |
| D19 | A deploy can no longer report success while the app is broken: the workflow fails when the readiness probe does not answer `200` | PR #20 · #22 |
| D20 | The outage closed: the deployed credential corrected, then verified live — readiness `200`, login `200`, signup creates the organisation | Deploy run `37303519527`, green end to end |
| D21 | The two `tenants` check constraints renamed to what the models declare, and a test asserting **every** constraint and index name against the metadata | migration `f993c55e6eaf` · [`test_schema_conventions.py`](../backend/tests/core/test_schema_conventions.py) |
| D22 | Schema conventions written down ([`database-conventions.md`](reference/database-conventions.md)); `User` ↔ `Tenant` relationships declared on both sides with a test; `alembic check` and the generated ER diagrams now gated in CI | [`schema-diagram.sh`](../scripts/schema-diagram.sh) · [`schema/`](reference/schema/README.md) · `.github/workflows/test-backend.yml` |
| D23 | `patients` created — the first tenant-scoped table — with forced RLS, a permissive policy that actually grants a caller its own rows, the design's restrictive floor, and `clinos_app` (no superuser, no `BYPASSRLS`, no `DELETE` grant) | PR #28 · migration `134a7201f6d2` · [`test_patients_isolation.py`](../backend/tests/isolation/test_patients_isolation.py) |
| D24 | The five database roles created with least-privilege grants — `clinos_app` holds no `DELETE` or `TRUNCATE` — and `MIGRATION_DATABASE_URL` split from `DATABASE_URL` so migrations own and the app does not | migration `33c56ebab859` · [`test_app_role_is_not_owner.py`](../backend/tests/isolation/test_app_role_is_not_owner.py) · [`test_every_tenant_table_has_policy.py`](../backend/tests/isolation/test_every_tenant_table_has_policy.py) |
| D25 | **Patients HTTP API**: 4 routes (`POST`, `GET`, `GET /{id}`, `PATCH /{id}`), deny-by-default, cross-tenant obscurity (`404`), server-side page size limit (25) | PR #29 · [`modules/patients/router.py`](../backend/app/modules/patients/router.py) · [`tests/patients/`](../backend/tests/patients/) |
| D26 | **Patients UI Screens**: Patients list view with server pagination, Add Patient dialog with submit validation, and individual Patient detail record screen | PR #30 · template `frontend/src/routes/_layout/patients.tsx` (removed by D33; now [`frontend/src/features/patients/`](../frontend/src/features/patients/)) |
| D27 | **RBAC Policy Layer & Catalog**: Schema for `roles`, `permissions`, `role_permissions`, `user_roles` with forced RLS; pure decision engine `can()` and `can_grant()` (R3); seed migration for 7 system roles and 19 permissions per tenant | PR #35 · migrations `f96bc0861b16`, `4d092676eafa`, `a1f2b3c4d5e6` · [`modules/users_roles/`](../backend/app/modules/users_roles/) |
| D28 | **Role Administration API**: 6 administrative routes (`GET /roles`, `GET /permissions`, `GET/POST /users/{id}/roles`, `GET /users/{id}/permissions`, `DELETE /users/{id}/roles/{role_id}`), rate limited at 20/min | PR #35 · [`modules/users_roles/router.py`](../backend/app/modules/users_roles/router.py) · [`tests/security/test_role_administration_authz.py`](../backend/tests/security/test_role_administration_authz.py) |
| D29 | **Admin UI Screens**: Roles & Permissions tab in navigation, interactive permissions bundle viewer, role assignment dialog, and role revocation | PR #36 · template `frontend/src/components/Admin/` (removed by D33; now [`frontend/src/features/admin/`](../frontend/src/features/admin/)) |
| D30 | **Playwright Test Sharding & Stability**: Bound shard runtimes and diagnostic artifact capture in CI workflows | PR #37 · [`.github/workflows/playwright.yml`](../.github/workflows/playwright.yml) |
| D31 | **RBAC Last Administrator Rule (R8)**: Revoking a role refuses with `403 LAST_ADMINISTRATOR` when it would leave a tenant with zero administrators | PR #38 · [`modules/users_roles/service.py`](../backend/app/modules/users_roles/service.py) |
| D32 | **Session Auth 401 vs 403 Separation**: Only unauthenticated `401` triggers a sign-out; `403 Forbidden` routes to a dedicated access-denied state without destroying the user's session | PR #39 · template `frontend/src/client/core/request.ts` (removed by D33; the same rule is [`frontend/src/lib/http.ts`](../frontend/src/lib/http.ts)) |
| D33 | **One frontend**: `frontend-features/` is the only app, built into the backend image and served at `/`; the template UI in `frontend/` is deleted, and deploy, Docker, Playwright CI, compose, SDK generation and pre-commit all point at the new app (the app directory was renamed to `frontend/` on 2026-10-07, D34) | [ADR-F005](../docs2/adr/ADR-F005-one-app-served-by-the-backend.md) |
| D35 | **Milestone 1 defects**: every response sends `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, `no-referrer` and HSTS; rate limits keyed per session as the design says (per address without one); `GET /tenants/current` moved to the 300/min read class; signup limited at 20/min; the self-permissions path settled as `GET /users/me/permissions` | [`security_headers.py`](../backend/app/core/security_headers.py) · [`rate_limit.py`](../backend/app/core/rate_limit.py) · [`test_security_headers.py`](../backend/tests/security/test_security_headers.py) · [`test_rate_limit_keys.py`](../backend/tests/security/test_rate_limit_keys.py) |
| D34 | **App directory renamed**: `frontend-features/` is now `frontend/` (workspace package `frontend`); every build, CI, compose, hook and doc path follows. Run guide: [`HOW_TO_RUN.md`](../HOW_TO_RUN.md) | [ADR-F005 addendum](../docs2/adr/ADR-F005-one-app-served-by-the-backend.md#addendum-2026-10-07-the-app-directory-is-frontend) |

---

### 🔄 In progress

**Nothing.** The working tree on `main` is clean.

---

### ⏭ Next Steps — in priority order

> 📋 **Complete Backlog**: For the exhaustive, task-by-task inventory across all 186 delivery tasks, 17 feature specifications, 7 security gates, and 6 invariants, refer to [`docs/to-be-completed.md`](to-be-completed.md).

Ordered into two parallel streams: **Pre-Production Hardening** (addressing known security/integrity gaps) followed by the **Clinical Regulatory Milestones**.

#### Stream 1: Pre-Production Hardening (Immediate)

| # | Step | Why it is next | Owner |
|:---:|---|---|---|
| **P1** | **Enforce Tenant Status in Auth (`get_actor`)** | Requirement R10: A `SUSPENDED` tenant must be refused on every request. Currently, suspended clinic users can still query patient records. | Backend Lead |
| **P2** | **Shorten Access Token Expiration & Protect Password Reset** | Control 1 mandates 15-minute access tokens; current setting is 8 days (`config.py`). `POST /api/v1/reset-password/` currently lacks rate limiting. | Security Lead |
| **P3** | **Atomic Organization Registration** | `register_user` runs across 4 separate database transactions. If role seeding fails, the user is left half-provisioned with 0 roles and locked out. Needs single-transaction atomicity and slug retry. | Backend Lead |
| **P4** | **Safe User Deactivation (No Hard Deletes)** | Requirement R11: `DELETE /api/v1/users/{id}` currently calls hard `session.delete(user)`, triggering foreign key crashes on `user_roles` and destroying audit attribution. Replace with `user.is_active = False`. | Backend Lead |
| **P5** | **Activate `clinos_app` in Production** | PostgreSQL RLS is bypassed in production because `DATABASE_URL` connects as `neondb_owner` (`rolbypassrls = true`). Grant `clinos_app` `INSERT ON tenants` and `SELECT ON user.hashed_password`, then switch connection. | Infra / DevOps |

#### Stream 2: Clinical Regulatory Milestones

| # | Step | Why it is next | Milestone |
|:---:|---|---|---|
| **N1** | **Append-Only Audit Trail (Feature 04)** | Invariant INV-4 and Control 6: Append-only `audit_log` table with SHA-256 hash chaining, writer facade, and immutable compliance export. Needed by clinical reads. | Gate 2 |
| **N2** | **TGA Approvals Engine (Feature 08)** | Invariant INV-2: Store SAS-B and Authorised Prescriber approvals at the grain (`patient_id` + `category` + `dosage_form` + `validity_window`) with a GiST exclusion constraint on active intervals. | Gate 4 · M2 |
| **N3** | **Prescription Safety Gate (Feature 10)** | The hard clinical constraint: script dispensing refused (`BLOCKED`) without an active, matching TGA approval. Negative decision matrix and audit emission. | Gate 5 · M3 |

---

### ⏸ Blocked — cannot start

| Item | Blocked by |
|---|---|
| Feature 02: MFA, sessions, step-up | **D-003** (identity), undecided |
| Gate 3 sign-off | D-003 |
| Gate 6 and 7 evidence | **D-004** needs a record for the FastAPI Cloud + Neon choice |
| Gate 1 sign-off | D-003 and D-004 both |
| The `valid_to` boundary in the safety gate | **D-006**, awaiting the Clinical Safety Officer |

---

### ⬜ Not started

Features 06–07, 09, 11–16 · full OIDC provider integration · prescription safety gate · S3 Object Lock compliance export · CI security scanning (T0-13–T0-15).

---

### Where each area stands today

| Area | State | Evidence |
|---|---|---|
| `tenants` table | **Created**, plus an opt-in demo seed | migration `706856e36a80` |
| Tenant-scoped transaction helper | **Built** — `SET LOCAL`, fails closed without a tenant | [`backend/app/core/db.py`](../backend/app/core/db.py) |
| Row-level security | **Enforced in code, bypassed in cloud.** Tables `patients`, `roles`, `role_permissions`, `user_roles` carry forced RLS policies. Live enforcement requires switching from `neondb_owner` to `clinos_app` (P5). | [`test_every_tenant_table_has_policy.py`](../backend/tests/isolation/test_every_tenant_table_has_policy.py) |
| Patients domain (Feature 05) | **CRUD Built**: Table, RLS, 4 API endpoints, React screens. Identifier encryption and search deferred. | PR #28, #29, #30 |
| RBAC domain (Feature 03) | **Built**: 7 roles, 19 permissions, pure policy engine `can()`, 6 admin routes, Admin UI screens. | PR #35, #36, #38 |
| Audit log (Feature 04) | **Not started** | All domain routes note `Audit: deferred` |
| Authentication (Feature 02) | **Template only**, 8-day token lifetime, blocked by D-003 | [`D-003`](reference/decisions/D-003-identity-model.md) |
| Organisation self-registration | **Operational** — signup registers the clinic, creates the tenant, and makes the signer Practice Owner | `POST /api/v1/users/signup` |
| Rate limiting | **Built**: login and signup 20/min per address; password recovery and reset 5/min per address; administrative class 20/min and single-resource reads 300/min, per session (per address without one) | [`backend/app/core/rate_limit.py`](../backend/app/core/rate_limit.py) |
| Repository visibility | **Public** (owner confirmed 2026-10-07). History holds the template's `changethis` defaults, never a production secret; production secrets live in GitHub secrets and the FastAPI Cloud environment. Full-history gitleaks: three upstream-template false positives only | [`README.md`](README.md) "Security findings" |
| Database migrations | **15 migrations, head `a1f2b3c4d5e6`**, `alembic check` clean | `uv run alembic check` |
| Tests | **184 passing backend tests, 94%+ coverage**; Playwright E2E suites passing | `uv run pytest` · Playwright CI |
| Schema diagrams | **Generated and committed**; CI gates against drift | [`docs/reference/schema/`](reference/schema/README.md) |
| Deployment | FastAPI Cloud + Neon (`ap-southeast-2`), **automatic on merge to `main`**, gated on `/api/v1/health/ready/` | Green end-to-end |

---

## 2. What the API serves today

Twenty-two routes across public intake, probes, user management, patient records, and role administration:

| Method | Path | Auth | Protection / Tenant Scope |
|---|---|---|---|
| `POST` | `/api/v1/login/access-token` | Open | Rate-limited (20/min) |
| `POST` | `/api/v1/password-recovery/{email}` | Open | Rate-limited (5/min) |
| `POST` | `/api/v1/reset-password/` | Open | Rate-limited (shares the 5/min recovery window) |
| `POST` | `/api/v1/users/signup` | Open | Organisation registration; creates tenant & assigns Practice Owner; rate-limited (20/min). A taken email is answered `400`, which discloses that the address has an account: a recorded residual risk (see `register_user` in `backend/app/api/routes/users.py`) |
| `GET` | `/api/v1/utils/health-check/` | Open | Liveness probe (does not touch database) |
| `GET` | `/api/v1/health/ready/` | Open | Readiness probe (verifies database connectivity) |
| `POST` | `/api/v1/login/test-token` | Session | Validates token payload |
| `GET/POST` | `/api/v1/users/` | Session | Superuser only |
| `GET/PATCH/DELETE` | `/api/v1/users/me` | Session | Account profile management |
| `PATCH` | `/api/v1/users/me/password` | Session | Password update |
| `GET/PATCH/DELETE` | `/api/v1/users/{user_id}` | Session | User management (superuser) |
| `POST` | `/api/v1/utils/test-email/` | Session | SMTP diagnostic |
| `POST` | `/api/v1/patients` | Session | `patient:create` · Tenant resolved from session |
| `GET` | `/api/v1/patients` | Session | `patient:read` · Server-side limit 25 · Tenant scoped |
| `GET` | `/api/v1/patients/{patient_id}` | Session | `patient:read` · Cross-tenant returns `404` |
| `PATCH` | `/api/v1/patients/{patient_id}` | Session | `patient:update` · Cross-tenant returns `404` |
| `GET` | `/api/v1/roles` | Session | `users:manage` · Rate-limited (20/min) · Tenant scoped |
| `GET` | `/api/v1/permissions` | Session | `users:manage` · Rate-limited (20/min) · Global reference |
| `GET` | `/api/v1/users/{user_id}/roles` | Session | `users:manage` · Rate-limited (20/min) · Tenant scoped |
| `GET` | `/api/v1/users/{user_id}/permissions` | Session | `users:manage` · Rate-limited (20/min) · Computed server-side |
| `POST` | `/api/v1/users/{user_id}/roles` | Session | `users:manage` · R3 grantability rule · Idempotent grant |
| `DELETE` | `/api/v1/users/{user_id}/roles/{role_id}` | Session | `users:manage` · R8 last admin rule · Scoped revocation |

---

## 3. Verified Metrics Summary

* **Backend Test Suite**: **184 passing tests** (`tests/api/`, `tests/core/`, `tests/isolation/`, `tests/patients/`, `tests/rbac/`, `tests/security/`, `tests/tenancy/`).
* **Code Quality**: `ruff` passing 0 errors, `mypy` strict mode passing on all source files.
* **Database Schema**: 15 Alembic migrations, 0 autogenerate drift (`alembic check` clean).
* **Data Residency**: AWS Sydney (`ap-southeast-2`) on Neon PostgreSQL (**INV-6**).
