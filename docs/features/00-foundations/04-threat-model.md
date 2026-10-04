---
doc_id: FEAT-FOUND-04
title: Foundations, threat model
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
next_review: 2026-11-04
related: 23-sprint-plan, 26-security-gates, 02-security-architecture
source:
  - clinic-os-secure-by-design/26-security-gates.md §1, §2
  - clinic-os-secure-by-design/02-security-architecture.md §1 controls 8 and 11, §6, §7
  - clinic-os-secure-by-design/03-threat-model.md §7, §12, §13
  - clinic-os-secure-by-design/25-adr/ADR-004-docker.md
  - clinic-os-secure-by-design/28-aws-network-and-deployment.md §7, §8, §10
  - clinic-os-secure-by-design/29-operations-and-observability.md §8
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Threat model

## Scoring

$$\text{Risk} = \text{Likelihood (1–5)} \times \text{Impact (1–5)}$$

Bands: **Low ≤ 4**, **Medium 5–9**, **High 10–16**, **Critical ≥ 17**. Every row names a human role,
never "the team". No control in this feature is inherent to the application, so almost every inherent
score is High or Critical — this is infrastructure that every later feature trusts.

---

## STRIDE and residual risk

| ID | STRIDE | Threat & attack path | Inherent | Control / mitigation | Residual | Owner | Source |
| --- | --- | --- | :---: | --- | :---: | --- | --- |
| **T-F1** | **Info Disclosure** | **Secrets committed to the repository.** `SECRET_KEY=changethis` in the tracked root `.env` allows an attacker to mint a valid JWT and impersonate any user; `POSTGRES_PASSWORD=changethis` gives database access. Any clone, fork, CI log or archive exposes them. | **Critical (5×5=25)** | Rotate every committed value; untrack `.env` and commit a name-only `.env.example`; Gitleaks pre-commit and in CI; full-history scan; treat the exposure as a leaked-secret incident (`29` §8.3, `18` R3). | **Medium (2×4=8)** — history retains the old blobs until rotated and purged | Security Lead | `02` §1 control 8, §6 rules 1–2; `29` §8.3; `23-sprint-plan.md` §2 |
| **T-F2** | **Tampering** | **Unauthenticated or absent CI security stages.** All 15 workflows lack semgrep, trivy, gitleaks, bandit, pip-audit and codeql today, so vulnerable code, dependencies and images reach the main branch and the registry with no gate. | **High (4×4=16)** | Define the eleven stages in the fixed order; make them required checks in branch protection; a Critical finding blocks build and deploy (`28` §10). | **Low (1×4=4)** | Security Lead | `02` §1 control 11; `26-security-gates.md` §1; `28` §10; `23-sprint-plan.md` §2 |
| **T-F3** | **Tampering** | **Dependency and base-image supply chain.** A floating tag or an unpinned transitive dependency lets a compromised upstream release enter the runtime image unexamined; the build is not reproducible, so a finding cannot be attributed to an artefact. | **High (4×4=16)** | Pin base images by digest and dependencies by lockfile; Trivy dependency scan and container scan before deploy; immutable registry tags; scan results retained as gate evidence (`ADR-004`). | **Low (2×4=8)** — residual is the untriaged upstream CVE itself | Head of Platform | `ADR-004` "Decision", "Security implications"; `28` §7, §10 |
| **T-F4** | **Elevation of Privilege** | **Container escape.** A process running as root with a writable root filesystem can modify the image at runtime, write persistence, or exploit a kernel or runtime bug to reach the host and the neighbouring task's credentials. | **High (3×5=15)** | Dedicated unprivileged `USER`; read-only root filesystem with an explicit writable `tmp`; no shell or package manager in the runtime image; resource limits; no privileged mode, no host mounts; a Critical image finding blocks deploy. | **Low (1×4=4)** | Head of Platform | `28` §7; `ADR-004` "Security implications"; `26-security-gates.md` §2 control 2 |
| **T-F5** | **Info Disclosure** | **Environment cross-contamination.** One shared `.env`, one compose database and one secret set across Development, Staging and Production lets a developer or a compromised development task read production data or credentials, and lets test data overwrite production state. | **Critical (4×5=20)** | Separate database, buckets, keys, secrets and credentials per environment; synthetic data only below Production; per-environment namespacing so a Development value cannot be loaded by Production; no standing production access (`28` §8). | **Medium (2×5=10)** — the model exists but is unverified while D-004 is open | CTO + Head of Platform | `28` §8; `23-sprint-plan.md` §12; `26-security-gates.md` §2 |
| **T-F6** | **Elevation of Privilege** | **Permissive startup defaults.** The current default check only *warns* when `SECRET_KEY` or `POSTGRES_PASSWORD` is `changethis` and `FASTAPI_ENV=development`, which the committed `.env` sets. A service starts with a known signing key, so the fail-open branch is the deployed path. | **Critical (4×5=20)** | Refuse startup on a missing or placeholder required key in **every** environment; name the key; no environment switch may disable the check; precedence ends in fail-closed (`21` §10). | **Low (1×4=4)** | CTO | `21` §10; `02` §1 control 9; `03-design.md` fail-closed config |
| **T-F7** | **Repudiation** | **Evidence gap: unproven controls.** A green pipeline that never failed for a known-bad input, or an audit event that can be updated or deleted, leaves a control claim that cannot be substantiated at a gate; a failed deployment then has no attributable artefact. | **High (3×4=12)** | A deliberately vulnerable fixture must block each blocking stage; append-only `audit_log` by grant with `INSERT`/`SELECT` only; every control names an evidence artefact and an owner; denied and failed attempts audited as successes are. | **Low (1×4=4)** | Security Lead | `23-sprint-plan.md` §2 exit criteria; `02` §1 controls 6 and 12; `26-security-gates.md` §2 |

---

## Assumptions

- One repository, one uv workspace; the frontend and worker images build from the same checkout.
- The deployment target is unresolved (D-004). The controls above are stated so that they hold for both
  the compose option and the source AWS shape; where they cannot, the gap is in `01-requirements.md`
  OPEN-8.
- No scanner is treated as authoritative. A clean scan is evidence of a control, not a compliance claim
  (`ADR-004` "Compliance implications").

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Whether the exposure of `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD` and `POSTGRES_PASSWORD` in git history is a notifiable breach | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Exact severity threshold per stage and how a scanner suppression is approved and expired | Security Lead | OPEN |
| Whether semgrep, trivy and gitleaks run as pinned images or pinned actions, and who owns the pin | Head of Platform | OPEN |
| Environment cross-contamination (T-F5) cannot be verified before D-004 closes | CTO + Head of Platform | OPEN |
