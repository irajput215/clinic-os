---
doc_id: FEAT-FOUND-01
title: Foundations, requirements
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
next_review: 2026-11-04
related: 23-sprint-plan, 26-security-gates, 02-security-architecture
source:
  - clinic-os-secure-by-design/23-sprint-plan.md §2, §6, §7
  - clinic-os-secure-by-design/26-security-gates.md §1, §2
  - clinic-os-secure-by-design/02-security-architecture.md §1 controls 8 and 11, §6, §7, §11
  - clinic-os-secure-by-design/21-technical-design.md §6, §7, §10
  - clinic-os-secure-by-design/28-aws-network-and-deployment.md §7, §8, §10
  - clinic-os-secure-by-design/29-operations-and-observability.md §8
  - clinic-os-secure-by-design/25-adr/ADR-004-docker.md
repo_docs:
  - 02-user-stories.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Foundations: requirements

## Purpose

Establish the repository, the container build, the environment model and the CI security pipeline so
that every later feature starts on schema and authentication rather than on scaffolding
(`23-sprint-plan.md` §2). This feature owns no clinic domain behaviour. It owns the build contract,
the pipeline and the environment separation every later feature is measured against.

## Scope summary

| Workstream (`23-sprint-plan.md` §2) | This feature delivers | Exit gate |
| --- | --- | --- |
| Repository architecture | `backend/` + `frontend/` + `packages/` layout, pinned toolchains (D-002) | CI green on an empty baseline |
| Docker | Three images, multi-stage, minimal base, non-root, read-only root FS, health checks | Images build, run and scan clean |
| Environment configuration | Namespaced variables, secrets outside git, fail-closed startup | Config checklist signed by the CTO |
| CI skeleton | Fixed stage order including SAST, dependency, container and secret scans | A deliberately vulnerable fixture is blocked |
| Repository rules | Branch protection, required reviews, no secrets in history | Branch protection screenshot in the bundle |

---

## Functional requirements

| ID | Requirement | Acceptance criterion (testable) |
| --- | --- | --- |
| **R1** | All configuration comes from environment variables or the secret store; missing required configuration fails startup and names the missing key | Starting with `SECRET_KEY` unset exits non-zero and the message names `SECRET_KEY`; no request is served (`21-technical-design.md` §10) |
| **R2** | Fail-closed configuration has no permissive default and no development escape | A default or placeholder secret value (`changethis`) refuses startup in every environment, with no `FASTAPI_ENV` bypass (`21-technical-design.md` §10) |
| **R3** | Configuration precedence is fixed: process environment → secret store → fail closed | A key absent from both sources refuses startup; there is no third fallback (`21-technical-design.md` §10) |
| **R4** | Environment variables are namespaced per service and per environment | A Development value cannot be loaded by Production; the inventory names service and environment for every key (`23-sprint-plan.md` §2) |
| **R5** | The root `.env` is untracked from git and `.gitignore`d; only `.env.example` with placeholder-free names is committed | `git ls-files` returns no `.env`; `git log --all -- .env` retains the old blobs, so rotation is evidenced separately (`29` §8.3) |
| **R6** | Every secret value ever committed is rotated; `SECRET_KEY=changethis` is treated as a forged-token incident, not a cleanup | Rotation record names each rotated secret, owner and timestamp; JWT forgery test with the old value fails (control 8) |
| **R7** | Secret-store names are reserved per secret class with a named owner and rotation cadence | Reservation list covers all eight classes in `29` §8.2; each row names an owner and a cadence |
| **R8** | Secret access sits behind one interface so the store can change without a rewrite | One interface plus one implementation; the application imports the interface, never the store SDK (D-004 consequence) |
| **R9** | No role credential is long-lived: task roles and CI federation replace static keys | No static access key in CI configuration; the deploy credential is federated (`02` §6 rule 3) |
| **R10** | Secret scanning runs pre-commit and in CI; a hit fails the build | A planted secret in a fixture fails the `secret scan` stage; the fixture is reverted before merge (`02` §6 rule 1) |
| **R11** | The CI pipeline defines eleven named stages in the fixed order `lint → typecheck → unit → integration → security tests → SAST → dependency scan → container scan → secret scan → build → deploy` | A pipeline run shows the stages in order as separate, visible steps (`28` §10) |
| **R12** | The repository has **no** security-scanning stage today; this is the defect R11 closes | **Verified 2026-10-04:** all 15 workflows under `.github/workflows/` lack semgrep, trivy, gitleaks, bandit, pip-audit and codeql; only test, deploy, playwright, pre-commit and zizmor jobs exist. R11 is not satisfied by any current workflow |
| **R13** | Any stage failure stops the pipeline; a Critical finding blocks build and deploy | A failing stage prevents later stages; severity threshold is enforced in configuration (`28` §10) |
| **R14** | A deliberately vulnerable fixture is blocked: planted secret → secret scan, planted vulnerable dependency → dependency scan, deliberate type error → typecheck | Three recorded failed-run IDs, one per fixture; each fixture reverted after proof (`23-sprint-plan.md` §2 exit criteria) |
| **R15** | `security tests` is a real stage, not a placeholder | The stage runs a named test path today and is the slot the Phase 1 five-category suite occupies (`02` control 11) |
| **R16** | Three images — frontend, backend, worker — build from the one repository; a single container running all three is rejected | Three image build targets exist and produce three images (`ADR-004` "Decision") |
| **R17** | Every image uses a multi-stage build with a minimal runtime stage | Runtime stage contains no build toolchain or package manager (`28` §7 row 1) |
| **R18** | Base images are pinned by digest and dependencies by lockfile; no floating tag in a release image | Image inspect shows a digest reference; `uv.lock` and `bun.lock` are committed (`ADR-004`) |
| **R19** | The container runs as a dedicated unprivileged user; `USER` is set explicitly | `docker compose run --rm backend id` returns a non-zero uid (`28` §7) |
| **R20** | The root filesystem is read-only where the service allows it, with an explicit writable `tmp`; exceptions are listed with a reason | Compose configuration shows `read_only` and a `tmpfs` mount, or a listed exception (`ADR-004` open item F2) |
| **R21** | Every image defines liveness and readiness health checks consumed by the orchestrator | A health check is declared and an unhealthy probe returns non-2xx (`28` §7) |
| **R22** | Images declare CPU and memory limits; backend and worker have separate profiles | Compose or task definitions show separate limits (`28` §7) |
| **R23** | `.dockerignore` excludes VCS metadata, virtual environments, `node_modules`, build output, test output and any `.env` | Build context listing contains no `.env` and no `.git` (`23-sprint-plan.md` §2) |
| **R24** | No secret is present in an image layer, the build cache, a build argument, a Dockerfile or a committed environment file | No-secret-in-image check passes; layer history contains no secret (`02` §6 rules 1–2) |
| **R25** | Production never shares a database, bucket, key, secret, credential or API key with Development or Staging | Environment separation table is complete and each environment has its own store; verification is blocked by D-004 (`28` §8) |
| **R26** | Development and Staging hold synthetic data only; production data never enters a lower environment without approved de-identification | Test-data rule recorded; de-identification standard is **REQUIRES LEGAL/REGULATORY VALIDATION** (`28` §8; `12` §7) |
| **R27** | Denied and failed attempts are audited with the same fidelity as successes, using the standard envelope | CI and configuration denials emit the envelope from doc 07 with `result = DENIED` (`21-technical-design.md` §4) |
| **R28** | The application database role owns no table and holds no `BYPASSRLS` | `information_schema`/`pg_roles` inspection returns `rolbypassrls = false` and non-owner (`26-security-gates.md` §2 Gate 2) |
| **R29** | Branch protection blocks direct pushes and requires review plus the pipeline checks; evidence is stored in the Gate 1 bundle | Branch protection settings and screenshot in the bundle (`23-sprint-plan.md` §2) |
| **R30** | The Development environment variable inventory is complete and signed by the CTO | Signed checklist artefact (`23-sprint-plan.md` §2) |

