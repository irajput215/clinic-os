---
doc_id: OZ-FEAT-15-TEST
title: "Administration and configuration — test plan"
owner: Clinical Safety Officer + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-15
phase: 04-phase-4-pilot-go-live
gate: [4]
source:
  - clinic-os-secure-by-design/26-security-gates.md §5 Gate 4
  - clinic-os-secure-by-design/27-security-testing.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md §5
  - clinic-os-secure-by-design/06-authentication-rbac.md §12, §13
  - clinic-os-secure-by-design/02-security-architecture.md §11
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI against a real PostgreSQL instance with RLS enabled, on synthetic data. A failing
security test blocks merge; a failing safety-gate test is a Critical finding.

## Functional tests

| ID | Case | Expected result | Command |
| --- | --- | --- | --- |
| **F1** | Change a flag | `200 OK`; a version row records `version`, `changed_by`, `changed_at`, `approval_reference` | `cd backend && uv run pytest tests/admin/test_feature_flags.py::test_flag_change_records_version_actor_and_approval_reference -v` |
| **F2** | Change a flag with `affects_safety_gate` and no approval reference | `422 ERR_FLAG_APPROVAL_REFERENCE_REQUIRED`, zero rows written | `cd backend && uv run pytest tests/admin/test_feature_flags.py::test_safety_flag_change_requires_step_up_and_approval_reference -v` |
| **F3** | Disable a reserved safety-gate flag | `422 ERR_SAFETY_GATE_FLAG_IMMUTABLE`; the gate still enforces | `cd backend && uv run pytest tests/admin/test_feature_flags.py::test_safety_gate_flag_cannot_be_disabled -v` |
| **F4** | Change `tga_inbox_confidence_threshold` without a CSO sign-off reference | `422 ERR_CSO_SIGNOFF_REQUIRED`; the prior value is unchanged | `cd backend && uv run pytest tests/admin/test_tenant_policy.py::test_threshold_change_requires_cso_signoff -v` |
| **F5** | Read policy defaults for a new tenant | `tga_inbox_confidence_threshold = 0.950`; `tga_inbox_auto_create_threshold` disabled | `cd backend && uv run pytest tests/admin/test_tenant_policy.py::test_auto_create_threshold_disabled_by_default -v` |
| **F6** | Resolve a key present in both the process environment and the secret store | The process environment wins; the resolution order is recorded | `cd backend && uv run pytest tests/admin/test_config.py::test_config_resolution_precedence_env_then_secret_store -v` |
| **F7** | Start with a required key absent everywhere (fail-closed configuration) | Startup fails closed and refuses with `ERR_CONFIG_REQUIRED_KEY_ABSENT`, **naming the key**; no permissive default is applied | `cd backend && uv run pytest tests/admin/test_config.py::test_missing_required_key_fails_startup_and_names_key -v` |
| **F8** | Request break-glass without a reason or ticket reference | `422`; no elevation issued | `cd backend && uv run pytest tests/admin/test_break_glass.py::test_break_glass_grant_requires_reason_and_ticket -v` |
| **F9** | Let a granted elevation reach `expires_at` | The elevation ends; a request after expiry is refused `401` | `cd backend && uv run pytest tests/admin/test_break_glass.py::test_break_glass_expires_automatically -v` |
| **F10** | Dry-run a retention job | A count and a manifest are written; zero rows deleted; `dry_run_state = 'DRY_RUN_PASSED'` | `cd backend && uv run pytest tests/admin/test_retention_jobs.py::test_retention_dry_run_writes_manifest_and_deletes_nothing -v` |
| **F11** | Run live without `dry_run_state = 'APPROVED'` | `409 ERR_RETENTION_APPROVAL_REQUIRED`; zero rows deleted | `cd backend && uv run pytest tests/admin/test_retention_jobs.py::test_retention_live_run_requires_approved_dry_run -v` |
| **F12** | Replay a completed run key | The replay deletes nothing; the original certificate is unchanged | `cd backend && uv run pytest tests/admin/test_retention_jobs.py::test_retention_job_idempotent_on_replay -v` |
| **F13** | Roll a configuration change back | The prior values are written as a new version and the change is audited | `cd backend && uv run pytest tests/admin/test_config.py::test_config_change_versioned_and_rollback_to_previous_version -v` |

## Security tests

