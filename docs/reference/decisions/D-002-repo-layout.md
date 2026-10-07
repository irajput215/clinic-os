# D-002: Layout is `backend/` + `frontend-features/` + `packages/`, not `apps/*`

- **Status:** Accepted
- **Date:** 2026-10-04
- **Owner:** CTO
- **Amended:** 2026-10-06. The frontend workspace is `frontend-features/`; the template's `frontend/`
  was deleted when the backend began serving `frontend-features/` at `/`
  ([ADR-F005](../../../docs2/adr/ADR-F005-one-app-served-by-the-backend.md)). The layout decision is
  unchanged: one bun workspace member for the frontend, beside `backend/` and `packages/`.
- **Source contract reference:** `23-sprint-plan.md` §2 "Repository architecture" — *"Monorepo layout: `apps/frontend`, `apps/backend`, `apps/worker`, `packages/shared`; strict TypeScript project references"*

## Context

The source contract's pre-sprint workstream specifies a monorepo with four top-level workspaces:
`apps/frontend`, `apps/backend`, `apps/worker`, `packages/shared`.

This repo has a different, already-working shape:

```
ozbrands/
├── backend/            → uv workspace member; FastAPI app in backend/app/
│   ├── app/            → main.py, api/, core/, alembic/, models.py
│   ├── tests/
│   └── pyproject.toml
├── frontend-features/  → bun workspace member; React + Vite (was frontend/ until 2026-10-06)
│   ├── src/, tests/, playwright.config.ts, openapi-ts.config.ts
│   └── package.json
├── packages/           → bun workspaces target (declared in root package.json)
├── hooks/, scripts/, img/
├── compose.yml, compose.override.yml, compose.deploy.yml
└── pyproject.toml      → uv workspace root, members = ["backend"]
```

Root `package.json` declares `workspaces: ["frontend-features", "packages/*"]`; root `pyproject.toml` declares
`[tool.uv.workspace] members = ["backend"]`.

Renaming to `apps/*` would break `compose*.yml` paths, the uv workspace membership, the bun workspace
membership, the `openapi-ts` output path, Dockerfiles, and the existing CI workflow — for a cosmetic gain.

## Decision

**Keep the current top-level layout.** Map the source contract's four workspaces onto it:

| Source contract workspace | Here | Notes |
|---|---|---|
| `apps/backend` | `backend/` | uv workspace member |
| `apps/frontend` | `frontend-features/` | bun workspace member |
| `apps/worker` | `backend/app/worker/` — a second entrypoint in the same Python package | Same codebase, different entrypoint, as the source contract itself specifies: *"The backend and worker are the same codebase with different entrypoints"* (`21-technical-design.md` §8) |
| `packages/shared` | `packages/` | Add `packages/shared/` when the first genuinely shared artefact appears |

Internal module layout inside `backend/app/` follows the source's module map:

```
backend/app/
├── main.py                  → app construction, lifespan
├── api/main.py              → router registration only
├── api/routes/              → thin HTTP layer
├── core/
│   ├── config.py            → pydantic-settings; fail closed on missing required config
│   ├── db.py                → engine, session, tenant-scoped transaction helper
│   ├── security.py          → token verification, central permission enforcement
│   └── audit.py             → append-only same-transaction event writer
├── modules/<module_id>/     → models.py, schemas.py, service.py, router.py
├── worker/                  → queue consumers, scheduled jobs (second entrypoint)
└── alembic/versions/        → one migration per schema change
```

Modules communicate **in-process through service facades**. A module owns its tables and is not imported
by another module's internals — the same boundary the source contract enforces with TypeScript facades.

## Consequences

**Easier:** nothing existing breaks. The worker as a second entrypoint matches the source's own model and
avoids a duplicated codebase.

**Harder:** no per-workspace TypeScript project references to enforce import boundaries. The equivalent
enforcement must be an **import lint** — a check that a module does not import another module's `models`
or internals directly.

**Phase assignment for the import lint (resolves the conflict raised as Phase 0 open item P0-5).** The
lint has two halves and they land in different phases:

| Half | Phase | Why |
|---|---|---|
| The **lint configuration** and the module-map skeleton it protects (`backend/app/{core,modules,worker}/`, the service-facade rule) | **Phase 0** — repository architecture workstream | It is repository architecture, which is what Phase 0 exists to establish. Landing it later leaves module internals unguarded while modules are written |
| **Keeping it green** as each module lands, and adding a failing example to the evidence bundle | **Phase 1** onward | The lint can only report on modules that exist |

Do not treat this as a Phase 1-only task: an import lint introduced after the modules are written is a
retrofit, and the source contract got this guarantee for free from the compiler.

**Note:** the flat template files `backend/app/models.py` and `backend/app/crud.py` are template
scaffolding (`User`, `Item`). They are superseded by `modules/` and are removed in Phase 1, not migrated
in place.

## Effect on the gates

No gate is blocked. Gate 1's check *"the environment separation model is defined"* and the pre-sprint
exit criteria continue to be evidenced against this layout. The import-boundary lint is added to Gate 1
evidence because the source relied on the compiler for the same guarantee.

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | Confirm whether `packages/shared/` is needed at all, given types are generated from OpenAPI | Frontend Lead + CTO |
| 2 | Confirm the worker entrypoint's process model (separate container vs. same container, separate process) once D-004 is closed | Head of Platform |
