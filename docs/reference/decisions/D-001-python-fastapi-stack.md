# D-001: Backend is Python 3.14 + FastAPI, not Node + TypeScript

- **Status:** Accepted
- **Date:** 2026-10-04
- **Owner:** CTO
- **Source contract reference:** `01-system-architecture.md` §8 "Technology choices"; `21-technical-design.md` §7; `02-security-architecture.md` §1 control 4

## Context

The source contract specifies a single-language stack: **Node + strict TypeScript** for the backend, with
**Zod** schemas for input validation, and a `packages/shared` workspace so that the frontend and backend
share types. It rejects "polyglot microservices" and gives one rationale: *"same type system as the
frontend; modules in-process."*

This repo is `fastapi-full-stack-template`. It has already committed to Python:

- `backend/pyproject.toml` — `requires-python = ">=3.14,<4.0"`, `fastapi[standard]>=0.141.1`,
  `pydantic>2.0`, `sqlmodel>=0.0.39`, `psycopg[binary]>=3.3.6`, `alembic>=1.19.1`, `pyjwt>=2.15.0`,
  `pwdlib[argon2,bcrypt]>=0.3.1`
- `backend/app/` — a working FastAPI application with `core/config.py` (pydantic-settings),
  `core/db.py`, `api/routes/*`, and five Alembic migrations
- `frontend/` — React 19 + Vite + TanStack, consuming the FastAPI OpenAPI schema via `openapi-ts`
  (`bun run generate-client`)

There is no TypeScript backend and no `apps/backend`. Replacing the backend would discard a working
`mypy --strict` + `ruff` + `pytest` toolchain and the existing frontend client-generation pipeline.

## Decision

**Keep the Python backend.** Build the ClinicOS modules in FastAPI, and re-express each source-contract
control against this stack.

| Source contract | Here | Control preserved? |
|---|---|---|
| Node + strict TypeScript | Python 3.14 + FastAPI, `mypy --strict` | Type safety preserved; enforced by `mypy` rather than `tsc` |
| Zod schemas | Pydantic v2 models in `modules/<module>/schemas.py` | Unknown fields rejected; strict types preserved |
| `packages/shared` shared types | `frontend/openapi-ts.config.ts` generating the client from FastAPI's OpenAPI schema | Single source of truth preserved, generated rather than authored |
| ESLint + typecheck stage | `ruff check` + `uv run mypy app` | Same stage, same position in the pipeline |
| `*.spec.ts` pytest-equivalent evidence names | `backend/tests/**/test_*.py` | Same test, mapped name — see [gates.md](../gates.md#artefact-naming-source-contract--this-repo) |
| Node worker container | A second FastAPI entrypoint in the same package (see D-002) | Same "one codebase, two entrypoints" model |
| TypeScript service facades between modules | Python module facades in `modules/<id>/service.py` | Same in-process boundary discipline |

`sqlmodel` is used as the ORM because it is already a dependency and it is the stack's idiomatic choice;
raw SQLAlchemy is used where SQLModel lacks a feature (for example RLS policy DDL and the GiST exclusion
constraint, which are Alembic raw-SQL migrations either way).

## Consequences

**Easier:** the existing toolchain, migrations and frontend client generation all keep working. Python is
where the team's RLS/Alembic work already sits.

**Harder:** the source contract's TypeScript code examples and artefact names are not runnable here.
Every task list in this phase set therefore states the Python artefact it expects, and
[gates.md](../gates.md) carries the naming map. Frontend/backend type sharing is now **generated**
(OpenAPI) rather than shared at the language level, so a contract test on the generated client is required
where the source relied on the compiler.

**Evidence substitution:** `tsc --noEmit` in CI becomes `uv run mypy app` in the same pipeline position.
Both fail the build on a type error. The Gate 1 check "the CI security pipeline stages and their order are
defined" is satisfied with `lint → typecheck → unit → integration → security → SAST → dependency →
container → secret → build → deploy`, which is the source's order with the stage names this repo uses.

## Effect on the gates

No gate is blocked. No control is dropped. Gate 1's evidence now cites Python artefacts.

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | Confirm that OpenAPI-generated client types are treated as a release artefact, with the parity test required by frontend security requirement 6 | Frontend Lead |
| 2 | Confirm `mypy --strict` covers `modules/**` and that `alembic/` stays excluded (it is excluded in `backend/pyproject.toml` today) | CTO |
