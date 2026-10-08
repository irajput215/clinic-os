---
doc_id: OZ-REF-BUILD-CONTRACT
title: Build contract — invariants, controls, stack and verified baseline
owner: CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
source_of_truth: ../../../../clinic-os-secure-by-design   # external to this repository, read-only
---

# ozbrands SDLC Build Contract

This directory is the **repo-side build contract** for ozbrands (ClinicOS). It decomposes the external
secure-by-design document set into **delivery phases**, and each phase into a spec, a plan and a task
list. It is written to be read and approved phase by phase, then implemented phase by phase.

> **Engineering instruction, not legal advice.** Every regulatory statement here is a pointer to the
> cited instrument, not a legal conclusion. Items that depend on a regulator's view, a contract term we
> have not seen, or a fact we do not have are marked **REQUIRES LEGAL/REGULATORY VALIDATION** and carry
> a named owner. An engineering control is evidence that we engineered carefully; it is never proof of
> legal compliance.

---

## 1. What is authoritative

Two document sets exist and they can conflict. This is the resolution order:

| Rank | Source | Location | Role |
|:---:|---|---|---|
| 1 | **This repo's code and configuration** | `backend/`, `frontend/`, `compose*.yml` | What physically exists today |
| 2 | **Decisions logged in `decisions/`** | [`docs/reference/decisions/`](decisions/) | Where this phase set deliberately diverges from rank 3, and why |
| 3 | **The secure-by-design contract** | `clinic-os-secure-by-design/` — external, read-only, not version-controlled here | Normative for *controls, gates, invariants and regulatory obligations* |

Rank 3 is normative for **what must be true**. Rank 1 and 2 are normative for **how it is built here**.
Where rank 3 names a technology this repo does not use, the control is retained and the implementation
is re-expressed against the stack in section 2; that translation is recorded as a decision document,
never applied silently. See [`decisions/`](decisions/README.md).

**Known divergences from the source contract** (each has a decision record):

| Divergence | Source says | This repo does | Decision |
|---|---|---|---|
| Language and framework | Node + strict TypeScript, `apps/*` monorepo | Python 3.14 + FastAPI, `backend/app` flat package | [D-001](decisions/D-001-python-fastapi-stack.md) |
| Input validation | Zod, one schema per endpoint | Pydantic v2 models, one schema per endpoint | [D-001](decisions/D-001-python-fastapi-stack.md) |
| Repo layout | `apps/frontend`, `apps/backend`, `apps/worker`, `packages/shared` | `backend/`, `frontend/`, `packages/` | [D-002](decisions/D-002-repo-layout.md) |
| Identity | Managed OIDC provider; *"we store no password hash"* | Self-hosted `PyJWT` + `pwdlib[argon2]` password auth shipped by the template | [D-003](decisions/D-003-identity-model.md) — **OPEN** |
| Compute and infrastructure | ECS Fargate, RDS, S3, SQS, CloudFront+WAF, Terraform | `compose.yml` / `compose.deploy.yml` | [D-004](decisions/D-004-deployment-target.md) — **OPEN** |
| Route paths | Unversioned: `/patients`, `/tga-approvals`, `/prescriptions/{id}/dispatch` | `/api/v1/...` per `settings.API_V1_STR`; provider webhooks stay unversioned | [D-005](decisions/D-005-route-path-convention.md) |
| Approval grain enforcement | Doc 08 §4: a `UNIQUE` at the grain and *"an exclusion constraint is deliberately not used"* — contradicted by docs 04, 20, 23 and Gate 2 | Partial **GiST exclusion** on overlapping `ACTIVE` intervals, compatible with the supersede chain | [D-006](decisions/D-006-approval-grain-and-validity-boundary.md) |
| `valid_to` boundary | Doc 08 §5 inclusive; doc 04 §3.6 half-open | Half-open `[valid_from, valid_to)` **as an interim fail-safe** | [D-006](decisions/D-006-approval-grain-and-validity-boundary.md) — 🔴 **OPEN, Clinical Safety Officer** |

**Two of these are contradictions inside the source contract, not divergences from it** — the approval
grain mechanism and the `valid_to` boundary (D-006). The source cannot settle them, which means the
implementer settles them whether or not anyone writes it down. D-006 is a **clinical safety parameter**:
the interim position is the narrower validity window, because refusing a prescription on the final day of a
legitimate approval is an inconvenience, while dispensing outside an approval is a statutory breach.

