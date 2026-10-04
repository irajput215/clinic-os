---
doc_id: FEAT-FOUND-03
title: Foundations, design
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
next_review: 2026-11-04
related: 23-sprint-plan, 26-security-gates, 02-security-architecture
source:
  - clinic-os-secure-by-design/23-sprint-plan.md §2
  - clinic-os-secure-by-design/26-security-gates.md §2
  - clinic-os-secure-by-design/02-security-architecture.md §1 controls 8 and 11, §6, §7, §11
  - clinic-os-secure-by-design/21-technical-design.md §6, §7, §10
  - clinic-os-secure-by-design/28-aws-network-and-deployment.md §7, §8, §10
  - clinic-os-secure-by-design/25-adr/ADR-004-docker.md
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

## Services and images

Three images build from the one repository (`ADR-004` "Decision"). Rejected: a single container running
frontend, backend and worker, because it couples scaling and failure domains.

| Image | Entrypoint | Inbound |
| --- | --- | --- |
| `frontend` | static bundle behind the edge; no server-side secret, no `VITE_` secret (`29` §8.3) | via edge only |
| `backend` | `fastapi run` (uvicorn workers), serving `/api/v1`; health endpoint exists today | via edge / load balancer |
| `worker` | queue consumer, no HTTP listener, separate task role; second entrypoint in one package (D-002) | none |

**Repo reality — verified 2026-10-04.** Only `backend/Dockerfile` exists, and it builds the frontend
bundle **into** the backend image — no worker image, no standalone frontend image. `USER` is never set,
the base images (`python:3.14`, `oven/bun:1`) are floating tags, `readonlyRootFilesystem` is absent, and
all three environments resolve to one committed `.env` and one compose `db` service. R16–R25 are
therefore unimplemented, not merely unverified.

### Image hardening

| Requirement | Implementation | Source |
| --- | --- | --- |
| Multi-stage build | build stage with toolchain; runtime stage with runtime + prod dependencies only | `28` §7 |
| Minimal base, pinned by digest | distroless or equivalent; no floating tag; no shell where avoidable | `ADR-004` |
| Non-root | dedicated unprivileged user, `USER` set explicitly, container never runs as root | `28` §7 |
| Read-only root FS | `read_only: true` plus an explicit writable `tmpfs`; exceptions listed with a reason | `ADR-004` F2 |
| Pinned dependencies | `uv.lock` and `bun.lock` committed; install with `--frozen` | `28` §7 |
| Health checks | liveness and readiness endpoints, plus the compose/orchestrator probe | `28` §7 |
| Resource limits | CPU and memory limits per service; backend and worker separate profiles | `28` §7 |
| No secret in the image | no secret in a layer, build cache, build arg or Dockerfile; injected at runtime | control 8; `02` §6 |
| Build context | `.dockerignore` excludes `.git`, `.venv`, `node_modules`, build and test output, and any `.env` | `23-sprint-plan.md` §2 |

## Database privileges

Foundations creates no domain table. Its obligations are the **role model** every later table inherits,
plus the isolation guarantee later features depend on. The application connects as non-owner
`clinos_app` (`26-security-gates.md` §2 Gate 2).

```sql
-- Role model: the app role is not an owner and cannot bypass RLS
ALTER ROLE clinos_app NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;

-- Audit and event tables: append-only by grant
GRANT SELECT, INSERT ON audit_log TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app;

-- Clinical/event rows are never hard-deleted by the application
REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM clinos_app;
```

Any attempt to `UPDATE`, `DELETE` or `TRUNCATE` an append-only table through `clinos_app` raises
`42501 insufficient_privilege` (`05-data-and-audit.md`).

## Environment separation

**The rule.** Production never shares a database, bucket, key, secret, credential or API key with
Development or Staging (`28` §8). Today all three environments resolve to one committed `.env` and one
compose `db` service, so this table is a **model only** and cannot be verified while D-004 is open.

| Aspect | Development | Staging | Production |
| --- | --- | --- | --- |
| Isolation unit | separate account or VPC | separate account or VPC | separate account |
| Database | own instance, synthetic only | own instance, synthetic only | own instance, real data |
| Object storage | own buckets | own buckets | own buckets |
| Encryption keys | own keys | own keys | own keys |
| Secrets | own secret set | own secret set | own secret set |
| Provider credentials | sandbox | sandbox | production |
| Human access | standing developer access | time-boxed, reason required | none standing; just-in-time only |
| Data rule | synthetic only | synthetic only | real patient data |

## Fail-closed configuration

`backend/app/core/config.py` requires `SECRET_KEY`, `PROJECT_NAME`, `DATABASE_URL`,
`FIRST_SUPERUSER` and `FIRST_SUPERUSER_PASSWORD` (Pydantic raises when they are absent). The rule:

1. Configuration precedence is **process environment → secret store → fail closed**. No third fallback.
2. A missing required key **refuses startup** and **names the key**. It never defaults.
3. A placeholder value (`changethis`) refuses startup **in every environment**, and no environment
   variable may turn a security check off: the current `_check_default_secret` only warns when
   `FASTAPI_ENV == "development"`, which the tracked root `.env` sets, so the check passes while
   `SECRET_KEY=changethis` is live and permits JWT forgery.

## CI pipeline — fixed stage order

`lint → typecheck → unit → integration → security tests → SAST → dependency scan → container scan →
secret scan → build → deploy`.

`lint` = `ruff check` + the import-boundary lint. `typecheck` = `uv run mypy app`, the Python substitute
for the source's `tsc --noEmit` (D-001). SAST = Semgrep; dependency and container scan = Trivy; secret
scan = Gitleaks (`28` §10; `23-sprint-plan.md` §2). Any failure stops the pipeline and a Critical
finding blocks build and deploy. Reordering requires Security Lead + Head of Platform and never
removes a security stage.

## Deny-by-default request path

Every request, in order, with a decision available at each step:

1. **Authenticate** the session; deny when missing or expired.
2. **Resolve tenant** from the session, never from the body, header or query string.
3. **Set tenant context** with `SET LOCAL` inside the transaction.
4. **Check permission** in the central policy layer; deny when not granted.
5. **Validate** against a strict schema with unknown fields rejected, so mass assignment fails.
6. **Execute** inside the RLS-scoped transaction.
7. **Audit** the decision — including refusals — in the same transaction as the change.

Cross-tenant access returns `404`, never `403`. Any error resolving identity, tenant or authorisation
fails closed with the standard error shape from `02-security-architecture.md` §7, diagnostics in logs only.

## Failure behaviour

| Failure | Behaviour |
| --- | --- |
| Required configuration key missing, or the secret store unreachable at task start | startup refused; key named; no cached permissive fallback |
| Security stage fails, or a Critical finding is present | pipeline stops; later stages do not run; build, deploy and merge blocked |
| Audit write fails for an audited operation | the operation does not complete |
| Image health check fails | orchestrator replaces the task; deploy rolls back to the previous immutable tag |

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Where the secret-store interface boundary sits before D-004 fixes the store | Head of Platform | OPEN |
| Health endpoint authentication position under the endpoint declaration standard | Security Lead + Head of Platform | OPEN |
| Region pin and its evidence (INV-6 is currently unimplemented) | CTO + Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether the worker is a second container or a second process in the backend image | Head of Platform | OPEN |
