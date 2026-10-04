---
doc_id: OZ-FEAT-16-DESIGN
title: "Operations and observability — design"
owner: Head of Platform + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-16
phase: 04-phase-4-pilot-go-live
gate: [6, 7]
source:
  - clinic-os-secure-by-design/29-operations-and-observability.md §1–§12
  - clinic-os-secure-by-design/21-technical-design.md §10
  - clinic-os-secure-by-design/18-incident-response.md §1–§7
  - clinic-os-secure-by-design/12-data-classification.md §1, §5
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

## Structured log contract

Every log line is JSON with a stable schema, and free-text concatenation is not permitted: the logger accepts typed fields only, and a raw string is refused unless it matches an allow-listed non-sensitive template (`29 §2`).

| Field | Rule |
|---|---|
| `request_id` | Generated at the edge, propagated through every call; a line without it is not emitted |
| `correlation_id` | Per user intent, across queues and providers; joins a log line to an audit event |
| `tenant_context` | Keyed pseudonym of the tenant; the raw identifier never appears in an application log |
| `user_context` | Keyed pseudonym of the actor; the raw identifier never appears in an application log |
| `service`, `route` | Service name; route **template**, never the resolved path or a path parameter |
| `action` | Audited action or handler name; closed vocabulary |
| `method`, `status`, `latency_ms`, `outcome` | HTTP method and status; server-measured duration; `success`, `denied`, `error`, `rate_limited` |
| `error_class` | Classified type; never a message, SQL fragment or provider text |
| `log_category`, `app_version`, `environment` | One of the five categories below; artefact version; Development, Staging or Production |

**Hard rule.** No clinical content, secret or full clinical request body reaches a log line, an analytics pipeline or error telemetry — not in a debug line, not in a stack trace, not in a crash report. `HIGHLY_SENSITIVE` stops the line, `HEALTH_INFORMATION` is pseudonymised, `SECRET` is blocked and alerted as `security.redaction.blocked`, and there is no bypass for a debug, trace, crash or error path (`12 §1`; `29 §2.2`).

**Five separate stores**, each with its own access and retention — not one stream with a `category` field (`29 §1`): **Application** (request lifecycle, errors); **Security** (auth, authorisation denials, RLS context failures, rate-limit rejections, malware, WAF); **Audit** (the append-only envelope); **Integration** (provider calls, correlation, retry, latency, error codes); **Infrastructure** (VPC, task, RDS, object store, KMS, load balancer).

## Metric catalogue

Every metric has a unit and an owner; the source for every row is `21-technical-design.md` §10 unless noted. No label carries a patient or raw actor identifier, and a raw `tenant_id` label is permitted internally but excluded from any cross-tenant dashboard (`29 §4`). An OPEN target is a figure the source does not name and is not invented here.

| Metric | Unit | Target or threshold | Owner |
|---|---|---|---|
| API latency p50/p95/p99, by route | ms | OPEN | Engineering Lead |
| Error rate (5xx and handled), by route | percent, rolling window | Alert threshold OPEN | Engineering Lead |
| Database latency | ms | OPEN | Engineering Lead |
| Database connection saturation | percent of pool | OPEN | Engineering Lead |
| Queue depth and queue age (oldest message) | messages, seconds | Normal band OPEN | Engineering Lead |
| Worker failure and retry counts | count | OPEN | Engineering Lead |
| Integration failure and latency, per provider | count, ms | OPEN | Engineering Lead |
| Webhook lag | seconds | OPEN | Engineering Lead |
| Notification delivery rate | percent | OPEN | Engineering Lead |
| Prescriptions not in a terminal state | count | Non-terminal age threshold OPEN | Clinical Safety Officer |
| Audit write failures | count | **Any occurrence** | Security Lead |
| Cross-tenant authorisation denials | count | **Any occurrence**; a spike pages | Security Lead |
Additional `29 §4` signals — RLS context failures, clinical record query p50/p95/p99 (**p95 ≤ 200 ms**), dispatch blocked by reason, approval expiry counts, inbox processing time (**two-minute target**), availability, malware detections, rate-limit rejections, authentication failures, export and bulk reads — are emitted under the same rules; owners Security Lead, Engineering Lead and Clinical Safety Officer.
## Alert catalogue

