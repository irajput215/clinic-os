---
doc_id: FEAT-FOUND-07
title: Foundations, definition of done
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
next_review: 2026-11-04
related: 23-sprint-plan, 26-security-gates, 02-security-architecture
source:
  - clinic-os-secure-by-design/24-definition-of-done.md §1, §2, §3
  - clinic-os-secure-by-design/26-security-gates.md §1, §2
  - clinic-os-secure-by-design/23-sprint-plan.md §2, §6, §10
  - clinic-os-secure-by-design/17-compliance-control-matrix.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Definition of Done

The six parts are from `24-definition-of-done.md` §1. Tick only with a link to evidence — an assertion
is not evidence (`docs/features/README.md` audit standard).

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in 01-requirements.md has a passing test (F1–F15) | [ ] | `backend/tests/foundations/` run id |
| 2 | Security: fail-closed config, pinned images, non-root, read-only root FS, secrets out of git, secret-store interface | [ ] | S7–S9, S12–S15 run ids; image inspect output |
| 3 | Security testing: S1–S15 pass, and each blocking stage is proven by a deliberately vulnerable fixture (S1–S3) | [ ] | failed-run ids for the three fixtures; scan reports |
| 4 | Audit: CI and configuration events emitted with the full envelope; A1–A4 | [ ] | `audit_log` sample; grant listing |
| 5 | Operations & compliance: structured logs with no secret value, metrics and alerts, classification applied, residency position recorded | [ ] | log sample; alert definition; `05-data-and-audit.md` |
| 6 | Deployment: three images build in CI, all scans clean, evidence bundle assembled and indexed | [ ] | pipeline run record; scan reports; Gate 1 bundle |

**No part is Done with an open High or Critical finding** (`24` §3). The tracked `.env` with
`secret` values is an open Critical finding today, so **part 2 and part 6 cannot be ticked** until it
is rotated, untracked and verified.

## Gate sign-off & Verification Governance

Who verifies, who decides and who approves. **No self-approval**: the person who delivered a control
never signs its gate (`26` §"How to take this point").

| Stage / Gate | What is verified | Verifier (decision maker) | Approver | Pass policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | F1–F15, S1–S15, A1–A4; stage order; scanner pins | CI pipeline (pytest, scanners) | Automated gate | **Hard block on any failure**; Critical blocks build and deploy |
| **Gate 1 (Architecture)** | All eight checks in `26-security-gates.md` §2: threat model with control + owner, tenant-isolation model incl. pool hazard, safety-gate design and grain, audit envelope and audited-operation list, environment separation, data classification, CI stage order, named residual-risk owners | **CTO** | **Security Lead** | Conditional pass available for **evidence completeness only** — **not** for a missing threat model or a missing safety-gate design |
| **Gate 2 (Database)** | App role is not owner and has no `BYPASSRLS`; audit table is append-only by grant; a tenant-less request reads zero rows | Security Lead | CTO | **❌ NO conditional pass** |
| **Gate 6 (Production)** | Environment separation: no production database, bucket, secret, key or credential reachable from development; scans clean of Critical | CTO | Security Lead + Head of Platform | **❌ NOT available for a Critical finding**; blocked by D-004 |
| **Independent compliance** | Secret-exposure assessment, evidence retention, classification applied | **Compliance Lead** | External auditor | Notifiable-breach decision is **REQUIRES LEGAL/REGULATORY VALIDATION** |

**Gates that permit no conditional pass:** Gate 2, and the prescription safety gate in Gate 4 — neither
is in this feature's scope, but Foundations supplies the role model and the pipeline both depend on.

## Control matrix rows fed by this feature

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| No secret in source, image, log or committed `.env` | Control 8; `29` §8.3 | untrack `.env`, `.env.example` names only, secret-store interface, Gitleaks pre-commit and CI | F6, F7, S5, S6, S13 | Security Lead | **failing today** |
| A critical scanner finding blocks deployment | Control 11 | fixed stage order, severity threshold, branch protection | F13, F14, S4 | Security Lead | planned |
| The pipeline's security stages are not inert | `23` §2 exit criteria | deliberately vulnerable fixtures per blocking stage | S1, S2, S3, S10 | Security Lead | planned |
| Supply chain is pinned and reproducible | `ADR-004` | digest-pinned base images, committed lockfiles, pinned scanner versions | F8, S11 | Head of Platform | planned |
| A compromised container cannot escalate | `28` §7 | non-root `USER`, read-only root FS, no shell/tooling, resource limits | F9, F10, F15 | Head of Platform | planned |
| Missing configuration refuses startup and names the key | Control 9; `21` §10 | fail-closed settings with no permissive default and no environment escape | F1–F5, S12, S15 | CTO | **failing today** |
| Tenant isolation cannot be bypassed by the app role | Gate 2 | `NOBYPASSRLS`, non-owner role, append-only grants | S8, S9 | Security Lead | planned |
| Production shares nothing with lower environments | `28` §8 | separate database, buckets, keys, secrets, credentials | model only | CTO + Head of Platform | **blocked by D-004** |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| Rotate and untrack the committed `.env` secrets; follow the leaked-secret incident path (T-F1, R5, R6) | Security Lead | **OPEN — Critical, blocks parts 2 and 6** |
| Add the eleven CI stages; no workflow performs any security scan today (T-F2, R11, R12) | Security Lead | **OPEN — blocks parts 3 and 6** |
| `audit_log` does not exist yet, so A1–A4 cannot pass (feature 04 dependency) | CTO | **OPEN — blocks part 4** |
| Rotating the secrets already in git history needs an incident runbook for this repository | Security Lead + Compliance Lead | OPEN |
| Deployment target D-004 — blocks the Gate 1 environment-separation check and all of Gate 6 | CTO + Head of Platform | OPEN |
| Region pin and the residency position (INV-6 is unimplemented) | CTO + Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Approved de-identification standard for a production extract | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Notifiable-breach assessment for the exposed credentials | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Worker process model, base image choice, read-only exception list, tag immutability (`ADR-004` F1–F4) | Head of Platform | OPEN |
| Named humans for each gate role (the source names roles, not people) | Practice Owner | OPEN |