---

## 2. The stack this contract is written against

Taken from `backend/pyproject.toml` and `frontend/package.json`.

| Layer | Choice | Version pin |
|---|---|---|
| Runtime | Python | `>=3.14,<4.0` |
| API | FastAPI | `>=0.141.1,<1.0.0` |
| Validation | Pydantic v2 | `>2.0` |
| ORM | SQLModel | `>=0.0.39,<1.0.0` |
| Driver | psycopg 3 (binary) | `>=3.3.6,<4.0.0` |
| Migrations | Alembic | `>=1.19.1,<2.0.0` |
| Tokens | PyJWT | `>=2.15.0,<3.0.0` |
| Password hashing | pwdlib (argon2 + bcrypt) | `>=0.3.1` |
| Config | pydantic-settings | `>=2.2.1,<3.0.0` |
| Errors/telemetry | sentry-sdk[fastapi] | `>=2.70.0,<3.0.0` |
| Test | pytest + coverage | `>=7.4.3,<10.0.0` |
| Lint/format | ruff | `>=0.2.2,<1.0.0` |
| Types | mypy `strict = true`, plus `ty` | `>=1.8.0,<3.0.0` |
| Frontend | React 19 + TanStack Router/Query/Table, Vite, Radix, Tailwind 4 | see `frontend/package.json` |
| Frontend lint | Biome | `biome check` |
| Frontend test | Playwright | `bunx playwright test` |
| Client generation | `openapi-ts` from the FastAPI OpenAPI schema | `bun run generate-client` |

**Consequence of D-001:** the source contract's TypeScript-specific evidence artefacts (for example
`authz.recomputes_server_side.spec.ts`, `Zod` schemas, ESLint pipeline stages) map to Python equivalents
(pytest module names, Pydantic models, ruff/mypy pipeline stages). The *control* is unchanged; only the
artefact name changes. Every task list in this phase set states the artefact it expects.

---

## 3. Phase, sprint, gate and milestone map

Five phases, taken from the source sprint plan and security gates. A phase closes only when its exit
gate is **signed**, not when the features demo.

| Phase | Features | Timeline | Scope | Gate(s) | Milestone | Tasks |
|---|---|---|---|---|---|---|
| **0. Foundation** | [00-foundations](../features/00-foundations/01-requirements.md) | Weeks 0–2 | Repo, Docker, environments, CI skeleton, baseline hygiene | Gate 1 *(evidence produced; signed at the Phase 1 boundary)* | — | [00](../tasks/00-phase-0-foundation.md) |
| **1. Foundations** | [01](../features/01-tenancy-and-clinics/01-requirements.md) – [07](../features/07-documents/01-requirements.md) | Sprint 1, weeks 3–4 | Schema, RLS, identity, RBAC, patient register, audit foundation, isolation suite | **Gate 1** · **Gate 2** · **Gate 3** | **M1** | [01](../tasks/01-phase-1-foundations.md) |
| **2. TGA engine** | [08](../features/08-tga-approvals/01-requirements.md) – [09](../features/09-tga-inbox/01-requirements.md), [14](../features/14-reports-and-exports/01-requirements.md) | Sprint 2, weeks 5–6 | Approval register at the grain, manual entry, inbox ingestion, OCR, matching, human verification, reporting | **Gate 4** · **Gate 5** *(TGA boundary)* | **M2** | [02](../tasks/02-phase-2-tga-approval-engine.md) |
| **3. e-Prescribing** | [10](../features/10-prescription-safety-gate/01-requirements.md) – [13](../features/13-integration-boundaries/01-requirements.md) | Sprint 3, weeks 7–8 | Parchment adapter, prescription workflow, safety gate, dispatch queue, idempotency, webhooks, reconciliation | **Gate 5** *(Parchment)* · **Gate 6** *(preparation)* | **M3** | [03](../tasks/03-phase-3-eprescribing.md) |
| **4. Pilot go-live** | [15](../features/15-admin-and-config/01-requirements.md) – [16](../features/16-operations-and-observability/01-requirements.md) | M4, after Sprint 3 | Production readiness, penetration test, restore drill, training, manual fallback | **Gate 6** · **Gate 7** | **M4** | [04](../tasks/04-phase-4-pilot-go-live.md) |

