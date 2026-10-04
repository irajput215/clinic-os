---
doc_id: OZ-FEAT-16-STORY
title: "Operations and observability — user stories"
owner: Head of Platform
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-16
phase: 04-phase-4-pilot-go-live
gate: [6, 7]
source:
  - clinic-os-secure-by-design/29-operations-and-observability.md
  - clinic-os-secure-by-design/18-incident-response.md
  - clinic-os-secure-by-design/21-technical-design.md §10
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A). The audit event names referenced
here are catalogued in [05-data-and-audit.md](05-data-and-audit.md); names absent from
`07-audit-architecture.md` §1 are marked `OPEN` there and are not used in code until added.

## Head of Platform
| US | Story | S: | A: |
|---|---|---|---|
| **US-1** | I want one structured log contract so any request can be reconstructed from its identifiers | Typed fields only; free-text concatenation refused | `request_id` and `correlation_id` on every log line and every audit event, so a line joins to an event |
| **US-2** | I want a metric catalogue with a unit and an owner per metric so "healthy" is defined per route | Labels are bounded; no patient or raw actor identifier | A catalogue change is versioned and reviewed |
| **US-3** | I want every alert to carry a threshold, severity, route, runbook and owner so no alert is noise | An alert missing any of the five is not enabled | Alert definition changes are recorded |
| **US-4** | I want secrets in a managed store, with rotation and no standing production access | No secret in source, image, task definition, build log or ticket; access is just-in-time, time-boxed and audited | Every production access, query and change carries `request_id` and `correlation_id` |
| **US-5** | I want a timed restore drill I can put in front of Gate 6 | Restore runs from an encrypted backup and re-applies later deletion manifests | The drill record states the time measured against the agreed RPO and RTO |

## On-call engineer
| US | Story | S: | A: |
|---|---|---|---|
| **US-6** | I want a page per named condition routed to me, not a dashboard I must watch | The route and runbook resolve before the alert is enabled | Alert firing is recorded in the incident register (event name `OPEN` — see 05) |
| **US-7** | I want the first 30 minutes of each runbook as a checklist | The runbook prescribes evidence preservation **before** remediation | Containment actions record action, time and actor in the incident register |
| **US-8** | I want to know which dependency failed without reading patient data | Errors carry `error_class` only, never a payload, SQL fragment or provider message | The failed request shares `request_id` with its audit event |
| **US-9** | I want production access to be requested per task, not standing | Elevation names a reason, a scope and a duration, and expires automatically | The elevation approval and expiry are auditable records |

## Security Lead
| US | Story | S: | A: |
|---|---|---|---|
| **US-10** | I want a sentinel test proving a planted clinical value never reaches a sink | Sentinels are distinctive and synthetic; production data never enters a test environment | The result is retained as INV-5 evidence |
| **US-11** | I want a page when an audit write fails, so I know the record of truth has a hole | The audited operation fails closed when its audit write fails | The failed write and the alert both reference the operation's `correlation_id` |
| **US-12** | I want cross-tenant denials and RLS context failures on the security dashboard, with a page on a spike | Cross-tenant access returns `404`, never `403`; a missing tenant context matches nothing | Denials are audited with the same fidelity as successes |
| **US-13** | I want a secret found in a sink to be SEV1 and to drive rotation plus a blast-radius review | The redaction pipeline blocks the value and raises `security.redaction.blocked` | The register records exposure location, time and the rotation record |
| **US-14** | I want append-only stores to stay append-only in production, not just by convention | The application role holds `INSERT, SELECT` and never `UPDATE, DELETE, TRUNCATE` on the audit store | A grant-inspection extract is retained as evidence |

## Clinical Safety Officer
| US | Story | S: | A: |
|---|---|---|---|
| **US-15** | I want prescriptions not in a terminal state measured by age, so nothing stalls silently | A timeout becomes an explicit non-terminal state, never success and never failure | The non-terminal state and its resolution are audited by the integration boundary |
| **US-16** | I want dispatch-blocked counts by reason and approval expiry counts on the clinical dashboard | Counts are aggregate; no patient identifier appears in a label | A past-expiry dispatch attempt is audited by the safety gate |
| **US-17** | I want the inbox measured against the two-minute target from receipt to the verification queue | Extraction cannot write a gating state without human verification | Inbox processing metrics are tenant-scoped |
| **US-18** | I want severity levels and the notifiable-breach path agreed before go-live | A SEV1 involving health information opens the breach assessment from the moment of suspicion | The register records the test applied, the factors considered and the decision maker, even when the outcome is "not notifiable" |

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Repo-side runbook artefact does not exist; it must name people, not roles (US-6, US-7) | Head of Platform + Security Lead | OPEN |
| On-call rota and per-alert routes are not assigned to named people with a backup (US-6, US-9) | Head of Platform | OPEN |
| Severity and runbook anchor for the six page conditions in `21 §10` (US-6) | Security Lead | OPEN |
| Statutory breach-notification window (US-18) | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