---

## Out of scope for the MVP

- Any clinic domain module, table, migration, endpoint, permission or domain audit event. Those belong to
  features 01–16 (`docs/features/README.md`).
- Production infrastructure: Terraform, AWS resources, WAF, ALB, ECS, ECR, RDS, S3, SQS, KMS and
  Secrets Manager. Blocked by D-004, which is OPEN.
- The identity model (D-003 OPEN) and the managed OIDC provider.
- Penetration test, restore drill, RPO/RTO and the Gate 6 environment-separation verification.
- Region pinning and any residency claim. The repository has no region pin today.

## Open items

| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | Deployment target (compose on an Australian host, the source AWS shape, or hybrid) — D-004. Blocks the Gate 1 environment-separation check and all of Gate 6 | CTO + Head of Platform | OPEN |
| OPEN-2 | Worker process model: separate container or second process in the backend image (D-002 open item 2) | Head of Platform | OPEN |
| OPEN-3 | Base image choice and digest-pinning policy per service (`ADR-004` F1) | Head of Platform | OPEN |
| OPEN-4 | Read-only-filesystem exception list (`ADR-004` F2) | Head of Platform | OPEN |
| OPEN-5 | Base image update cadence and owner (`ADR-004` F3) | Security Lead | OPEN |
| OPEN-6 | Registry tag immutability and retention policy (`ADR-004` F4) | Head of Platform | OPEN |
| OPEN-7 | Approved de-identification standard for a production extract entering a lower environment | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-8 | Which Gate 6 checks are replaced under D-004 Option B, by what control and evidence | Security Lead | OPEN |
| OPEN-9 | Whether `packages/shared/` is needed given the frontend SDK is generated from OpenAPI (D-002 open item 1) | Frontend Lead + CTO | OPEN |
| OPEN-10 | Who approves a gate when the named approver role is unfilled (single-person team) | Practice Owner | OPEN |
| OPEN-11 | Rotating the secrets already in git history is an incident response, and its runbook is not yet written for this repository | Security Lead | OPEN — blocks Done |