```
 weeks 0-2         weeks 3-4            weeks 5-6             weeks 7-8           after S3
┌───────────┐    ┌───────────┐        ┌───────────┐         ┌───────────┐       ┌───────────┐
│ Phase 0   │───>│ Phase 1   │───────>│ Phase 2   │────────>│ Phase 3   │──────>│ Phase 4   │
│ foundation│    │ foundns   │        │ TGA engine│         │ e-prescri-│       │ pilot     │
└───────────┘    └─────┬─────┘        └─────┬─────┘         └─────┬─────┘       └─────┬─────┘
                       │                    │                     │                   │
                       v                    v                     v                   v
                Gate 1 Architecture    Gate 4 APIs           Gate 5 Parchment    Gate 6 Prod
                Gate 2 Database        Gate 5 TGA            Gate 5 complete     Gate 7 Go-live
                Gate 3 AuthN
                M1                     M2                    M3                  M4
```

### The rule that makes the gates real

- **No self-approval.** The person who delivered the work never signs its gate.
- **A failed gate stops dependent work.** The gate is re-run; it is never carried forward as a
  background task.
- **Conditional passes are limited, named, expiring, and unavailable for two controls:** Gate 2
  (tenant isolation) and the prescription safety gate in Gate 4.
- **No feature is Done with an open High or Critical finding.**

Full checklists, evidence and approvers: [`docs/reference/gates.md`](gates.md).

---

## 4. How to read the build

The unit of build is the **feature folder** under [`docs/features/`](../features/), not the phase. Each
holds seven short documents, read in this order:

| File | Answers |
|---|---|
| `01-requirements.md` | What must this do, and how do we know it works? |
| `02-user-stories.md` | Who needs it and why? |
| `03-design.md` | How is it built? Tables, constraints, RLS, endpoints, failure behaviour |
| `04-threat-model.md` | What can go wrong? STRIDE with residual score and named owner |
| `05-data-and-audit.md` | How is data handled and what is recorded? |
| `06-test-plan.md` | How do we prove it? Exact pytest commands |
| `07-definition-of-done.md` | When is it finished, and who signs? |

The **ordered work breakdown** is [`docs/tasks/`](../tasks/) — one file per delivery phase, each task
carrying `Acceptance / Verify / Files / Controls / Evidence / Blocked by`. The phases above are a
*delivery* view over the feature set; the features are the build unit. Work a feature only after its
`01-requirements.md` is approved.

---

## 5. The six invariants

These hold everywhere and are never traded for schedule. Each has a named test.

| ID | Invariant | Proven by |
|---|---|---|
| **INV-1** | Tenant isolation holds even when the application forgets a filter | RLS policy on every tenant table + `test_rls_holds_without_app_filter` |
| **INV-2** | No prescription is dispatched without an `ACTIVE` TGA approval at the approval grain | `test_dispatch_blocks_without_active_approval` + negative dispatch matrix |
| **INV-3** | Enforcement is backend-only; the frontend hides and warns, never decides | `test_authz_recomputes_server_side` |
| **INV-4** | Audit is append-only; the application role cannot `UPDATE` or `DELETE` it | GRANT inspection test |
| **INV-5** | No PHI appears in logs, metrics, traces or error responses | Sentinel-value test + redaction unit tests |
| **INV-6** | Data stays in Australia; no production data leaves the approved region | Residency policy check + vendor register |

The source contract states INV-1…INV-6 for the whole platform. INV-2 is the clinical safety gate and is
specified in full in [`03-phase-3-eprescribing/spec.md`](../features/10-prescription-safety-gate/01-requirements.md).

---

## 6. The twelve controls every feature implements

From source doc 02. A feature that implements nine of twelve is not partially secure; it is a finding.
Each phase's `tasks.md` must cite the controls it advances.

