---
doc_id: OZ-SDLC-P0-TASKS
title: "Phase 0 — Foundation: tasks"
owner: Delivery Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
phase: "0 — Foundation (pre-sprint)"
gate: "Gate 1 — Architecture (evidence produced here; signed at the Phase 1 boundary)"
source: "clinic-os-secure-by-design/23-sprint-plan.md §2, §6, §7; clinic-os-secure-by-design/26-security-gates.md §2; clinic-os-secure-by-design/02-security-architecture.md §1, §6; clinic-os-secure-by-design/28-aws-network-and-deployment.md §7, §8, §10; clinic-os-secure-by-design/25-adr/ADR-004-docker.md"
---

> **The phase specification this list was written against has been superseded** by the numbered feature folders under [`../features/`](../features/). Requirements, design, threats, data handling, tests and the Definition of Done now live there, one folder per feature.

# Phase 0 — Foundation: tasks

Discrete tasks for the five workstreams in [`features/00-foundations/01-requirements.md`](../features/00-foundations/01-requirements.md). Each task is sized to **one focused
session** and touches **at most ~5 files**. Controls are the twelve controls in
[`build-contract.md`](../reference/build-contract.md) §6. No task in this list implements a ClinicOS domain feature — those
belong to Phase 1 onward.

| Workstream | Tasks | Points |
|---|---|:---:|
| WS1 Repository architecture | T0-1 … T0-4 | 8 |
| WS2 Docker | T0-5 … T0-8 | 8 |
| WS3 Environment configuration | T0-9 … T0-12 | 5 |
| WS4 CI skeleton | T0-13 … T0-16 | 5 |
| WS5 Repository rules | T0-17 … T0-19 | 3 |
| Gate 1 evidence | T0-20 | — |

---

## WS1 — Repository architecture (8 points)

- [ ] **T0-1 — Confirm the monorepo layout and workspace membership**
  - Acceptance: `backend/` is a uv workspace member and `frontend/` + `packages/*` are bun workspace members; no `apps/*` path exists; the D-002 source-to-repo mapping table is recorded in the repo docs.
  - Verify: `uv sync` from the repo root resolves the `backend` member; `bun install --frozen-lockfile` resolves the bun workspaces.
  - Files: `pyproject.toml`, `package.json`, `README.md`
  - Controls: 12 Compliance evidence; 2 Authorisation (module-boundary precondition)
  - Evidence: layout mapping table + workspace resolve output

- [ ] **T0-2 — Land the `backend/app/` module skeleton per the spine module map**
  - Acceptance: `main.py`, `api/main.py` (router registration only), `api/routes/`, `core/{config,db,security,audit}.py`, `modules/` (package only, no domain module), `worker/` and `alembic/versions/` exist; `mypy` passes over the skeleton.
  - Verify: `find backend/app -maxdepth 2 -type f` shows the skeleton; `cd backend && uv run mypy app` passes; the app starts with `uv run fastapi dev app/main.py`.
  - Files: `backend/app/main.py`, `backend/app/api/main.py`, `backend/app/core/audit.py`, `backend/app/modules/__init__.py`, `backend/app/worker/__init__.py`
  - Controls: 2 Authorisation; 6 Audit logging (writer placeholder); 12 Compliance evidence
  - Evidence: directory listing + `mypy` output

- [ ] **T0-3 — Land the import-boundary lint that replaces compiler-enforced boundaries**
  - Acceptance: the lint fails when a module imports another module's `models`, `service` internals or private helpers; a module is reachable only through its service facade; the lint runs pre-commit and in the CI `lint` stage.
  - Verify: add a temporary cross-module internal import, run `cd backend && uv run ruff check .`, observe failure, revert; record both runs.
  - Files: `backend/pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/pre-commit.yml`
  - Controls: 2 Authorisation; 12 Compliance evidence
  - Evidence: failing-lint example + passing run (Gate 1 compensating control for D-002)