Every enabled alert has one threshold, one severity, one route, one runbook and one named owner; an alert missing any of the five is removed or completed before enablement (`29 §5`; `18 §3`). Runbook anchors are in `18-incident-response.md` §5.

| Alert | Condition | Severity | Runbook | Owner | Source |
|---|---|---|---|---|---|
| Cross-tenant authorisation denial spike | Denials above the normal band | Page | OPEN | Security Lead | `21 §10` |
| Prescription non-terminal age | Age beyond threshold | Page | OPEN | Clinical Safety Officer | `21 §10` |
| Audit write failure | Any failed audit write | SEV2 | `R1` | Security Lead | `21 §10`; `29 §5` |
| Reconciliation job failure | Job fails or leaves items unresolved | Page | OPEN | Head of Platform | `21 §10` |
| Backup or restore failure | Backup or restore drill fails | Page | OPEN | Head of Platform | `21 §10`; `29 §10` |
| WAF block-rate anomaly | Block rate outside the normal band | Page | OPEN | Security Lead | `21 §10` |
| Cross-tenant read signal | A response carries another tenant's resource | SEV1 | `R1` | Security Lead | `29 §5` |
| RLS context failure | Missing or invalid tenant context | SEV2 | `R1` | Security Lead | `29 §5` |
| Secret in a sink, or redaction block | Redaction block, or a secret in a deployed artefact | SEV1 | `R3` | Security Lead | `29 §2.2`, `§5` |
## Secrets management

A secret is any value whose disclosure grants access or defeats a control (`29 §8.1`). It is never in source control, a task definition or its environment variable, an image layer or build argument, a committed `.env`, a build or application log, an error message, crash report or ticket, a frontend bundle or source map, a database column or backup, or a chat, email or vendor portal (`29 §8.3`; `02 §6` rule 1).

| Secret class | Where it lives | Rotation cadence, with overlap | Owner |
|---|---|---|---|
| Database credentials | Secret store, referenced by ARN | 90 days recommended, automated | Engineering Lead |
| Provider API keys | Secret store | 90 days recommended, or provider policy | Security Lead |
| OIDC client secret | Secret store | 180 days recommended, or provider guidance | Security Lead |
| Session signing and field-level encryption keys | KMS, non-exportable / customer-managed | Annual recommended; the old signing key is kept for verification | Security Lead |
| Webhook signing secrets | Secret store | 90 days recommended, **with an overlap window** | Engineering Lead |
| CI deploy credentials | OIDC federation, no long-lived key | No static credential; trust reviewed annually | Engineering Lead |
| Break-glass credentials | Sealed store, dual control | Reviewed quarterly; a used value rotated immediately | Security Lead |

Cadences are internal recommendations pending review against key-management guidance and provider policy (`29 §8.2`, O4). Secret scanning runs pre-commit and in CI and blocks the build, and **a suspected exposure is an incident, not a cleanup task**: any suspected exposure or a finding in a deployed artefact is handled under `R3`, with rotation, a search of logs and images for the value, and a review of what the credential could reach (`29 §8.3`; `02 §6` rule 5).

**Repo finding:** the root `.env` is tracked in git with template-default values — a live violation of this section, carried as OPEN-2 in [01-requirements.md](01-requirements.md).
## Incident readiness

Severity and response targets (`18 §2`); the targets are internal recommendations, and anything touching a legal clock is **REQUIRES LEGAL/REGULATORY VALIDATION**.

| Severity | Definition | Acknowledge | Containment | Paged |
|---|---|---|---|---|
| SEV1 | Confirmed or strongly suspected exposure of health information, or an exploited control failure | 15 min, 24×7 | Begun within 1 hour | Security Lead, CTO, on-call, Privacy Officer; Practice Owner notified |
| SEV2 | Suspected exposure without confirmation, or a serious failure with no exploitation | 30 min business hours, 2 h out of hours | Within 4 hours | Security Lead, on-call, Engineering Lead |
| SEV3 | Single-tenant or single-user issue, or a failure with limited blast radius | Next business day | Within 3 business days | Security Lead, Engineering Lead |
| SEV4 | Near miss or a finding with no data or service impact | Next business day | Planned remediation | Engineering Lead |