| # | Control | Implementation here | Evidence artefact |
|:---:|---|---|---|
| 1 | Authentication | `PyJWT` verification of `iss`/`aud`/`exp`, MFA for clinical and administrative roles, 15-minute access tokens, refresh rotation, server-side revocation | Auth test module + IdP/session config export |
| 2 | Authorisation | Thin role bundles over granular permissions, one central policy layer, recomputed per request from identity + tenant + resource | `test_authz_recomputes_server_side` |
| 3 | Tenant isolation | `tenant_id NOT NULL` on every clinical table, RLS with `FORCE`, transaction-scoped `SET LOCAL app.tenant_id` | Isolation suite + migration lint |
| 4 | Input validation | One Pydantic schema per endpoint, unknown fields rejected, size and list limits | `test_validation_rejects_unknown_field` |
| 5 | Output validation | Response serialised through a declared schema, no raw ORM entity returned, field allow-list per role | `test_serialisation_omits_restricted_fields` |
| 6 | Audit logging | Append-only `audit_log` written in the same transaction, fixed envelope | `test_audit_writes_in_same_transaction` + GRANT test |
| 7 | Encryption | TLS 1.2+, HSTS, SSE-KMS at rest, envelope encryption for documents | KMS/TLS config review |
| 8 | Secrets management | Secrets from environment-injected secret store, rotation, no secret in image/log/repo, pre-commit + CI scanning | Secret scan report |
| 9 | Error handling | One error envelope, no diagnostics to the client, `request_id` correlation, fail closed | `test_errors_never_leak_internal_detail` |
| 10 | Abuse protection | Edge + per-endpoint + per-tenant rate limits, idempotency keys on writes, breached-credential check | Per-endpoint rate-limit tests |
| 11 | Security testing | SAST, SCA, secret scanning on every PR; isolation suite on every staging deploy; pen test before production | CI pipeline definition + scan reports |
| 12 | Compliance evidence | Every control names an evidence artefact and an owner | [`control-matrix.md`](control-matrix.md) |

### The request pipeline

Take this as the literal order of operations in every sensitive handler:

```
DENY BY DEFAULT
   → EXPLICITLY AUTHORISE   (permission, then tenant scope, then ownership/relationship)
   → AUDIT                  (intent event before the state change, same transaction)
   → VALIDATE               (input schema, domain invariants, resource state machine)
   → EXECUTE                (state change + resource event + audit event + outbox row, one transaction)
```

Never `ACCEPT → PROCESS → TRY TO SECURE LATER`.

**Hard prohibitions** carried from source doc 02:

- Do not log a request body from a clinical endpoint, at any log level, including in errors.
- Do not accept `tenant_id`, `actor_id` or `role` from a request body, header or query string.
- Do not put a token, a patient identifier or any PHI in a URL, a cache key or an analytics event.
- Do not string-interpolate into SQL, including identifiers.
- Do not return a raw ORM entity from a route.

### The seven classification levels

Classification is declared at schema level and drives storage, logging, encryption, access, export,
monitoring and retention. From source doc 12 — note **seven**, not six:

| Level | Meaning | Example |
|---|---|---|
| `PUBLIC` | No harm from disclosure | Published clinic hours |
| `INTERNAL` | Staff and contracted operators only | Runbooks, architecture diagrams |
| `CONFIDENTIAL` | Harms the organisation, a clinic or a commercial relationship | Tenant contract metadata, pricing |
| `SENSITIVE` | Harms an individual or clinic; not itself health information | Audit events, account metadata, payment references |
| `HEALTH_INFORMATION` | Health, health services or healthcare identifiers | DOB, address, Medicare number, IHI, allergy status |
| `HIGHLY_SENSITIVE` | Health information where disclosure risks serious harm, discrimination or stigma | Clinical note bodies, prescriptions and their payloads, TGA approval records, OCR extraction results |
| `SECRET` | Disclosure grants access or defeats a control | Password verifiers, MFA seeds, API and signing keys, DB credentials |

The ladder is a **containment ladder**: each level is a superset of the controls above it.

```
SECRET              no persistence in ClinicOS columns; no logs, analytics, telemetry or export
HIGHLY_SENSITIVE    no logs, analytics or telemetry; field-level encryption; named access; export gated
HEALTH_INFORMATION  pseudonymised application logs only; tenant + role access; export logged
SENSITIVE           audit-grade access; export logged; no bulk export without approval
CONFIDENTIAL        staff access; monitored
INTERNAL            staff access
PUBLIC              open
```

Two hard prohibitions outweigh any operational convenience:

1. **`SECRET` never appears in any log, application database column, frontend bundle or repository.**
   Credential verifiers are held by the identity provider; API keys live in the secret store and are
   referenced by ARN. A secret found in a log sink, bundle, image or Git object is an **incident**.
