---
doc_id: FEAT-FOUND-05
title: Foundations, data and audit
owner: CTO + Privacy Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
next_review: 2026-11-04
related: 23-sprint-plan, 26-security-gates, 02-security-architecture
source:
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2
  - clinic-os-secure-by-design/12-data-classification.md §1, §5.1, §7
  - clinic-os-secure-by-design/13-data-residency.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md
  - clinic-os-secure-by-design/29-operations-and-observability.md §8
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

Foundations holds no patient data. Its data classes are **configuration, secrets and environment
values** — which is precisely why it matters: a secret in this feature is a key to every later one.

Levels are the **seven** from `12-data-classification.md` §1: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`,
`SENSITIVE`, `HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`.

## Field classification

| Field | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- |
| Environment name (`development`/`staging`/`production`) | INTERNAL | yes | yes | non-sensitive configuration |
| Configuration **key name** (`DATABASE_URL`, `SMTP_HOST`) | INTERNAL | yes | yes | name only; never the value |
| `PROJECT_NAME`, `EMAILS_FROM_EMAIL`, `FRONTEND_HOST` | INTERNAL | yes | yes | non-sensitive configuration |
| Container image reference, digest, tag | INTERNAL | yes | yes | evidence artefact (`ADR-004` F4) |
| Scan result, stage name, scan duration, severity counts | SENSITIVE | yes | aggregate only | security findings (`12` §1 SENSITIVE) |
| Secret-store **ARN / name** (`integration_credentials_refs`) | CONFIDENTIAL | name only | no | a pointer carries no secret material (`12` §5.1 rule 1) |
| `DATABASE_URL` **with password** | SECRET | **no** | **no** | connection string is a credential |
| `SECRET_KEY` (session/JWT signing) | SECRET | **no** | **no** | disclosure permits token forgery |
| `FIRST_SUPERUSER_PASSWORD` | SECRET | **no** | **no** | bootstrap credential |
| `SMTP_PASSWORD`, `SENTRY_DSN` | SECRET | **no** | **no** | third-party credential |
| Provider API keys, webhook signing secrets, CI deploy credentials | SECRET | **no** | **no** | `29` §8.2 classes |
| Encryption private keys, MFA seed secrets | SECRET | **no** | **no** | never in an application column (`12` §5.1) |
| CI environment variables, runner context | INTERNAL | yes | no | no secret value in runner logs |
| `.env.example` contents | PUBLIC | n/a | n/a | names only, **no value**, committed |
| Root `.env` contents | SECRET | **no** | **no** | **must not be committed** (`29` §8.3) |

`SECRET` is the top of the containment ladder: **no persistence in an application column, no logs, no
analytics, no telemetry, no export** (`12` §1, §5.1). A secret must never be written to a log line, a
stack trace, a crash report, a build log, a ticket or a chat message — and a hit fails the build.

## Residency

Synthetic data only in Development and Staging; production data stays in Production (`28` §8,
`12` §7). **Repo reality — verified 2026-10-04:** the repository has **no region pin**, so INV-6 (data
stays in Australia) is **unimplemented** — neither true nor false. No artefact in this feature may
claim residency. Owner: CTO + Compliance Lead; blocked by D-004.

## Audit events

The `audit_log` table and the standard envelope are delivered by feature 04 (audit-log); this feature
defines **which CI and configuration events must be recorded** once it exists. Until then, denials are
logged but not audited, which is an open gap (see below).

| Event | Trigger | Key fields beyond the envelope |
| --- | --- | --- |
| `ci.pipeline.completed` | pipeline reaches a terminal state | commit, workflow, stage list, result, duration |
| `ci.security_stage.failed` | any security stage fails | stage, rule or signature id, severity, blocked commit |
| `ci.fixture_blocked` | a deliberately vulnerable fixture is caught | fixture id, stage, run id |
| `container.build` | image built and pushed | image reference, digest, scan summary |
| `secret.scan.completed` | working-tree or full-history scan | scope, finding count, tool version |
| `secret.rotated` | a committed or exposed secret is rotated | secret **name**, owner, reason |
| `secret.exposure_assessed` | exposure inventory reviewed | scope, decision owner, outcome |
| `config.validation_failed` | startup refused on missing or placeholder key | key **name**, environment |
| `config.loaded` | task starts with a valid configuration set | environment, key **names only** |
| `db.grants_inspected` | grant-inspection test runs | role, observed privilege set, `rolbypassrls` |
| `evidence.read` | auditor reads a pipeline run or report | actor, artefact, purpose |

Each event uses the standard envelope from `07-audit-architecture.md` §2: `event_id, timestamp,
tenant_id, actor_id, actor_role, action, resource_type, resource_id, result, reason, source_ip,
request_id, correlation_id` (plus `prev_hash`/`hash` for the chain). CI events carry `actor_id` of
`SYSTEM` with the workflow name in `reason`, because no tenant owns a pipeline run.

The store is **append-only by grant**: the application role holds `INSERT` and `SELECT` only, and
**denied and failed attempts are audited with the same fidelity as successes** — a failed security
stage and a refused startup are events, not silence.

## Retention

Status: **OPEN — REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy Officer.

Working assumption for design only: scan reports and pipeline runs are retained for at least the gate
cycle that consumes them, referenced by run id, because `definition-of-done.md` requires an evidence
artefact per control. Audit events follow the retention the Privacy Officer confirms. Rotated secret
values are never retained anywhere in recoverable form.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Retention period for CI evidence, scan reports and audit events | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether `SECRET_KEY` exposure in git history is a notifiable breach, and the interim position until then | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| `audit_log` does not exist yet, so CI and configuration events cannot be audited as specified until feature 04 lands | CTO | OPEN — blocks Done |
| The notifiable-breach assessment path for a leaked credential names people, not roles | Compliance Lead | OPEN |
