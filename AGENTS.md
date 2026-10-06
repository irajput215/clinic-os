# AGENTS.md — standing orders for this repository

## What this repository is

ozbrands (ClinicOS): a clinical prescribing platform — TGA approvals, the prescription safety gate,
e-prescribing and pharmacy dispatch. The backend is FastAPI + SQLModel + PostgreSQL; the frontend is
React + TanStack, built into the backend image.

**Current state: MVP.** `docs/` describes the *target* contract, not the code. The app is a FastAPI
template plus the first tenancy slice. Never assume a behaviour exists because a document specifies it —
check `backend/app/`.

Read [docs/README.md](docs/README.md) first. That file fixes the rest.

## Commands

```bash
# Backend (run from backend/)
uv sync                                   # install
uv run fastapi dev app/main.py            # dev server
uv run pytest                             # tests
uv run pytest tests/path::test_name       # one test
uv run ruff check . && uv run ruff format .
uv run mypy app                           # strict
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head

# Frontend: frontend-features/, the only app (run from the repo root; workspace scripts)
bun install && bun run dev                # :5174, proxies /api to the backend on :8000
bun run lint && bun run typecheck         # biome, tsc
bun run build                             # writes backend/app/frontend, served by the backend at /
bun run test                              # playwright; PLAYWRIGHT_BASE_URL=http://127.0.0.1:8000 for the served build
bash scripts/generate-client.sh           # regenerate the SDK from the backend OpenAPI

# Whole stack
docker compose up -d
```

`.env` is **not** committed. Run `cp .env.example .env` before anything that reads settings — CI does
exactly this. Rotate the placeholder values before deploying.

## Non-negotiables

The full statement is [docs/reference/build-contract.md](docs/reference/build-contract.md) §6 and §8.
These hold everywhere and are never traded for schedule:

- **Deny by default.** `DENY → EXPLICITLY AUTHORISE → AUDIT → VALIDATE → EXECUTE`. Never
  `ACCEPT → PROCESS → TRY TO SECURE LATER`.
- **The backend is the only security boundary** (INV-3). The frontend hides, disables and warns; it never
  decides.
- **Tenant identity is resolved, never supplied** (INV-1). A `tenant_id` from a body, header or query
  parameter is ignored and audited as a cross-tenant attempt.
- **No PHI in logs, metrics, traces or error responses** (INV-5). Never log a clinical request body, at
  any level, including in errors.
- **Audit in the same transaction as the change**, append-only, and a failed audit write fails the
  operation (INV-4).
- **Fail closed.** A missing tenant setting matches nothing, never everything.
- **`404`, not `403`, across a tenant boundary** — a `403` confirms the resource exists.
- **No secret** in source, image, log, client bundle or a committed `.env`.

## Boundaries

- **Always:** write the denial path before the success path; add the test the design names in the same
  change; run `ruff`, `mypy` and `pytest` before committing.
- **Ask first:** any schema change; any new dependency; any change to RLS, the tenant-setting helper or
  the permission matrix; any change to CI pipeline order; any new third-party data flow.
- **Never:** accept `tenant_id` from the client; commit `.env`; edit `clinic-os-secure-by-design/` (an
  external read-only input); ship a feature with an open High or Critical finding.

## Where things live

| Path | Owns |
|---|---|
| [`docs/features/`](docs/features/README.md) | The build unit: 17 folders × 7 documents. Normative for requirements, invariants and audit events |
| [`docs/tasks/`](docs/tasks/) | The ordered work breakdown, one file per delivery phase |
| [`docs/reference/`](docs/reference/) | Build contract, gates, Definition of Done, control matrix, open questions, decision records |
| [`.agents/skills/`](.agents/skills/) | Reusable workflows. Load the matching skill before doing the work it covers |

A conflict between layers is a defect to raise, not a judgement call: the feature document is normative
for requirements, the reference layer for gates and Definition of Done.

## Conventions that differ from the upstream template

- **Python 3.14.** `except A, B:` without parentheses is valid (PEP 758). It looks like a Python 2 syntax
  error to older tools and to Python 3.13 — it is correct here. Do not "fix" it.
- **Layout — one convention, no exceptions.** All new domain code lives in
  `backend/app/modules/<module_id>/{models,schemas,service,router}.py`. A module owns its tables and is
  reached only through its service facade. The template layer (`app/models.py`, `app/crud.py`,
  `app/api/routes/*.py`) is **legacy: frozen**. Do not add a model, service or route outside
  `app/modules/`, and do not extend the legacy layer.
- **Where models register.** Every table must be imported by `app/db_models.py` — the single place Alembic
  reads. Never import a model into `app/models.py` just to register it.
- **Constraint names.** `app.core.metadata` sets one naming convention. Declare check constraints with a
  suffix (`name="status"` renders as `ck_tenants_status`). Run `uv run alembic check` before committing a
  model change; it must report **no** operations.
- **Tenant transactions.** Use `app.core.db.tenant_transaction(...)` for any query against tenant data.
  It sets `app.tenant_id` with `SET LOCAL` inside the transaction and refuses to open without a tenant.
  Never use a session-level `SET`.