2. **`HIGHLY_SENSITIVE` never appears in a log, analytics pipeline or error telemetry** — not in a debug
   line, a stack trace, a request-body capture or a third-party crash report.

Whether a field is "personal information" or "sensitive information" for a specific clinic and
jurisdiction is a legal question, not an engineering one: **REQUIRES LEGAL/REGULATORY VALIDATION**.

---

## 7. Module map

Each module owns its tables and exposes a service facade. No module reaches into another module's
tables. The target layout under `backend/app/` is:

```
backend/app/
├── main.py                  → app construction and lifespan
├── api/
│   ├── main.py              → router registration only
│   └── routes/              → thin HTTP layer, one module per file
├── core/
│   ├── config.py            → pydantic-settings, fail-closed on missing config
│   ├── db.py                → engine, session, tenant-scoped transaction helper
│   ├── security.py          → token verification, permission enforcement
│   └── audit.py             → append-only event writer (same-transaction)
├── modules/<module_id>/     → models.py, schemas.py, service.py, router.py
└── alembic/versions/        → one migration per schema change
```

| Module id | Responsibility | Owned tables | Endpoints | Phase |
|---|---|---|---|:---:|
| `identity_tenancy` | Sessions, tokens, tenant resolution, permission evaluation | `tenants`, `refresh_tokens`, `integration_credentials_refs` | `/api/v1/auth/*`, `/api/v1/tenants/*` | 1 |
| `users_roles` | User lifecycle, role bundles, permission grants | `users`, `roles`, `permissions`, `role_permissions`, `user_roles` | `/api/v1/users/*`, `/api/v1/roles/*`, `/api/v1/permissions/*` | 1 |
| `patients` | Demographics, identifiers, consent, duplicate detection | `patients`, `consent_records` | `/api/v1/patients/*` | 1 |
| `clinical_records` | Versioned immutable notes and addenda | `clinical_records`, `clinical_record_versions` | `/api/v1/clinical-records/*` | 1 |
| `audit` | Append-only event write and read | `audit_log` | `/api/v1/audit/*` | 1 |
| `tga_approvals` | Approval grain, state machine, validity intervals | `tga_approvals`, `tga_approval_events` | `/api/v1/tga-approvals/*` | 2 |
| `tga_inbox` | Mailbox ingestion, extraction, human verification queue | `tga_inbox_messages`, `tga_inbox_attachments`, `tga_extraction_results` | `/api/v1/tga-inbox/*` | 2 |
| `reports` | Tenant-scoped reporting and exports | `report_runs`, `export_jobs` | `/api/v1/reports/*` | 2 |
| `prescribing` | Draft, validate, sign, submit, reconcile | `prescriptions`, `prescription_events`, `prescription_state_history` | `/api/v1/prescriptions/*` | 3 |
| `pharmacy` | Dispatch receipt and confirmation | `pharmacy_dispatches`, `dispatch_attempts`, `webhook_events` | `/api/v1/pharmacy/*` | 3 |
| `documents` | Upload, scan state, presigned URL minting | `documents` | `/api/v1/patients/{id}/documents/*` | 1 |
| `admin` | Tenant configuration, break-glass, retention operations | `feature_flags`, `configuration`, `retention_jobs` | `/api/v1/admin/*` | 4 |
| `appointments` | Practitioner roster, calendar bookings, public booking (added in Milestone 2, phase 2C; `docs2/sdlc/04-calendar-and-booking/api.md`) | `appointments`, `appointment_settings` | `/api/v1/practitioners`, `/api/v1/appointments/*`, `/api/v1/public/*` | M2 |
| `dashboard` | The Today page: one read composed from the `appointments`, `prescriptions` and `tga_approvals` facades (added in Milestone 2, phase 2E; `docs2/sdlc/08-today/api.md`) | none | `/api/v1/dashboard/today` | M2 |

**Legacy `/api/state` — NOT APPLICABLE HERE.** Section 12 records that `grep -rn "api/state" backend
frontend/src` returns nothing: this endpoint does not exist in this repository. The source contract's
freeze-and-strangle migration (source doc 21 §3) therefore describes a **predecessor prototype** and is out
of scope unless a legacy client is discovered. The Phase 1 workstream "State synchronisation" is
**de-scoped pending confirmation**. Recorded here only so a reader of the source contract does not go
looking for it; if a legacy client does appear, the rules apply — freeze the contract, add a compatibility
adapter that holds no business logic and never bypasses authorisation, tenant resolution or audit, dual-read
in staging, then remove.

