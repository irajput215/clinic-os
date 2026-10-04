---
doc_id: OZ-FEAT-15-DATA
title: "Administration and configuration — data and audit"
owner: CTO + Privacy Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-15
phase: 04-phase-4-pilot-go-live
gate: [4]
source:
  - clinic-os-secure-by-design/12-data-classification.md §1, §2, §3
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2, §3, §9
  - clinic-os-secure-by-design/13-data-residency.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md §2, §3
  - clinic-os-secure-by-design/02-security-architecture.md §6
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

## Field classification

Levels are from `12-data-classification.md` §1, which defines **seven**: `PUBLIC`, `INTERNAL`,
`CONFIDENTIAL`, `SENSITIVE`, `HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`.

| Field | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- |
| `tenant_id`, `id`, `record_class`, `dry_run_state` | INTERNAL | yes | yes | identifiers and operational state |
| `feature_flags.flag_key`, `enabled`, `version` | INTERNAL | yes | aggregate | a flag name is not a secret |
| `feature_flags.affects_safety_gate` | CONFIDENTIAL | yes | aggregate | control posture |
| `feature_flags.approval_reference` | SENSITIVE | no | no | approval provenance |
| `configuration.config_key`, `version`, `required` | INTERNAL | yes | aggregate | names only |
| `configuration.value` (non-secret, e.g. rate limit, session timeout) | CONFIDENTIAL | value for operational keys only | aggregate | never a clinical value |
| `configuration.secret_ref` (Secrets Manager ARN) | SENSITIVE | no | no | a pointer, not a value (`02 §6`) |
| **A configuration value that confers access** (API key, signing key, webhook secret, credential) | **SECRET** | **no** | **no** | never persists in an application column (`12 §1`); only the ARN is stored |
| `tenant_policy.policy_key`, `policy_value`, `version` | CONFIDENTIAL | yes | no | clinical threshold; audited on change (`11 §4`) |
| `tenant_policy.cso_signoff_reference` | SENSITIVE | no | no | clinical sign-off provenance |
| `retention_jobs.retention_days`, `schedule_cron`, `legal_hold` | INTERNAL | yes | aggregate | |
| `retention_jobs.approved_by`, `last_run_key`, `manifest_hash` | SENSITIVE | pseudonymous | no | |
| Break-glass `ticket_reference` and `reason` | SENSITIVE | reason **code** only | no | free text never written to a log line |
| `legal_holds` register fields (referenced) | SENSITIVE | no | no | written only through the hold workflow |
| Envelope `actor_id`, `actor_role` | CONFIDENTIAL / INTERNAL | pseudonymous | no | role held at decision time |
| Envelope `source_ip` | SENSITIVE | yes | no | security telemetry |

`SECRET` never reaches a log, an analytics pipeline, error telemetry, an image layer, a client bundle or
source control — not in a debug line, a stack trace or a crash report. `HIGHLY_SENSITIVE` does not apply
to this module: no field here is health information. `configuration_history` carries `secret_ref` and
never a secret value.

## Residency
All rows live in the Australian production region (`ap-southeast-2`), one region only; Secrets Manager is
in the same region. No third party receives these values in the MVP. Any vendor that would deliver flags
or configuration cross-border is OPEN and **REQUIRES LEGAL/REGULATORY VALIDATION** before it receives
tenant configuration.

## Audit event catalogue

