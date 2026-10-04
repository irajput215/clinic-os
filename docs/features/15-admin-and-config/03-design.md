---
doc_id: OZ-FEAT-15-DESIGN
title: "Administration and configuration — design"
owner: CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-15
phase: 04-phase-4-pilot-go-live
gate: [4]
source:
  - clinic-os-secure-by-design/21-technical-design.md §7, §10
  - clinic-os-secure-by-design/20-product-requirements.md §12
  - clinic-os-secure-by-design/06-authentication-rbac.md §8, §12
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md §4
  - clinic-os-secure-by-design/14-retention-and-deletion.md §3
  - clinic-os-secure-by-design/04-database-erd.md §3.15, §6, §9
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

## `feature_flags` — one current row per `(tenant_id, flag_key)`
| Column | Type | Constraints and notes |
| --- | --- | --- |
| `id` | uuid | PK, `gen_random_uuid()` |
| `tenant_id` | uuid | NOT NULL, FK `tenants(id)`; RLS key |
| `flag_key` | text | NOT NULL, `CHECK (flag_key <> '')`; allowlist |
| `enabled`, `affects_safety_gate` | boolean | NOT NULL DEFAULT false |
| `approval_reference` | text | NULL; `CHECK (NOT affects_safety_gate OR approval_reference IS NOT NULL)` |
| `version` | integer | NOT NULL DEFAULT 1; monotonic per flag; a cache is keyed on it |
| `changed_by`, `changed_at` | uuid, timestamptz | NOT NULL; the actor and the change time |

`UNIQUE (tenant_id, flag_key)`; partial index on `(tenant_id) WHERE affects_safety_gate`. For a reserved
safety-gate key, `CHECK (NOT affects_safety_gate OR enabled)` makes the disabled state unrepresentable,
and a `BEFORE UPDATE` trigger raises `SAFETY_GATE_FLAG_IMMUTABLE` if `enabled` is set false or
`affects_safety_gate` moves — a flag affecting the safety gate can never disable it (R5).
## `configuration` — one current row per `(tenant_id, config_key)`
| Column | Type | Constraints and notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `tenant_id` | uuid | NOT NULL, FK; RLS key |
| `config_key` | text | NOT NULL; namespaced per service and environment (`21 §10`) |
| `value`, `secret_ref`, `is_secret` | text, text, boolean | NULL, NULL, NOT NULL DEFAULT false; a value that confers access is stored as a Secrets Manager ARN in `secret_ref`, never as a value (`02 §6`); `CHECK (is_secret OR secret_ref IS NULL)` |
| `value_class` | text | NOT NULL; `CHECK IN ('INTERNAL','CONFIDENTIAL','SENSITIVE','SECRET')` (`12 §1`) |
| `required` | boolean | NOT NULL DEFAULT false; an absent required key fails startup |
| `version`, `changed_by`, `changed_at` | integer, uuid, timestamptz | NOT NULL; `version` DEFAULT 1 |

`UNIQUE (tenant_id, config_key)`; `CHECK (value_class <> 'SECRET' OR is_secret)`. Precedence:
`process environment → secret store → fail closed if a required key is absent`, with **no permissive
default**. `app/core/config.py` (pydantic-settings) refuses startup and names the key
(`ERR_CONFIG_REQUIRED_KEY_ABSENT`), never its value.
## `tenant_policy` — clinical and operational policy values
| Column | Type | Constraints and notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `tenant_id` | uuid | NOT NULL, FK; RLS key |
| `policy_key` | text | NOT NULL, `CHECK IN ('tga_inbox_confidence_threshold','tga_inbox_auto_create_threshold','tga_inbox_field_floor','tga_inbox_match_threshold')` (`11 §4`) |
| `policy_value` | numeric(4,3) | NOT NULL; `CHECK (policy_value BETWEEN 0 AND 1)` |
| `is_clinical_safety_parameter`, `cso_signoff_reference` | boolean, text | NOT NULL DEFAULT true, NULL; `CHECK (NOT is_clinical_safety_parameter OR cso_signoff_reference IS NOT NULL)` |
| `version`, `changed_by`, `changed_at` | integer, uuid, timestamptz | NOT NULL; `version` DEFAULT 1 |

`UNIQUE (tenant_id, policy_key)`. Seeded: `tga_inbox_confidence_threshold = 0.950` (`11 §4`), a
**clinical safety parameter requiring CSO sign-off**; `tga_inbox_auto_create_threshold` is disabled by
default. A change needs `tenant:configure` plus step-up (R6).
## `retention_jobs`
| Column | Type | Constraints and notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `tenant_id` | uuid | NOT NULL, FK; RLS key |
| `record_class` | text | NOT NULL, `CHECK IN ('AUDIT','CLINICAL','SESSION','DOCUMENT','INBOX','EXPORT')` (`04 §3.15`) |
| `schedule_cron`, `retention_days` | text, integer | NOT NULL; `CHECK (retention_days > 0)` |
| `legal_hold`, `dry_run_state` | boolean, text | NOT NULL DEFAULT false, NOT NULL DEFAULT `'NOT_RUN'`; a hold blocks deletion entirely; state `CHECK IN ('NOT_RUN','DRY_RUN_PASSED','APPROVED','EXECUTED','FAILED')` |
| `last_run_at`, `last_run_count`, `manifest_hash` | timestamptz, integer, text | NULL; the manifest is written before anything is deleted (`14 §3.2`) |
| `last_run_key` | text | NULL; `UNIQUE (tenant_id, record_class, last_run_key)` makes a replay idempotent |
| `approved_by`, `approved_at` | uuid, timestamptz | NULL; `CHECK (dry_run_state <> 'APPROVED' OR approved_by IS NOT NULL)` |