---

## 8. Repo conventions inherited by every phase

### Commands

```bash
# Backend
cd backend
uv sync                                              # install
uv run fastapi dev app/main.py                       # dev server
uv run pytest                                        # tests
uv run pytest --cov=app --cov-report=term-missing     # coverage
uv run mypy app                                      # types (strict)
uv run ruff check . && uv run ruff format .           # lint + format
uv run alembic revision --autogenerate -m "message"   # new migration
uv run alembic upgrade head                           # apply migrations
uv run alembic downgrade -1                           # rollback one

# Frontend
cd frontend
bun install
bun run dev
bun run build
bun run lint                                          # biome
bun run test                                          # playwright
bun run generate-client                               # regenerate from OpenAPI

# Whole stack
docker compose up -d
```

### Boundaries

- **Always:** write the denial path before the success path; add the test named in the control's
  evidence column in the same change; run `ruff`, `mypy` and `pytest` before committing; keep the
  audit event in the same transaction as the state change.
- **Ask first:** any schema change; any new dependency; any change to RLS policy, the tenant-setting
  helper or the permission matrix; any change to CI pipeline order; any new third-party data flow.
- **Never:** accept `tenant_id` from the client; log a clinical request body; add a secret to source,
  image, `.env` committed to git, or a task definition; suppress a scanner finding without a recorded
  justification and expiry; edit `clinic-os-secure-by-design/` (it is an external read-only input);
  ship a feature with an open High or Critical finding.

**Schema changes** additionally follow [`database-conventions.md`](database-conventions.md): where the
four defining layers are, how relationships are declared, how `ondelete` is chosen, and which checks CI
must pass. That document also records what `alembic check` cannot see on its own.

### Test data

Synthetic only. No production data enters Development or Staging. Seeded fixtures carry a canary tenant
whose rows must never appear in another tenant's response — this is what the isolation suite asserts
*absence* against.

---

## 9. Document map

| Document | Purpose |
|---|---|
| [`docs/reference/gates.md`](gates.md) | Gates 1–7: purpose, entry criteria, checks, evidence, decision maker, conditional-pass rules, sign-off template |
| [`docs/reference/definition-of-done.md`](definition-of-done.md) | The six-part test, Definition of Ready, exception process, evidence storage |
| [`docs/reference/control-matrix.md`](control-matrix.md) | Requirement → source → control → implementation → evidence → owner → status |
| [`docs/reference/open-questions.md`](open-questions.md) | Every open item and every `REQUIRES LEGAL/REGULATORY VALIDATION` item, with an owner |
| [`docs/reference/traceability.md`](traceability.md) | Source document → this repo's document, and the reverse |
| [`docs/reference/decisions/`](decisions/README.md) | Decision records, including every divergence from the source contract |
| [`docs/features/`](../features/) | Per-feature specification layer: spec, threat model, data and audit, test plan |

---

## 10. Evidence discipline

Every substantive row in this set carries:

```text
Requirement      what must be true
Source           the primary instrument or the internal decision
Control          the engineering or operational control
Implementation   where it lives in the build
Evidence         what an auditor or a customer's security team would be shown
Owner            the single named accountable role
Status           implemented / in progress / planned / open
Last reviewed    date
```

An artefact that does not link to the control it proves is not evidence. A test name without its output
does not satisfy this. Where an item is not implemented, the status says so.

---

## 11. Change control

| Change | Who approves |
|---|---|
| A new document in this set | CTO |
| A change to a security control | CTO + Security Lead |
| A change to the tenant isolation model | CTO + Security Lead, plus a **Gate 2 re-run** |
| A change to the prescription safety gate | CTO + Clinical Safety Officer, plus a **Gate 4 re-run** |
| A change to a regulatory position | CTO + legal/regulatory adviser |
| Production deployment with an open High finding | Practice Owner + CTO, recorded in the risk register |
| A new divergence from the source contract | Recorded as a decision document in `docs/reference/decisions/` |

Substantive changes are recorded as a decision document or an update to
[`control-matrix.md`](control-matrix.md), not as an untracked edit.

---

## 12. Verified baseline — what does not exist yet

