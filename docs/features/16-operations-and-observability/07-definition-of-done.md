---
doc_id: OZ-FEAT-16-DOD
title: "Operations and observability — definition of done and gate sign-off"
owner: Head of Platform + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-16
phase: 04-phase-4-pilot-go-live
gate: [6, 7]
source:
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md §7, §8
  - clinic-os-secure-by-design/23-sprint-plan.md §11
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Definition of done

The six parts are from `24-definition-of-done.md`. Tick a part only with a link to an artefact an auditor would be shown.

| # | Part | Done | Evidence |
|---|---|---|---|
| 1 | Functional: every acceptance criterion in [01-requirements.md](01-requirements.md) has a passing test, including the negative cases | [ ] | `F1–F9`, `S1–S11`, `A1–A4` output from [06-test-plan.md](06-test-plan.md) |
| 2 | Security: log contract, five separate stores, redaction pipeline, tenant-scoped log queries, probe minimisation and secret handling implemented | [ ] | Sentinel proof (`S1–S4`), bounded-label proof (`S5`), probe test (`S8`), secret scan (`S10`) |
| 3 | Security tests pass in CI: `S1–S11` | [ ] | CI run identifier on the release commit |
| 4 | Audit: the observability event catalogue is emitted with the full envelope, and the audit store is append-only by grant | [ ] | `A1–A4` output; `information_schema.role_table_grants` extract (`S11`) |
| 5 | Operations and compliance: metric catalogue and alert catalogue live; every enabled alert has a threshold, severity, route, runbook and named owner; secrets in the store with rotation records; runbook names people; retention position recorded | [ ] | Metric and alert configuration; rotation records; named-person runbook; retention record |
| 6 | Deployment: image builds, scans are clean, sinks are configured for the chosen target, and the change is verified in Staging | [ ] | Scan reports; Staging verification; sink configuration |

**No part is Done with an open High or Critical finding.**

## Gate sign-off and verification governance

| Stage / Gate | What is verified | Verifier (decision maker) | Approver | Pass policy |
|---|---|---|---|---|
| **CI / automated** | Envelope validator, sentinel leak test, metric cardinality, silent-catch lint and test | CI pipeline (pytest + `ruff`) | Automated gate | Hard block on failure |
| **Gate 6 — Production** | Monitoring and alerting cover the business signals and the security alerts; a restore drill was performed and **timed inside the agreed RPO and RTO**; environment separation; IAM has no long-lived access keys; WAF rules and blocked-request logging active; scans clean of **Critical** | CTO | Security Lead + Head of Platform | **No conditional pass for a Critical finding**; a High may pass conditionally with a documented compensating control, an expiry and a steering committee record |
| **Gate 7 — Go-Live** | **Zero open Critical and High findings**; the incident runbook names **people, not roles**; the notifiable-breach path is understood; a named person is on call for the first two weeks; every `REQUIRES LEGAL/REGULATORY VALIDATION` item has an interim position and an owner | Practice Owner + CTO | Clinical Safety Officer + Compliance Lead | **Zero open Critical and High**; a conditional pass is available only for a non-clinical, non-security item with a named acceptance and a date |
| **Independent compliance** | Retention, residency and breach-reconstruction evidence | Privacy Officer / Compliance Lead | External auditor | Periodic and pre-launch |

There is **no self-approval**: the person who delivered the work never signs its gate (`gates.md`; `26 §9`).

## Control-matrix rows fed by this feature

| Requirement | Control | Implementation | Evidence | Owner | Status |
|---|---|---|---|---|---|
| Structured logging with correlation | Mandatory fields and propagation across queues and providers (`29 §12`) | Logger library and middleware | `F2`, `F4`, `F5` | Engineering Lead | Planned |
| No sensitive data in logs, metrics, traces or error responses (**INV-5**) | Classification-driven redaction before the sink write, with a planted sentinel (`29 §12`; `02 §1` control 9) | Redaction pipeline; error envelope; trace sampling | `S1–S5` | Security Lead | Planned |
| Detection and alerting | Metrics and alerts with routes and runbooks (`29 §12`) | Metric and alert catalogues | `F6`, `F9`, `S7`, `A1–A3` | Security Lead | Planned |
| Log categories are separate and access-controlled | Five stores with separate access and retention (`29 §12`) | Log configuration | `F3`, `S6` | Engineering Lead | Planned |
| Audit is append-only | Application role holds `INSERT, SELECT` only (`17` AUD-01; `07`) | `audit_log` grants in Alembic | `S11`, `A4` | Security Lead | Planned |
| Audit write failure is alerted | Alert on any failed audit write (`17` AUD-03; `29 §12`) | Audit writer and alert | `A1` | Security Lead | Planned |
| Residency of logs, metrics and telemetry | Logs and metrics stored in the approved Australian region (`29 §12`) | Region and store configuration | Register rows DR-14, DR-15 | Security Lead | OPEN — blocked by [`D-004`](../../reference/decisions/D-004-deployment-target.md) |
| Log retention supports breach assessment | Retention beyond the assessment window (`29 §12`) | Retention configuration | Retention policy | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Provider credentials live only in a managed secret store | Secrets per environment with rotation, no secret in an image or task definition (`29 §12`) | Secret-store adapter | `S10` | Security Lead | OPEN — the store depends on `D-004` |
| No standing production access | Just-in-time, time-boxed, audited elevation (`29 §9`) | Elevation workflow | Elevation and review records | Security Lead | Planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| [`D-004`](../../reference/decisions/D-004-deployment-target.md) unresolved: no sink, no region pin and no environment-separation evidence, so **Gate 6 cannot be signed** | CTO + Head of Platform | OPEN — blocks Gate 6 |
| Repo-side runbook naming people, not roles, with a backup | Head of Platform | OPEN — blocks Gate 7 |
| Severity and runbook anchor for the six `21 §10` page conditions | Security Lead | OPEN |
| Tracked root `.env` holds default `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD` | Security Lead | OPEN — Phase 0 exit task |
| RPO and RTO unagreed, so the restore drill has nothing to be measured against | Practice Owner + CTO | OPEN — blocks Gate 6 |
| On-call rota and alert routes not assigned to named people | Head of Platform | OPEN — blocks Gate 7 |
| Per-jurisdiction log retention and the breach-notification window | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Offshore sink, trace backend, error monitor and SIEM position | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
