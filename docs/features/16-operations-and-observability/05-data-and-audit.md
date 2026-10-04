---
doc_id: OZ-FEAT-16-DATA
title: "Operations and observability — data classification, residency and audit"
owner: Head of Platform + Privacy Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-16
phase: 04-phase-4-pilot-go-live
gate: [6, 7]
source:
  - clinic-os-secure-by-design/12-data-classification.md §1, §5
  - clinic-os-secure-by-design/13-data-residency.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

## Field classification

The seven levels are from `12-data-classification.md` §1: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`, `HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`. **Log fields themselves carry a classification**: the redaction pipeline reads the level from the schema annotation, and a missing classification is a build failure, never `INTERNAL` by default (`12` "How to take this point"; `29 §2.2` rule 2).

| Field | Level | In logs | In analytics | Note |
|---|---|---|---|---|
| `request_id`, `correlation_id` | INTERNAL | yes | yes | correlation handles only |
| `tenant_context` | INTERNAL | pseudonymous | aggregate only | keyed pseudonym of the tenant |
| `user_context` | SENSITIVE | pseudonymous | no | keyed pseudonym of the actor |
| `service`, route **template**, `method`, `status`, `latency_ms`, `outcome`, `error_class`, `log_category`, `app_version`, `environment` | INTERNAL | yes | yes | no path parameters, no free text |
| `source_ip` | SENSITIVE | security logs only | no | security and audit stores |
| Audit envelope `tenant_id`, `actor_id` (real identifiers) | SENSITIVE | audit store only | no | the audit event carries real identifiers where the control requires them; application logs carry pseudonyms |
| Reason and reason code | SENSITIVE | code only | no | free-text clinical content never in the log line (`29 §3`) |
| Metric labels (route template, status class, outcome) | INTERNAL | n/a | yes | no patient or raw actor identifier; a raw `tenant_id` label is excluded from cross-tenant dashboards |
| Patient identifiers, clinical note bodies, prescription payloads, OCR text, TGA approval values | HIGHLY_SENSITIVE | **no** | **no** | prohibited from every sink |
| Tokens, keys, MFA seeds, session identifiers, credentials | SECRET | **no** | **no** | blocked by the pipeline and alerted as `security.redaction.blocked` |
| Alert definitions, runbook text, retention configuration | INTERNAL | n/a | n/a | non-clinical operational metadata |

`HIGHLY_SENSITIVE` never reaches a log line, an analytics pipeline or error telemetry — not in a debug line, not in a stack trace, not in a crash report; `SECRET` never persists in a log, analytics pipeline, telemetry export or client bundle (`12` "How to take this point").

## Residency

Log and metric storage is pinned to the Australian production region: `29 §12` names `ap-southeast-2` and residency register rows DR-14 and DR-15 (`13-data-residency.md` §3). This repo has **no region pin** and [`D-004`](../../reference/decisions/D-004-deployment-target.md) is unresolved, so INV-6 is unimplemented rather than satisfied. Whether any log sink, trace backend, error monitor or SIEM is offshore, and the register row for it, is **REQUIRES LEGAL/REGULATORY VALIDATION** (`29` open item O2).

## Audit event catalogue

Names in this table that are absent from `07-audit-architecture.md` §1 are marked **OPEN**: that section states no module invents an action name outside its mandatory list without adding it there first.

| Event | Trigger | Key fields (no PHI values) | Status |
|---|---|---|---|
| `incident.opened` | An incident record is created | `incident_id`, severity, category, tenant scope, detection time | **Absent from `07 §1`** — OPEN, must be added there before use |
| `incident.resolved` | An incident is closed | `incident_id`, closure date, closing owner, residual risk | **Absent from `07 §1`** — OPEN |
| `alert.fired` | An alert crosses its threshold | Alert name, severity, route, threshold, `request_id` | **Absent from `07 §1`** — OPEN |
| `break_glass.used` | Break-glass access is used | Actor, scope, reason, duration, review outcome | **Absent from `07 §1`** — OPEN; break-glass access is in `29 §8.4` and §9 but defines no action name |
| `security.redaction.blocked` | The pipeline blocks a value | Field class, sink, `request_id`, `correlation_id` | Named as a signal in `29 §2.2` rule 5, **absent from `07 §1`** — OPEN |
| `audit.read` | Any read of the audit trail itself | Query filters, result count | Present in `07 §1` — the existing anchor |

## Standard envelope

Every event uses the `07-audit-architecture.md` §2 envelope: `event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result, reason, source_ip, request_id, correlation_id`. It is written in the same transaction as the change, append-only by grant, and **denied and failed attempts are audited with the same fidelity as successes**. A failed audit write fails the operation (`29 §4`; `definition-of-done.md` §1 Part 3).

## Retention

| Store | Recommended retention | Status |
|---|---|---|
| Application logs | 30 days | Source recommendation, unvalidated |
| Security logs | 12 months | Source recommendation, unvalidated |
| Audit logs | 12 months minimum, per the retention schedule | Source recommendation; audit retention is set separately (`14`) |
| Integration logs | 90 days | Source recommendation, unvalidated |
| Infrastructure logs | 90 days hot, 12 months archive | Source recommendation, unvalidated |

Log retention per category and per jurisdiction is **REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy Officer, against the breach assessment window and the retention schedule (`29` open item O3; `29 §12` control row "Log retention supports breach assessment"). Audit and access records are retained beyond the breach assessment window so an incident can be reconstructed (`14`; OAIC NDB guidance).

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Log retention per category and per jurisdiction | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Offshore sink, trace backend, error monitor and SIEM position, and the register rows | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Incident register table name is unnamed by the source; it lives in the audit plane (`18 §4`) | Head of Platform | OPEN |
| The five events absent from `07 §1` must be added there before any code emits them | Security Lead | OPEN |
| Residency of logs and metrics cannot be proven while [`D-004`](../../reference/decisions/D-004-deployment-target.md) is open | CTO + Compliance Lead | OPEN — blocks Gate 6 |