| Event (source name) | Repo action | Trigger | Key fields beyond the envelope |
| --- | --- | --- | --- |
| `CONFIG_CHANGED` (`20 §12`; `22 US-01`) | `configuration.changed` | a configuration value changed | `config_key`, `from_version`, `to_version`, `is_secret`, `approval_reference` |
| `tenant.security_config_change` (`07 §1`) | `tenant.security_config_change` | tenant security configuration changed | `changed_fields` (names only), `step_up` |
| `FEATURE_FLAG_CHANGED`, `SAFETY_FLAG_CHANGED` (`20 §12`) | `feature_flag.changed` | a flag version written, including a refusal | `flag_key`, `from`, `to`, `version`, `affects_safety_gate`, `approval_reference`, `result` |
| `AUTH_BREAK_GLASS_GRANTED` (`06 §8`) | `auth.break_glass_granted` | break-glass elevation granted | `actor_role`, `ticket_reference`, `expires_at`, `step_up`, `notified` |
| `BREAK_GLASS_USED`, `BREAK_GLASS_EXPIRED` (`22 US-03`) | `auth.break_glass_expired` | elevation ended, by expiry or revocation | `grant_id`, `reason`, `review_required` |
| `record.purged` (`14 §3.3`) | `retention.job_run` | a dry run, an approval or a live run | `rule_id`, `schedule_version`, `approver`, `candidates`, `purged`, `held`, `certificate_id` |
| (none named in doc 07 §1) | `tenant_policy.changed` | a policy value changed | `policy_key`, `from`, `to`, `cso_signoff_reference` |
| `auth.step_up`, `auth.step_up_failed` (`07 §1`) | unchanged | step-up for a named admin operation | `operation`, `resource_id` |
| `user.permission_change` (`07 §1`) | unchanged | permission change — owned by feature 03, not here | `target_user_id`, `added`, `removed`, `step_up` |

**Names absent from `07 §1`.** `configuration.changed`, `feature_flag.changed`,
`AUTH_BREAK_GLASS_GRANTED`, `retention.job_run` and `tenant_policy.changed` do not appear in the
mandatory-event table. Doc 07 §1 states a module must not invent an action name outside that table
without adding it there first, so this is an OPEN item against doc 07 §1, not a licence to diverge.
Two source naming systems are also in use: `06 §8` and doc 20 use `SCREAMING_SNAKE`
(`AUTH_BREAK_GLASS_GRANTED`), doc 22 US-03 uses `BREAK_GLASS_USED` for the same action, and doc 07 §1
uses lowercase dot form. The repo emits the lowercase dot action and carries the source name here.

## Event envelope
Every event uses the `07 §2` envelope, written in the same transaction as the change:

`event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result,
reason, source_ip, request_id, correlation_id, prev_hash, hash`

- `tenant_id` comes from the request context, never the body; `actor_role` is the role held at decision
  time; a scheduled retention run uses `actor_id = SYSTEM` with the job name in `reason`.
- `resource_type` is `TENANT` for configuration and policy, `FEATURE_FLAG` for flags, `SESSION` for
  break-glass and step-up. `FEATURE_FLAG` is not in the `07 §2` enum — recorded as OPEN.
- `reason` is a controlled code, never free text and never a secret or ticket body.
- `result` is `SUCCESS`, `DENIED`, `FAILED` or `UNKNOWN`. **Denied and failed attempts are audited with
  the same fidelity as successes.**
- An audit write failure aborts the administrative change (fail closed, `503`).

## Retention and deletion
Status: OPEN — **REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy Officer.

| Record | Working position (design only) |
| --- | --- |
| Flag, configuration, policy current rows | Life of the tenant; not user-visible deletable |
| Flag, configuration, policy history | Never row-deleted; append-only by grant; whole-partition expiry only |
| Admin audit events | 12 months recommended (`07 §9`; `14 §2`), suspended by a legal hold |
| Retention run certificate | Retained as an audit event; carries rule ID, approver and count, never deleted content |
| Break-glass grant records | Retained per the audit schedule; reviewed retrospectively |

A legal hold suspends purge. Deleting the audit row that recorded an administrative change is refused
and the refusal is recorded (`14 §3.5`). The retention period for configuration and flag history, and
the ownership of the legal-hold register, are unresolved and block Done.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| `configuration.changed`, `feature_flag.changed`, `AUTH_BREAK_GLASS_GRANTED`, `retention.job_run`, `tenant_policy.changed` absent from `07 §1`; add before build | Security Lead + Compliance Lead | OPEN |
| `FEATURE_FLAG` missing from the `07 §2` `resource_type` enum | Security Lead | OPEN |
| Retention period for configuration and flag history | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Legal-hold register ownership and the write path from the hold workflow | Privacy Officer + Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
