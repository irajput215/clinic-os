---
doc_id: OZ-FEAT-15-REQ
title: "Administration and configuration — requirements"
owner: CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-15
phase: 04-phase-4-pilot-go-live
gate: [4]
source:
  - clinic-os-secure-by-design/21-technical-design.md §10
  - clinic-os-secure-by-design/06-authentication-rbac.md §8, §11–§12
  - clinic-os-secure-by-design/02-security-architecture.md §1 control 12, §6, §11
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md §4
  - clinic-os-secure-by-design/14-retention-and-deletion.md §3, §5
  - clinic-os-secure-by-design/20-product-requirements.md §12
  - clinic-os-secure-by-design/22-user-stories.md US-01, US-03, US-09
  - clinic-os-secure-by-design/03-threat-model.md §11
  - clinic-os-secure-by-design/26-security-gates.md §5 Gate 4
repo_docs:
  - 01-requirements.md
  - 03-design.md
---

# Administration and configuration: requirements

## Purpose
Own the administrative surface that changes platform and tenant configuration: versioned feature flags,
the configuration resolver, tenant policy (including the clinical-safety confidence thresholds) and the
retention-job contract. Source: `21-technical-design.md` §10; `20-product-requirements.md` §12. This
module is the only writer of these tables; the prescription safety gate (feature 10) is a reader.

## Non-negotiable rule
**No configuration value and no feature flag may disable, bypass or weaken the prescription safety
gate.** A flag that affects the gate requires an approval reference and step-up and may only ever be
enabled; its disabled state is unrepresentable (R5).

## Requirements and test traceability

| ID | Requirement | Testable acceptance | Source | Evidence |
| --- | --- | --- | --- | --- |
| **R1** | Admin configuration and flag writes are scoped to the session tenant; a `tenant_id` in the body is rejected | Unknown field returns `422`; a forged `tenant_id` writes to the caller's tenant and raises a denial event | `21 §10`; `05 §4` | S7, S9 |
| **R2** | Configuration precedence is `process environment → secret store → fail closed`; no permissive default exists | An absent required key refuses startup with `ERR_CONFIG_REQUIRED_KEY_ABSENT` naming the key; resolution order is asserted | `21 §10` | F6, F7 |
| **R3** | No secret value is stored or returned; secrets are referenced by ARN | Columns hold an ARN only; every admin response is allow-listed; a secret never appears in a body, log, image or bundle | `02 §6`; `20 §12` | S10 |
| **R4** | Feature flags are stored and versioned; each version records the actor, timestamp and approval reference | Version increments per change; a history row is written in the same transaction | `21 §10` | F1, A1 |
| **R5** | A flag affecting the safety gate requires an approval reference and step-up and can never disable the gate | Missing approval reference `422`; missing step-up `401`; a disable attempt `422 ERR_SAFETY_GATE_FLAG_IMMUTABLE` | `20 §12`; `26 §5 Gate 4` | F2, F3, S19 |
| **R6** | `tenant_policy.tga_inbox_confidence_threshold` is a clinical safety parameter requiring CSO sign-off | A change without `cso_signoff_reference` returns `422`; the change needs `tenant:configure` plus step-up and is audited | `11 §4` | F4, S3 |
| **R7** | Break-glass is short-lived, scoped, time-bounded, dual-notified, reason-required and fully audited | A grant without a reason or ticket returns `422`; the elevation expires automatically at `expires_at`; both the practice owner and the Security Lead are notified | `06 §8`; `22 US-03` | F8, F9, S13, S14 |
| **R8** | Retention jobs are dry-run capable and idempotent and check legal hold explicitly before acting | Default is dry-run; a live run requires `dry_run_state = 'APPROVED'`; a replayed run key deletes nothing twice | `14 §3.2` | F10, F11, F12 |
| **R9** | A retention run aborts rather than purging when the legal-hold check cannot be evaluated | An unavailable hold check aborts the run, deletes zero rows and records `FAILED` | `14 §3.2` rule 6 | S16 |
| **R10** | Step-up (passkey or hardware key, 5 minutes, single use) is required for named admin operations; TOTP is excluded for security-configuration changes | Missing step-up `401`; TOTP-only step-up `403`; the token is resource-bound and consumed on use | `06 §8` | S3, S4, S5 |
| **R11** | Administrator routes are rate limited to 20 requests per minute per session | The 21st request in a minute returns `429` with `Retry-After` and is audited | `02 §11` | S17 |
| **R12** | Every admin table carries RLS with `FORCE ROW LEVEL SECURITY` and the `NULLIF` guard | A missing tenant setting returns zero rows; a forged tenant write is refused by `WITH CHECK` | `05 §4` | S7, S8 |
| **R13** | Cross-tenant access returns `404`, never `403`; denials and failures are audited with equal fidelity | Tenant B requesting a tenant A flag id returns `404` and an audited denial | `06 §12` | S6, A2 |
| **R14** | Flag, configuration and tenant-policy history is append-only by grant | `information_schema.role_table_grants` shows `{SELECT, INSERT}`; `UPDATE`/`DELETE`/`TRUNCATE` raise `42501` | `07 §3` | S11 |
| **R15** | A configuration change is versioned and rollback-able to the previous version | Rollback writes the prior values as a new version and is audited | `20 §12` | F13 |
| **R16** | The retention job runs as a dedicated role that can never delete the audit trail | `clinos_retention` holds no privilege on `audit_log` or the admin tables, and deletes only where `04 §6` permits | `14 §3.2` rule 7 | S12 |

F/S/A IDs resolve to the exact `cd backend && uv run pytest tests/... -v` commands in
`06-test-plan.md`.

## Out of scope
- Authentication mechanics: login, MFA enrolment, sessions, step-up token minting (feature 02).
- Role and permission change, and the permission catalogue itself (feature 03).
- The safety-gate decision function and its negative matrix (feature 10).
- Inbox extraction and confidence scoring; this feature owns the threshold value, not the scoring
  (feature 09).
- Notification transport and delivery (operations and observability).
- Secret rotation mechanics (`02 §6`; deployment), and the DSAR workflow (feature 14).

## Open items
| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | `tenant_policy.tga_inbox_confidence_threshold` is required by `11 §4` in Phase 2, but this module is Phase 4 (`docs/reference/build-contract.md` §7; Phase 2 risk R5) — ingestion cannot be configured without it | Head of Platform | OPEN — blocks R6 |
| OPEN-2 | `07-audit-architecture.md` §1 has no `configuration.changed`, `feature_flag.changed`, `AUTH_BREAK_GLASS_GRANTED`, `retention.job_run` or `tenant_policy.changed`; doc 07 §1 forbids a module inventing an action name without adding it there first | Security Lead + Compliance Lead | OPEN — blocks R6, R7, R8 |
| OPEN-3 | The `admin:*` permission codes come from `20 §12` and are candidates in feature 03 OPEN-1, not granted permissions | CTO + Security Lead | OPEN — blocks R1, R3, R11 |
| OPEN-4 | Which flags are on the safety-gate allowlist, and who may approve a change to one | Clinical Safety Officer + CTO | OPEN — blocks R5 |
| OPEN-5 | Whether platform-scope (non-tenant) flags exist, and how they are authorised; `20 §12` requires platform-scope administration but `05-tenant-isolation.md` defines no platform RLS context | CTO | OPEN |
| OPEN-6 | Retention consequences, legal-hold ownership and the retention period for configuration and flag history | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