`UNIQUE (tenant_id, record_class)`; index on `(tenant_id, dry_run_state)`. The legal-hold register
(`legal_holds`, `07 §9`; `14 §3.6`) is read, never written, here; its ownership is OPEN (01 OPEN-6).
## Append-only history and grants
`feature_flag_history`, `configuration_history` and `tenant_policy_history` share one shape — `id uuid PK`,
`tenant_id uuid NOT NULL`, `<key> text NOT NULL`, `version integer NOT NULL`, `changed_by`,
`changed_at`, `change_reason_code`, plus the parent's value columns **except any secret**
(`configuration_history` carries `secret_ref`, never a value); `UNIQUE (tenant_id, <key>, version)`.

```sql
GRANT SELECT, INSERT, UPDATE ON feature_flags, configuration, tenant_policy, retention_jobs TO clinos_app;
REVOKE DELETE, TRUNCATE ON feature_flags, configuration, tenant_policy, retention_jobs FROM clinos_app;
GRANT SELECT, INSERT ON feature_flag_history, configuration_history, tenant_policy_history TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON feature_flag_history, configuration_history, tenant_policy_history FROM clinos_app;
GRANT SELECT ON retention_jobs TO clinos_retention;
REVOKE ALL ON feature_flags, configuration, tenant_policy, feature_flag_history, configuration_history, tenant_policy_history, audit_log FROM clinos_retention;
```
## RLS
- `ENABLE` and `FORCE ROW LEVEL SECURITY` on all seven tables.
- Policy: `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` for SELECT, INSERT and
  UPDATE, with a matching `WITH CHECK` on writes; an unset tenant matches nothing, never everything.
- The tenant is set with `SET LOCAL` inside each transaction, never per pooled connection or session; the
  app role is not the table owner and has no `BYPASSRLS`.
## Break-glass contract
- **Scope:** named tenant, resource class and action set; least privilege; no standing production data access (`02 §6`).
- **Trigger:** `POST /api/v1/admin/break-glass` with a ticket reference and a written reason, after step-up with a passkey or hardware key (`06 §8`).
- **Lifetime:** a short, explicit `expires_at` enforced server-side on every request; single use; no silent renewal — an elevation is time-bounded, never open-ended.
- **Notification:** dual notification on grant — practice owner and Security Lead — plus an alert (`02 §11`), and its own event type.
- **Audit and review:** `AUTH_BREAK_GLASS_GRANTED` on grant, `BREAK_GLASS_EXPIRED` on expiry, and a mandatory retrospective review record.
## Retention job contract
- **Dry-run first:** dry-run by default; writes a count and a manifest and deletes nothing (`14 §3.2`).
- **Approval:** a live run requires `dry_run_state = 'APPROVED'`, an approver other than the requester, and step-up.
- **Legal hold:** checked explicitly before every delete; held records are excluded and counted.
- **Fail closed:** if the hold check cannot be evaluated, the run aborts and purges nothing.
- **Idempotent:** a replayed run key deletes nothing twice; each run writes a deletion certificate with the rule ID, approver and count, and never deleted content.
- **Identity:** runs as `clinos_retention`, which never holds a privilege on `audit_log`.
## Endpoints
| Method and path | Permission | Step-up | Notes |
| --- | --- | --- | --- |
| `GET /api/v1/admin/{config,feature-flags,tenant-policy,retention-jobs}` | `admin:read` | no | allow-listed; never a secret value |
| `PATCH /api/v1/admin/config` | `admin:configure` | yes, 5 min | versioned and rollback-able |
| `PATCH /api/v1/admin/feature-flags/{key}` | `admin:feature_flag` | yes, 5 min | approval reference required when `affects_safety_gate` |
| `PATCH /api/v1/admin/tenant-policy/{key}` | `tenant:configure` | yes, 5 min | CSO sign-off for a clinical safety parameter |
| `POST /api/v1/admin/break-glass`, `.../{id}/revoke` | `admin:configure` | yes, 5 min | ticket reference and reason required; revoke ends it early |
| `POST /api/v1/admin/retention-jobs/{id}/dry-run` | `admin:retention:configure` | no | deletes nothing |
| `POST /api/v1/admin/retention-jobs/{id}/approve`, `.../run` | `admin:retention:configure` | yes, 5 min | approver must not be the requester; a live run needs an approved dry run and no hold |

`admin:*` codes are candidates in `20 §12`, not in the 19-permission catalogue (01 OPEN-3).
## Deny-by-default request path
1. Authenticate the session — deny `401` if missing, expired or revoked.
2. Resolve the tenant from the session and set it with `SET LOCAL` — deny if absent.
3. Check the permission in the central policy layer — deny `403` if not granted.
4. Require a resource-bound step-up for the named operations — deny `401` if absent, `403` if the authenticator class is wrong.
5. Enforce the administrative rate limit — deny `429`.
6. Validate the body against a strict schema; unknown fields, including `tenant_id`, are rejected `422`.
7. Enforce the domain rule: approval reference for a safety flag, CSO sign-off for a clinical parameter, ticket and reason for break-glass, an approved dry run for a live retention run.
8. Audit the decision, including every refusal, in the same transaction as the change.
9. Execute inside the RLS-scoped transaction and return the versioned result.
## Failure behaviour
- An absent required configuration key refuses startup and names the key; the value is never logged.
- An unreachable flag or policy store fails closed: the gate keeps enforcing, because a safety-gate flag has no disabled state.
- A cache entry is keyed on `(tenant_id, key, version)`, invalidated on write, and an unknown flag resolves to the enforcing default — a stale cached flag can never weaken a control.
- An audit write failure aborts the change (`503`); nothing commits without its event.
- Errors use the standard envelope with a request ID and leak no configuration value, secret or stack trace.

Open items are in `01-requirements.md`.