| ID | Case | Expected result | Command |
| --- | --- | --- | --- |
| **S1** | Call an admin route with no session | `401 Unauthorized`; the attempt is audited | `cd backend && uv run pytest tests/admin/test_admin_rbac.py::test_admin_route_requires_authenticated_session -v` |
| **S2** | Call an admin route with a role lacking the permission | `403 Forbidden`; the denial is audited with the full envelope | `cd backend && uv run pytest tests/admin/test_admin_rbac.py::test_admin_route_denies_role_without_permission -v` |
| **S3** | Change a security configuration **without** step-up | `401 step_up_required`; no change is written | `cd backend && uv run pytest tests/admin/test_admin_rbac.py::test_admin_step_up_required_for_security_config_change -v` |
| **S4** | Step up with TOTP only, then change security configuration | `403`; TOTP is excluded for a security-configuration change | `cd backend && uv run pytest tests/admin/test_admin_rbac.py::test_security_config_change_rejects_totp_only_step_up -v` |
| **S5** | Replay a step-up token, and apply it to a different flag | Refused; the token is single use, user-, session-, operation- and resource-bound | `cd backend && uv run pytest tests/admin/test_admin_rbac.py::test_admin_step_up_token_is_single_use_and_resource_bound -v` |
| **S6** | Tenant B requests a tenant A flag, policy or retention job id | `404 Not Found`, never `403`; the attempt is audited | `cd backend && uv run pytest tests/admin/test_isolation.py::test_cross_tenant_admin_resource_returns_404 -v` |
| **S7** | Query an admin table with no tenant setting on the connection | Zero rows, not all rows | `cd backend && uv run pytest tests/admin/test_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` |
| **S8** | Inspect `pg_class` and `pg_policies` for the seven tables | RLS is `ENABLE` and `FORCE`; the policy uses `NULLIF(current_setting('app.tenant_id', true), '')::uuid` | `cd backend && uv run pytest tests/admin/test_isolation.py::test_rls_forced_with_nullif_guard_on_admin_tables -v` |
| **S9** | Send `tenant_id`, `changed_by` or `version` in the body | `422 Unprocessable Entity` (mass assignment blocked, zero rows) | `cd backend && uv run pytest tests/admin/test_admin_rbac.py::test_admin_body_mass_assignment_rejected -v` |
| **S10** | Inspect every admin response and log payload | No secret value, ARN value or credential appears in a body, log line or stack trace | `cd backend && uv run pytest tests/admin/test_config.py::test_admin_endpoints_never_return_secret_value -v` |
| **S11** | Inspect `information_schema.role_table_grants` for the flag and configuration history tables (append-only inspection) | Exactly `{SELECT, INSERT}`; a direct `UPDATE`/`DELETE`/`TRUNCATE` raises `42501` | `cd backend && uv run pytest tests/admin/test_grants.py::test_flag_and_config_history_grants_are_append_only -v` |
| **S12** | Inspect and exercise the `clinos_retention` grants | No privilege on `audit_log` or the admin tables; delete only where `04 §6` permits | `cd backend && uv run pytest tests/admin/test_grants.py::test_retention_role_cannot_delete_audit_or_admin_tables -v` |
| **S13** | Grant break-glass: expiry and dual notification | Exactly two notifications fire — practice owner and Security Lead — and both are recorded | `cd backend && uv run pytest tests/admin/test_break_glass.py::test_break_glass_dual_notification_on_grant -v` |
| **S14** | Attempt to extend or renew an active elevation beyond the window | Refused; no path silently extends `expires_at` | `cd backend && uv run pytest tests/admin/test_break_glass.py::test_break_glass_elevation_cannot_be_extended_indefinitely -v` |
| **S15** | Run a live retention job with a record under legal hold in scope | The held record is excluded, the exclusion is counted, and the record survives | `cd backend && uv run pytest tests/admin/test_retention_jobs.py::test_retention_job_honours_legal_hold -v` |
| **S16** | Make the legal-hold check unavailable, then run | The run aborts, purges nothing, and records `FAILED` | `cd backend && uv run pytest tests/admin/test_retention_jobs.py::test_retention_job_aborts_when_legal_hold_check_unavailable -v` |
| **S17** | Exceed the administrative rate limit | The 21st request in a minute returns `429` with `Retry-After` and is audited | `cd backend && uv run pytest tests/admin/test_rate_limits.py::test_admin_rate_limit_twenty_per_minute -v` |
| **S18** | From the admin surface, grant a permission the actor does not hold, or reach a platform route from a clinical role | `403`; the escalation attempt is audited | `cd backend && uv run pytest tests/admin/test_admin_rbac.py::test_admin_surface_blocks_privilege_escalation -v` |
| **S19** | Serve a stale cached flag value to the safety gate after a change | The gate still enforces; the stale value cannot disable or weaken it | `cd backend && uv run pytest tests/admin/test_feature_flags.py::test_stale_cached_flag_never_disables_safety_gate -v` |
| **S20** | Make the audit write fail during an admin change | The change does not commit; `503`; an alert is raised | `cd backend && uv run pytest tests/admin/test_admin_rbac.py::test_audit_write_failure_aborts_admin_change -v` |

## Audit tests

| ID | Case | Expected result | Command |
| --- | --- | --- | --- |
| **A1** | Perform each successful admin action | One event per action with the full envelope, written in the same transaction | `cd backend && uv run pytest tests/admin/test_audit_events.py::test_admin_actions_emit_full_envelope -v` |
| **A2** | Make a refusal on each admin route, including cross-tenant | A denial event with the same fidelity as a success | `cd backend && uv run pytest tests/admin/test_audit_events.py::test_denied_admin_attempt_audited_with_equal_fidelity -v` |
| **A3** | Run a live retention job | A deletion certificate with rule ID, approver and count, and no deleted content | `cd backend && uv run pytest tests/admin/test_audit_events.py::test_retention_run_writes_deletion_certificate_without_content -v` |

## CI pipeline hooks
Dependency scan, SAST, secret scan and the S-series tests run on every pull request. The grant-inspection
and legal-hold tests (`S11`, `S12`, `S15`, `S16`) are Gate 4 evidence and cannot be waived.

## Traceability
F1–F13 cover R1–R16 of `01-requirements.md`. S1–S20 cover the security criteria in `02-user-stories.md`
and the controls in `04-threat-model.md` (F2/F3/S19 → T-15.1, T-15.2, T-15.7; S15/S16 → T-15.5;
S10 → T-15.9; S14 → T-15.4). A1–A3 cover the event catalogue in `05-data-and-audit.md`.