Eight runbooks exist (`18 §5`) — `R1` cross-tenant exposure, `R2` clinician credential compromise, `R3` leaked secret, `R4` ransomware or destructive event, `R5` lost device with a clinical session, `R6` misconfigured object store, `R7` malicious inbox file, `R8` wrong-pharmacy or wrong-patient dispatch. Each states trigger, first 30 minutes, evidence preservation, internal notification and what not to do; Gate 7 requires the repo-side runbook to name **people, not roles**, and the source names roles only, so that copy is OPEN.

**Notifiable-breach assessment path** (`18 §6`), owned by the Privacy Officer and run in parallel with containment because the clock starts at suspicion: unauthorised access, disclosure or loss? → serious harm likely? → can remedial action prevent the risk? → if not, an eligible data breach, statement and notification per the statutory path. The 30-day figure and the multi-tenant who-notifies-whom question are **REQUIRES LEGAL/REGULATORY VALIDATION**.

## Database privileges

The application connects as non-owner role `clinos_app`, with no `BYPASSRLS`, and privileges are enforced by grant rather than convention (`04 §9`; `07 §3`).

```sql
GRANT SELECT, INSERT ON audit_log TO clinos_app;          -- the record of truth
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app;
-- The incident register lives in the audit plane, append-only for the factual record and amended by
-- addendum rather than edit (`18 §4`); the source names no separate table: OPEN.
```
## Deny-by-default request path

The endpoint declaration standard permits exactly two unauthenticated surfaces: public intake, and the liveness/readiness probes. A probe exposes **no tenant data and no more than a boolean status** and is **never routed through tenant resolution** ([`definition-of-done.md`](../../reference/definition-of-done.md) §4; `28` §9); probe paths are repo-chosen and OPEN.

| Probe | Auth | Exposes | Tenant resolution |
|---|---|---|---|
| Liveness and readiness | None | Boolean status only; **no tenant data** | **Never routed through tenant resolution** |

1. Generate `request_id` at the edge and `correlation_id` per user intent.
2. Authenticate the session; only the two permitted unauthenticated surfaces are excepted.
3. Resolve the tenant from the session and `SET LOCAL app.tenant_id` inside the transaction.
4. Check the granular permission in the central policy layer **before** the handler body runs.
5. Build the log line from typed fields only; a raw string is refused.
6. Classify: `HIGHLY_SENSITIVE` stops the line, `HEALTH_INFORMATION` is pseudonymised, `SECRET` is blocked and alerted.
7. Scrub the deny list (tokens, keys, card patterns, document markers), and let the envelope validator fail closed, so a line missing `request_id` or `correlation_id` is dropped and counted rather than emitted.
8. Route to exactly one of the five sinks, emit metrics with bounded labels, and write the audit event — a failed audit write fails the operation.

**Failure behaviour.** A missing or empty tenant setting matches **nothing**, never everything, and a tenant-context failure fails closed and alerts (`29 §4`). A redaction block is a security signal, alerted and reviewed, never a silent drop (`29 §2.2` rule 5). A missing classification is a build failure and fails closed at runtime as the most restrictive level. Errors use the standard envelope with `request_id` and no stack trace, and cross-tenant access returns `404`, never `403` (`02 §7`). An alert with no runbook is not enabled, and a backup or restore failure stops Gate 6 rather than shipping (`29 §5`, §10).

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Sink, tracing and error-monitor products, and the region pin — blocked by [`D-004`](../../reference/decisions/D-004-deployment-target.md) | CTO + Head of Platform | OPEN — blocks Gate 6 |
| Severity and runbook anchor for the six `21 §10` page conditions, and the repo-side runbook naming people, not roles; the incident-register table is unnamed by the source | Security Lead + Head of Platform | OPEN |
| Tracked root `.env` with default secrets | Security Lead | OPEN — Phase 0 exit task |
| Metric targets other than p95 ≤ 200 ms and the two-minute inbox target | Head of Platform | OPEN |
| Log retention per category and jurisdiction; offshore sink position | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
