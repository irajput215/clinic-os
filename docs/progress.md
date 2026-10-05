---
doc_id: OZ-PROGRESS
title: Build progress against the contract
owner: CTO (interim: Ishu Rajput)
status: DRAFT — for review
last_reviewed: 2026-10-05
next_review: 2026-11-05
classification: RESTRICTED
repo_docs:
  - README.md
  - reference/build-contract.md
  - reference/gates.md
  - reference/decisions/README.md
---

# Build progress

One page answering three questions: **what is actually built**, **what is verified**, and **what the rest
of this set now says that is no longer true**.

[`README.md`](README.md) states that "nothing is implemented". That is no longer accurate — but it is not
far from accurate either. The domain is still empty: no feature is complete and no gate is signed.

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
| D18 | Readiness probe `GET /api/v1/health/ready/` — boolean only, never tenant-routed; liveness deliberately left independent of the database | this change |
| D19 | A deploy can no longer report success while the app is broken: the runtime `DATABASE_URL` is synced from the GitHub secret, and the workflow fails when the app does not report ready | this change |

### 🔄 In progress

**Nothing.** The working tree is clean and the next slice has not started. This row is empty on purpose.

### ⏭ Next — in this order

| # | Step | Why it is next |
|:---:|---|---|
| N1 | **Patients** — table, service, `POST`/`GET /api/v1/patients` | The first *tenant-scoped* table. It brings the first forced RLS policy, which is where INV-1 stops being an intention |
| N2 | **TGA approvals** — manual entry with a validity window | The gate in N3 needs an `ACTIVE` approval to exist |
| N3 | **The prescription safety gate** — dispatch refused without an approval at the grain | INV-2, and the screen that demonstrates the product's hard constraint |
| N4 | **Isolation tests** — two tenants, absence assertions | Proves N1's RLS rather than asserting it |
| N5 | **Verify the live deployment** — signup, login and the readiness probe | Deploys are automatic on merge to `main` (D19); this step is the check that the deploy that just ran actually serves, not a manual publish |

### ⏸ Blocked — cannot start

| Item | Blocked by |
|---|---|
| Feature 02: MFA, sessions, step-up | **D-003** (identity), undecided |
| Gate 3 sign-off | D-003 |
| Gate 6 and 7 evidence | **D-004** needs a record for the FastAPI Cloud + Neon choice |
| Gate 1 sign-off | D-003 and D-004 both |
| The `valid_to` boundary in the safety gate | **D-006**, awaiting the Clinical Safety Officer |

### ⬜ Not started

Features 01–16 as features (no feature is complete) · row-level security · the audit log · RBAC ·
reporting and exports · integrations · CI security scanning (T0-13–T0-15) · every gate's evidence
bundle · password recovery that can actually send mail.

### Where each area stands