- [ ] **T0-4 — Establish the green empty baseline**
  - Acceptance: `ruff check`, `ruff format --check`, `mypy app` and `pytest` all pass on the empty baseline, and pre-commit is wired to the same commands.
  - Verify: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest`
  - Files: `backend/pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/test-backend.yml`
  - Controls: 11 Security testing (baseline); 12 Compliance evidence
  - Evidence: baseline run record (WS1 exit gate: CI green on an empty baseline)

---

## WS2 — Docker (8 points)

- [ ] **T0-5 — Backend image: multi-stage, pinned minimal base, non-root, health check**
  - Acceptance: a build stage with the toolchain and a runtime stage with production dependencies only; base image pinned by digest; explicit non-root `USER`; liveness and readiness health checks; no build tooling in the runtime image.
  - Verify: `docker compose build backend`; `docker compose run --rm backend id` shows a non-root uid; `docker image inspect` confirms the pinned digest.
  - Files: `backend/Dockerfile`, `.dockerignore`, `compose.yml`
  - Controls: 8 Secrets management; 11 Security testing
  - Evidence: build output + non-root proof + image inspect

- [ ] **T0-6 — Worker image as a second entrypoint of the same package**
  - Acceptance: the worker is a second entrypoint in `backend/app/worker/`, built into its own image and its own container, with no inbound traffic and its own CPU/memory profile; the process model stays compatible with a later D-004 decision.
  - Verify: `docker compose build worker`; `docker compose up -d worker`; the container runs and exposes no listening port.
  - Files: `backend/Dockerfile`, `backend/app/worker/__init__.py`, `compose.yml`
  - Controls: 8 Secrets management; 11 Security testing
  - Evidence: build output + container run record

- [ ] **T0-7 — Frontend image: pinned base, non-root, static build**
  - Acceptance: a multi-stage frontend image with a build stage and a minimal runtime stage, pinned base digest, non-root runtime user and a health check.
  - Verify: `docker compose build frontend`; `docker compose up -d frontend`; the service reports healthy.
  - Files: `frontend/Dockerfile`, `frontend/package.json`, `compose.yml`
  - Controls: 8 Secrets management; 11 Security testing
  - Evidence: build output + health check result

- [ ] **T0-8 — Compose hardening: read-only filesystem, writable tmp, limits, no-secret context**
  - Acceptance: read-only root filesystem where the service allows it with an explicit writable `tmp` mount; resource limits set; `.dockerignore` excludes VCS metadata, virtual environments, `node_modules`, build artefacts, test output and every `.env` file; an exception list exists for any service that cannot be read-only.
  - Verify: `docker compose up -d` and all services healthy; `docker inspect` shows `ReadonlyRootfs` and limits; `docker compose build` context excludes `.env`.
  - Files: `compose.yml`, `compose.override.yml`, `compose.deploy.yml`, `.dockerignore`
  - Controls: 8 Secrets management; 11 Security testing
  - Evidence: compose inspect output + exception list (WS2 exit gate: images build, run and scan clean locally)

---

## WS3 — Environment configuration (5 points)

- [ ] **T0-9 — Complete the Development environment variable inventory with namespacing**
  - Acceptance: every required variable is listed; variable names are namespaced per service and per environment so a Development value cannot be loaded by Production by accident; the inventory is complete for Development.
  - Verify: start each service from the inventory alone; the inventory table is reviewed line by line against `core/config.py` settings fields.
  - Files: `backend/app/core/config.py`, `.env.example`, `docs/development.md`
  - Controls: 8 Secrets management; 12 Compliance evidence
  - Evidence: Development variable inventory (WS3 exit gate)

- [ ] **T0-10 — `.env.example` with no secrets; untrack and clean the committed root `.env`**
  - Acceptance: `.env.example` carries every required variable name and **no secret value**; the root `.env` is **untracked from git** and added to `.gitignore`; every value that has ever been committed is **rotated**, not merely reviewed; `.env.example` values are unmistakable placeholders.
  - Verify: `git ls-files --error-unmatch .env` **fails** (untracked); `git check-ignore .env` succeeds; secret scan of `.env.example` reports zero secret-shaped values; rotation recorded for `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD` and `POSTGRES_PASSWORD`.
  - Files: `.env.example`, `.env`, `.gitignore`, `docs/development.md`
  - Controls: 8 Secrets management
  - Evidence: `git ls-files` output proving `.env` is untracked; secret scan report; rotation record (D-004 open item 3)
  - **Verified finding, 2026-10-04:** `.env` **is** tracked in git and holds `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD` and `POSTGRES_PASSWORD`, all at the template default `changethis`. `SECRET_KEY=changethis` signs JWTs, so deploying as-is permits token forgery. This is a live control-8 violation, not a hypothetical — it is a Phase 0 exit blocker.

- [ ] **T0-11 — Prove fail-closed startup on missing required configuration**
  - Acceptance: starting with a required variable unset aborts startup, names the missing key, and applies no permissive default; configuration precedence is `process environment → secret store → fail closed`.
  - Verify: `unset <REQUIRED_KEY> && docker compose up backend` fails with the key named; repeat for a representative key per class (database, signing key, environment name).
  - Files: `backend/app/core/config.py`, `.env.example`, `compose.yml`
  - Controls: 9 Error handling (fail closed); 8 Secrets management
  - Evidence: fail-closed startup log + signed CTO config checklist (WS3 exit gate)

- [ ] **T0-12 — Reserve secret-store names, add the secret-access interface, document environment separation**
  - Acceptance: every secret class has a reserved name, an owner and a rotation cadence; secret access is behind one interface so moving off `.env` is a configuration change; the Development/Staging/Production separation model is documented with its Gate 6 verification marked **blocked by D-004**.
  - Verify: the reservation list covers all eight secret classes in `29-operations-and-observability.md` §8.2; the separation document names the D-004 blocker and the Compliance Lead ownership for de-identification.
  - Files: `docs/reference/secrets-inventory.md`, `backend/app/core/config.py`, `docs/reference/environments.md`
  - Controls: 8 Secrets management; 7 Encryption (key handling precondition)
  - Evidence: secret-store reservation list + separation model with blocked marker

---

## WS4 — CI skeleton (5 points)

- [ ] **T0-13 — Define the pipeline with all eleven stages in the fixed order**
  - Acceptance: `lint → typecheck → unit → integration → security tests → SAST → dependency scan → container scan → secret scan → build → deploy` appear as separate, named steps in that order; `lint` = `ruff check` + import-boundary lint; `typecheck` = `uv run mypy app`; a run shows the order.
  - Verify: pipeline definition review; a run record showing every stage name in order.
  - Files: `.github/workflows/ci.yml`, `.github/workflows/test-backend.yml`, `.github/workflows/deploy.yml`
  - Controls: 11 Security testing; 12 Compliance evidence
  - Evidence: pipeline definition + run showing the stage order (Gate 1 check)

- [ ] **T0-14 — Wire the scanners with Critical blocking**
  - Acceptance: Semgrep (SAST), Trivy dependency scan, Trivy container scan and Gitleaks secret scan run on pull requests and the main branch; any failure stops the pipeline; a **Critical** finding blocks build and deploy; secret scanning also runs pre-commit.
  - Verify: open a pull request and confirm all four scanners execute; confirm a failing scan blocks the merge.
  - Files: `.github/workflows/ci.yml`, `.pre-commit-config.yaml`
  - Controls: 11 Security testing; 8 Secrets management
  - Evidence: scanner run output on a pull request

- [ ] **T0-15 — Prove the pipeline blocks a deliberately vulnerable fixture**
  - Acceptance: a planted secret trips `secret scan`, a planted vulnerable dependency trips `dependency scan`, and a deliberate type error trips `typecheck` **before** `unit`; all three runs are recorded and the fixture is reverted before merge.
  - Verify: three throwaway-branch pipeline runs, each recorded by run id; the fixture branch is deleted and the main branch re-run green.
  - Files: `.github/workflows/ci.yml`, throwaway fixture branch (reverted)
  - Controls: 11 Security testing; 12 Compliance evidence
  - Evidence: three blocked-run records + green re-run (WS4 exit gate; source §2 exit criteria)

- [ ] **T0-16 — Retain scan reports and pipeline runs as evidence**
  - Acceptance: scan reports and pipeline runs are retained and referenced by run identifier; the retention position is recorded; no test name is treated as evidence without its output.
  - Verify: locate each evidence artefact by run id from the Gate 1 bundle index; confirm retention settings.
  - Files: `.github/workflows/ci.yml`, `docs/reference/evidence-storage.md`
  - Controls: 12 Compliance evidence; 11 Security testing
  - Evidence: evidence-retention note + one artefact retrieved by run id

---

## WS5 — Repository rules (3 points)

- [ ] **T0-17 — Enable branch protection, required reviews and required checks**
  - Acceptance: direct pushes to the main branch are blocked; at least one approving review is required from a role other than the author; required status checks are the pipeline stages from T0-13; these settings are enabled before the pipeline is declared the required gate.
  - Verify: attempt a direct push and observe the refusal; attempt a merge with a red check and observe the block.
  - Files: repository settings (no file change); `docs/reference/repository-rules.md`
  - Controls: 12 Compliance evidence; 11 Security testing
  - Evidence: branch protection settings + refusal records

- [ ] **T0-18 — Secret scanning on the initial push and across history**
  - Acceptance: Gitleaks runs over the full history; the report is clean or every finding is handled as a leaked-secret incident (rotate, then remove); pre-commit blocks a planted secret locally.
  - Verify: full-history Gitleaks run; plant a secret in a local commit and observe the pre-commit block, then reset.
  - Files: `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `docs/reference/repository-rules.md`
  - Controls: 8 Secrets management; 11 Security testing
  - Evidence: full-history secret scan report + pre-commit block record