Recorded by direct inspection of this repository on 2026-10-04. This is the honest starting point, and it
is deliberately blunt: the source contract describes a build that **has not happened**, and pretending
otherwise is the failure mode this document set exists to prevent.

| Finding | Verification | Consequence |
|---|---|---|
| **No ClinicOS domain code exists.** | `backend/app/api/routes/` contains only `users.py`, `items.py`, `login.py`, `private.py`, `utils.py`; migrations are the template's `User`/`Item` models | Every module in section 7 is greenfield. Phases 1–4 are net-new code |
| **The repo is an unmodified `fastapi-full-stack-template`.** | Root `package.json` → `"name": "fastapi-full-stack-template"` | Template scaffolding (`models.py`, `crud.py`, `items.py`) is superseded and removed in Phase 1 |
| **The root `.env` is tracked in git.** | `git ls-files --error-unmatch .env` succeeds; `.gitignore` does not exclude it | **Live violation of control 8.** Holds `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD`, all at the template default `changethis`. `SECRET_KEY=changethis` signs JWTs, so deploying as-is permits token forgery. Phase 0 exit task: untrack, gitignore, ship `.env.example`, rotate |
| **CI has no security scanning at all.** | Across all 15 files in `.github/workflows/`: semgrep 0, trivy 0, gitleaks 0, bandit 0, pip-audit 0, safety 0, codeql 0 | Control 11 is unimplemented and Gate 1's "CI security pipeline stages are defined" check **fails**. Phase 0 must create it, not just document it |
| **What CI does have.** | `test-backend.yml`, `test-docker-compose.yml`, `playwright.yml`, `pre-commit.yml`, `zizmor.yml`, `deploy.yml`, `deploy-docker-compose.yml`, plus housekeeping | Test and hygiene stages exist; `.pre-commit-config.yaml` runs ruff check/format, mypy, ty, biome, typos, zizmor — code hygiene and GitHub Actions linting, **no SAST/SCA/secret scanning** |
| **`/api/state` does not exist.** | `grep -rn "api/state" backend frontend/src` returns nothing | The source's `/api/state` freeze-and-strangle migration (source doc 21 §3, technical risks T3 and T9) describes a **predecessor prototype**. It is out of scope unless a legacy client is discovered; the Phase 1 workstream "State synchronisation" is de-scoped pending confirmation |
| **No region pin.** | No Terraform, no AWS resource definitions, no `ap-southeast-2` reference anywhere | **INV-6 is not true or false — it is unimplemented.** A Gate 1 and Gate 6 gap (D-004) |

Two of these are **security findings, not documentation gaps**: the tracked `.env` and the absent scanning
pipeline. They are the first tasks in Phase 0 for that reason.

---

## Open items and assumptions

| # | Item | Owner role |
|---|---|---|
| O1 | Confirm whether identity stays self-hosted or moves to a managed OIDC provider (D-003) | CTO + Security Lead |
| O2 | Confirm the deployment target: compose on a single host, or the source contract's ECS/RDS/S3/SQS (D-004) | CTO + Head of Platform |
| O3 | ~~Confirm whether `/api/state` exists in this codebase~~ **RESOLVED 2026-10-04: it does not exist.** See section 12. The source's strangler migration is out of scope unless a legacy client is found, and the Phase 1 "State synchronisation" workstream is de-scoped pending confirmation. | Head of Product |
| O4 | Confirm measured velocity after Phase 1; the source's 40 points/sprint is an assumption, not a measurement | Delivery Lead |
| O5 | Name the legal and privacy adviser who answers `open-questions.md` | Practice Owner |
| O6 | Confirm the region decision (the stack is not yet pinned to `ap-southeast-2`) | CTO + Compliance Lead |

## Sources

- `clinic-os-secure-by-design/00-README.md` — document set rules: deny by default, backend-only enforcement, evidence discipline
- `clinic-os-secure-by-design/02-security-architecture.md` — the twelve controls, request pipeline, error contract, rate limits
- `clinic-os-secure-by-design/21-technical-design.md` — architecture, tenant isolation, API standard, module map
- `clinic-os-secure-by-design/23-sprint-plan.md` — sprint scope, exit criteria, dependency table
- `clinic-os-secure-by-design/24-definition-of-done.md` — the six-part test
- `clinic-os-secure-by-design/26-security-gates.md` — Gates 1–7
- `backend/pyproject.toml`, `frontend/package.json` — the stack this contract is written against