| Area | State | Evidence |
|---|---|---|
| ClinicOS domain features (01–16) | **Not started** — no domain endpoint exists | [`§2`](#2-what-the-api-serves-today) |
| `tenants` table | **Created**, plus an opt-in demo seed | migration `706856e36a80` |
| Tenant-scoped transaction helper | **Built** — `SET LOCAL`, fails closed without a tenant | [`backend/app/core/db.py`](../backend/app/core/db.py) |
| Row-level security | **Not implemented.** `tenants` is global by design; the first forced policy lands with the first tenant-scoped table | [`03-design.md`](features/01-tenancy-and-clinics/03-design.md) |
| Audit log (feature 04) | **Not started** | — |
| Authentication (feature 02) | **Template only**, and blocked by D-003 | [`D-003`](reference/decisions/D-003-identity-model.md) |
| Self-registration | **Open** — one signup creates an organisation and its administrator (D17) | `USERS_OPEN_REGISTRATION` |
| Liveness vs readiness | **Separated.** Liveness answers without touching the database; readiness returns `503` when it cannot reach one | [`core/health.py`](../backend/app/core/health.py) |
| Rate limiting | **Built** for login (20/min) and password recovery (5/min) | [`backend/app/core/rate_limit.py`](../backend/app/core/rate_limit.py) |
| Database migrations | 9, head `0bc1f345552b`, `alembic check` clean | `uv run alembic check` |
| Tests | **83 passing, 94% coverage** | `uv run pytest` |
| CI | 15 checks green: backend, compose, 4 Playwright shards, pre-commit, zizmor, coverage | PR #15 |
| Gate 1–7 | **None passed, none signed.** No evidence bundle exists | [`gates.md`](reference/gates.md) |
| Deployment | FastAPI Cloud + Neon (`ap-southeast-2`), **automatic on merge to `main`**, and now **gated on the readiness probe** | D19 · [`§6`](#6-known-gaps-and-risks) |

---

## 2. What the API serves today

Twelve routes. Six are unauthenticated — more than the endpoint declaration standard's two permitted
*surfaces*, but they are exactly those two: public intake (login, recovery, signup) and the probes.

| Method | Path | Auth |
|---|---|---|
| `POST` | `/api/v1/login/access-token` | open — rate limited |
| `POST` | `/api/v1/password-recovery/{email}` | open — rate limited |
| `POST` | `/api/v1/reset-password/` | open — **not rate limited** |
| `POST` | `/api/v1/users/signup` | open — **refuses with 403 unless `USERS_OPEN_REGISTRATION`** (on by default since D17); creates the tenant |
| `GET` | `/api/v1/utils/health-check/` | open — liveness; does **not** touch the database |
| `GET` | `/api/v1/health/ready/` | open — readiness; `503` with a boolean body when the database is unreachable |
| `POST` | `/api/v1/login/test-token` | session |
| `GET/POST` | `/api/v1/users/` | session |
| `GET/PATCH/DELETE` | `/api/v1/users/me` | session |
| `PATCH` | `/api/v1/users/me/password` | session |
| `GET/PATCH/DELETE` | `/api/v1/users/{user_id}` | session |
| `POST` | `/api/v1/utils/test-email/` | session |

Removed from the template: `/api/v1/items/*` (the example domain), `/api/v1/private/users/`
(unauthenticated user creation) and `/api/v1/password-recovery-html-content/{email}` (an enumeration
oracle). `users` and `login` remain the template's, pending features 02 and 03.

---

## 3. What changed during 2026-10-04 → 05

Nine pull requests, all merged. Each is a measured step, not a feature.

| PR | Change |
|---|---|
| #11 | `.env` untracked, `.gitignore`d, `.env.example` added; control 8's live violation closed |
| #12 | `AGENTS.md`; the tenant transaction helper; `tenants` table, migration and seed; a pytest guard that refuses a non-local database |
| #13 | One constraint naming convention and one model registry; `updated_at` actually maintained; the demo seed made opt-in; `private` route removed |
| #14 | Self-registration closed by default; the signup page removed (reversed by #19) |
| #15 | The `item` domain dropped; rate limiting on login and recovery; the recovery HTML oracle removed |
| #16 | This board, and the index corrections it required |
| #17 | Branding work merged into the wrong base branch — recovered, not lost, as #18 |
| #18 | clinicOS branding ships for real; the auth forms validate on submit, not on blur |
| #19 | Signup restored as organisation registration; one signup creates one tenant and its administrator |
| this change | Readiness probe; the runtime `DATABASE_URL` synced from the GitHub secret; the deploy now fails when the app cannot serve |

Also in this window: six defects corrected in the document set itself ([`traceability.md`](reference/traceability.md),
[`control-matrix.md`](reference/control-matrix.md), [`definition-of-done.md`](reference/definition-of-done.md),
[`tasks/00`](tasks/00-phase-0-foundation.md), a dead anchor in [`gates.md`](reference/gates.md), and stale
labels in [`open-questions.md`](reference/open-questions.md)).

---

## 4. Where this document set is now wrong

A defect to raise, not a judgement call to make silently.

1. **[`build-contract.md` §12](reference/build-contract.md) "Verified baseline"** is dated 2026-10-04 and
   states that the routes are `users`, `items`, `login`, `private` and `utils`. `items` and `private` no
   longer exist and `tenants` does. The section needs re-verification, or to be marked as the historical
   starting point it now is.
2. **[`README.md`](README.md) status** — "Everything in this set is `DRAFT — for review`. Nothing is
   implemented." The first sentence holds; the second does not.
3. **Feature 01 is partially and unevenly built.** `tenants` exists with the documented column set, but
   `clinics` does not (OPEN-1), there is no RLS, no endpoint, and no grant — `clinos_app` does not exist
   (T1-11). Feature 01's status is *not started*, not *in progress*.
4. **[`open-questions.md`](reference/open-questions.md)** — the committed-`.env` finding is resolved by #11.
   D-003 and D-004 remain open.
5. **A probe has no home in the module map.** [`build-contract.md` §7](reference/build-contract.md) and
   [`control-matrix.md` §1.4](reference/control-matrix.md) name twelve target modules, none of which is an
   operations or observability module — yet
   [`16-operations-and-observability/03-design.md`](features/16-operations-and-observability/03-design.md)
   requires liveness and readiness probes, and `AGENTS.md` says no route may be added outside
   `app/modules/`. The probe was therefore placed in the thin HTTP layer (`app/api/routes/health.py`)
   beside the existing `utils` probe, with the decision in `app/core/health.py`. **This is a raised
   conflict, not a settled one**: either the module map gains an operations module, or the layout rule
   gains a stated exception for platform probes. The path itself
   (`/api/v1/health/ready/`) is OPEN in the design and is a repo choice.
6. **No `spec.md` declares the probe under the endpoint declaration standard.** The standard requires every
   endpoint to declare authentication, permission, tenant scope, ownership, input and output schema, audit,
   rate limit and errors. The probe's declaration is recorded in its module docstrings
   ([`health.py`](../backend/app/api/routes/health.py)) rather than in a phase spec, because no phase owns
   it. It needs either a spec home or an explicit exemption.

---

## 5. Decisions and blockers

| Item | State |
|---|---|
| **D-003** identity | 🔴 OPEN — blocks Gate 3 |
| **D-004** deployment target | 🔴 OPEN on paper, **decided in practice**: the application runs on FastAPI Cloud with a Neon database. Neither is one of D-004's three options, so this needs its own decision record and a statement of which Gate 6 checks it substitutes |
| **D-006** `valid_to` boundary | 🔴 OPEN — awaits the Clinical Safety Officer; a clinical safety parameter |
| **INV-6** data stays in Australia | **Partial evidence only**: the Neon database is in `ap-southeast-2`. There is no vendor register entry and no residency register |
| **Dependabot alerts** | Disabled on the repository — no vulnerability alerts, no security-update PRs |

---

## 6. Known gaps and risks

- **Deployment is automatic, and it was automatic and green throughout a total outage.** The Deploy
  workflow runs on push to `main`; the runs for #12–#19 all succeeded. Earlier in this window this
  document claimed the opposite ("merging does not deploy anything"), which was wrong — the workflow has
  existed since `d338605`. The true risk is worse than the one written down: **a green deploy proved
  nothing about whether the app worked.**
- **The deployed database credential had drifted from the one CI migrates with.** On 2026-10-05 the live
  app returned `500` for `POST /api/v1/users/signup` *and* `POST /api/v1/login/access-token` — every route
  that touches the database — while `GET /api/v1/utils/health-check/` returned `200 true`, because
  liveness never touched the database and nothing asked whether the app could serve. The cause was not
  code: `fastapi deploy` ships code only and never carries configuration, so FastAPI Cloud's
  `DATABASE_URL` held a credential Neon rejects (`password authentication failed for user 'neondb_owner'`)
  while the GitHub secret's credential migrated that same database successfully in the same run. D18 and
  D19 close both halves: the runtime value is now synced from the single GitHub secret, and the workflow
  fails when the readiness probe does not answer `200`. Also noted: that variable is stored in FastAPI
  Cloud as **non-secret**, so making it secret needs delete-and-recreate.
- **`POST /api/v1/reset-password/`** is unauthenticated and, unlike its siblings, not rate limited.
- **Password recovery cannot deliver mail** (`SMTP_HOST=localhost`), so it returns success and nothing
  arrives — a silent dead end.
- **Rate limiting is per process and keys on the ASGI client address.** Behind a proxy that does not
  rewrite it (uvicorn trusts `X-Forwarded-For` only from `--forwarded-allow-ips`), every request shares
  one bucket and the limit becomes global.
- **No security scanning in CI** (T0-13–T0-15): 0 occurrences of semgrep, trivy, gitleaks, bandit,
  pip-audit or codeql across the workflows.
- **The pre-commit workflow cannot push its own fixes** — its `pr-push` step fails with "did not issue an
  installation token", so a hook that reformats files turns the check red instead of committing.
- **The pre-untracking `.env` values remain in git history.** Rotation is a Phase 0 exit task and is not
  evidenced anywhere in this repo.
- **No gate has an evidence bundle**, and no sign-off record exists for Gates 1–7.

---

## 7. Why that order

[The board's Next column](#1-the-board) is the single home for what comes next. The reasoning behind it:

- **Patients first** because it is the first *tenant-scoped* table. Until one exists, INV-1 is a design
  statement; the moment one does, it carries a forced RLS policy and INV-1 becomes something a test can
  fail ([`05-patients`](features/05-patients/01-requirements.md)).
- **Approvals before prescribing** because the safety gate has nothing to check without an `ACTIVE`
  approval at the grain.
- **The gate before anything cosmetic** because it is the product's hard constraint, and the one screen
  that shows a clinic owner what the platform refuses to do.
- **Isolation tests with patients, not after them** because the RLS policy has to be proved in the same
  change, not by a later audit.

Deliberately excluded until after that: RBAC (feature 03), MFA and OIDC (feature 02, pending D-003),
audit-log completeness (feature 04), reporting, integrations, and the gate sign-offs.

---

## 8. How this document stays honest

- **Every claim names an artefact.** A command, a migration, a file, or a signed record. An artefact that
  does not link to what it proves is not evidence (`README.md`).
- **"Not started" is a status.** It is written here rather than left blank.
- **Update it in the same change** that changes a status. A stale progress document is worse than none,
  because it is believed.