- [ ] **T0-19 — Record the signed-commit position and capture branch-protection evidence**
  - Acceptance: signed commits are enabled where practical, or a written position states why not; the branch-protection screenshot is stored for the Gate 1 bundle; the no-self-approval rule is reflected in the required-review configuration.
  - Verify: repository settings review; the screenshot is retrievable from the bundle location.
  - Files: `docs/reference/repository-rules.md`, evidence bundle image
  - Controls: 12 Compliance evidence
  - Evidence: branch protection screenshot (WS5 exit gate; source §2 exit gate)

---

## Gate 1 evidence

- [ ] **T0-20 — Assemble the Gate 1 evidence bundle and its index (days 9–10)**
  - Acceptance: every one of the eight Gate 1 checks has a linked artefact or an explicit blocked marker; the D-003 and D-004 blockers are stated with owners; the bundle index links each artefact to the control it proves; the sign-off record is prepared with the decision left **blank** because Gate 1 is signed at the Phase 1 boundary, not in Phase 0.
  - Verify: walk the eight Gate 1 checks in [`gates.md` § Gate 1](../reference/gates.md#gate-1-architecture) against the bundle; confirm no artefact is claimed without a control link; confirm the bundle states that Gate 1 is **blocked** by D-003 and D-004.
  - Files: `docs/features/00-foundations/01-requirements.md` (index reference), `docs/reference/evidence-storage.md`, bundle index, `docs/reference/gates.md` sign-off copy
  - Controls: 12 Compliance evidence (all controls are evidenced through the index)
  - Evidence: Gate 1 evidence bundle index + prepared sign-off record with the D-003/D-004 blockers named

---

## Task rules

- A task is not started until [`features/00-foundations/01-requirements.md`](../features/00-foundations/01-requirements.md) is approved.
- Every task produces its **named evidence** in the same change that claims the control; a task with no
  artefact is not done ([`../../reference/definition-of-done.md`](../reference/definition-of-done.md) §8).
- A task that introduces an open **High** or **Critical** finding is not done, and a **Critical** finding
  blocks deployment.
- No task may remove or weaken a CI security stage; that requires Security Lead + Head of Platform and is
  never granted for a missing stage ([`../../reference/definition-of-done.md`](../reference/definition-of-done.md) §5).
- Days 9–10 take no new scope: they are the gate-evidence window (`clinic-os-secure-by-design/23-sprint-plan.md`
  §7).

## Open items that gate tasks

| # | Item | Blocks | Owner |
|---|---|---|---|
| OQ-1 | [D-003](../reference/decisions/D-003-identity-model.md) identity decision | Gate 1 signature, Gate 3 | CTO + Security Lead |
| OQ-2 | [D-004](../reference/decisions/D-004-deployment-target.md) deployment decision | Gate 1 separation check, Gate 6, worker process model (T0-6) | CTO + Head of Platform |
| OQ-3 | Region pin and residency evidence — **REQUIRES LEGAL/REGULATORY VALIDATION** | INV-6, Gate 6 | CTO + Compliance Lead |
| OQ-6 | Import-boundary lint phase assignment (Phase 0 vs Phase 1 per D-002) | T0-3, Gate 1 evidence | CTO + Delivery Lead |
| OQ-10 | ~~`control-matrix.md`, `open-questions.md`, `traceability.md` referenced by the [document map](../reference/build-contract.md) are absent~~ **RESOLVED** — all three now exist under [`docs/reference/`](../reference/): [`control-matrix.md`](../reference/control-matrix.md), [`open-questions.md`](../reference/open-questions.md), [`traceability.md`](../reference/traceability.md). T0-20's index must **cite** them, not record them as missing | T0-20 index, control 12 | Compliance Lead + CTO |
| OQ-12 | Gate 1 architecture artefacts unverified for per-threat control/owner coverage and field-level classification | T0-20 bundle | Security Lead + Compliance Lead |

## Sources

- `clinic-os-secure-by-design/23-sprint-plan.md` §2 workstreams, deliverables and exit criteria, §6
  dependency table, §7 estimation and last-two-days rule
- `clinic-os-secure-by-design/26-security-gates.md` §1, §2
- `clinic-os-secure-by-design/02-security-architecture.md` §1 (controls 8, 9, 11), §6 secrets rules
- `clinic-os-secure-by-design/28-aws-network-and-deployment.md` §7 container design, §8 environment
  separation, §10 pipeline
- `clinic-os-secure-by-design/29-operations-and-observability.md` §8 secret classes and rotation
- `clinic-os-secure-by-design/25-adr/ADR-004-docker.md`
- Repo: [`features/00-foundations/01-requirements.md`](../features/00-foundations/01-requirements.md),
  [`build-contract.md`](../reference/build-contract.md), [`gates.md`](../reference/gates.md),
  [`definition-of-done.md`](../reference/definition-of-done.md)
