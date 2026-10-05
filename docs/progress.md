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

## 1. Status at a glance — 2026-10-05

| Area | State | Evidence |
|---|---|---|
| ClinicOS domain features (01–16) | **Not started** — no domain endpoint exists | [`§2`](#2-what-the-api-serves-today) |
| `tenants` table | **Created**, plus an opt-in demo seed | migration `706856e36a80` |
| Tenant-scoped transaction helper | **Built** — `SET LOCAL`, fails closed without a tenant | [`backend/app/core/db.py`](../backend/app/core/db.py) |
| Row-level security | **Not implemented.** `tenants` is global by design; the first forced policy lands with the first tenant-scoped table | [`03-design.md`](features/01-tenancy-and-clinics/03-design.md) |
| Audit log (feature 04) | **Not started** | — |
| Authentication (feature 02) | **Template only**, and blocked by D-003 | [`D-003`](reference/decisions/D-003-identity-model.md) |
| Self-registration | **Closed by default** | `USERS_OPEN_REGISTRATION` |
| Rate limiting | **Built** for login (20/min) and password recovery (5/min) | [`backend/app/core/rate_limit.py`](../backend/app/core/rate_limit.py) |
| Database migrations | 8, head `89d27ee38a6f`, `alembic check` clean | `uv run alembic check` |
| Tests | **73 passing, 93% coverage** | `uv run pytest` |
| CI | 15 checks green: backend, compose, 4 Playwright shards, pre-commit, zizmor, coverage | PR #15 |
| Gate 1–7 | **None passed, none signed.** No evidence bundle exists | [`gates.md`](reference/gates.md) |
| Deployment | FastAPI Cloud + Neon (`ap-southeast-2`); **behind `main`** | [`§6`](#6-known-gaps-and-risks) |

---

## 2. What the API serves today

Eleven routes. Four are unauthenticated:

| Method | Path | Auth |
|---|---|---|
| `POST` | `/api/v1/login/access-token` | open — rate limited |
| `POST` | `/api/v1/password-recovery/{email}` | open — rate limited |
| `POST` | `/api/v1/reset-password/` | open — **not rate limited** |
| `POST` | `/api/v1/users/signup` | open — **refuses with 403 unless `USERS_OPEN_REGISTRATION`** |
| `GET` | `/api/v1/utils/health-check/` | open |
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

Five pull requests, all merged. Each is a measured step, not a feature.

| PR | Change |
|---|---|
| #11 | `.env` untracked, `.gitignore`d, `.env.example` added; control 8's live violation closed |
| #12 | `AGENTS.md`; the tenant transaction helper; `tenants` table, migration and seed; a pytest guard that refuses a non-local database |
| #13 | One constraint naming convention and one model registry; `updated_at` actually maintained; the demo seed made opt-in; `private` route removed |
| #14 | Self-registration closed by default; the signup page removed |
| #15 | The `item` domain dropped; rate limiting on login and recovery; the recovery HTML oracle removed |

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

- **The deployment is behind `main`.** Verified against the live OpenAPI document: it still serves
  `/api/v1/items/*` and `/api/v1/password-recovery-html-content/*`. It therefore also **does not have
  rate limiting**, which means login is currently unlimited on the public URL.
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

## 7. What would move this furthest, next

The MVP demonstration slice, in this order — each step is small and ends in something showable:

1. **Patients** — the first tenant-scoped table. It brings the first forced RLS policy, which is the
   point at which INV-1 stops being an intention ([`05-patients`](features/05-patients/01-requirements.md)).
2. **TGA approvals** — manual entry of an approval with its validity window.
3. **The prescription safety gate** — dispatch refused without an `ACTIVE` approval at the grain. This is
   INV-2, and it is the screen that demonstrates the product's hard constraint.
4. **Redeploy**, so the hardening already merged (#13–#15) is what the public URL is actually running.

Deliberately excluded until after that: RBAC (feature 03), MFA and OIDC (feature 02, pending D-003),
audit-log completeness (feature 04), reporting, integrations, and the gate sign-offs.

---

## 8. How this document stays honest

- **Every claim names an artefact.** A command, a migration, a file, or a signed record. An artefact that
  does not link to what it proves is not evidence (`README.md`).
- **"Not started" is a status.** It is written here rather than left blank.
- **Update it in the same change** that changes a status. A stale progress document is worse than none,
  because it is believed.
