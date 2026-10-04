---
doc_id: FEAT-FOUND-06
title: Foundations, test plan
owner: Security Lead + Head of Platform
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
next_review: 2026-11-04
related: 23-sprint-plan, 26-security-gates, 02-security-architecture
source:
  - clinic-os-secure-by-design/23-sprint-plan.md §2, §7
  - clinic-os-secure-by-design/26-security-gates.md §1, §2
  - clinic-os-secure-by-design/27-security-testing.md
  - clinic-os-secure-by-design/28-aws-network-and-deployment.md §7, §10
  - clinic-os-secure-by-design/29-operations-and-observability.md §8.3
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI on synthetic data. A failing security test blocks merge. Every row below carries
its **exact command** — a test name without a command is not evidence
(`docs/features/README.md` audit standard).

```bash
# Whole foundations suite
cd backend && uv run pytest tests/foundations tests/security -v
```

## Functional tests

| ID | Case | Expected result | Command (exact) |
| --- | --- | --- | --- |
| **F1** | Required key absent at startup | non-zero exit, message names the key, no request served | `cd backend && uv run pytest tests/foundations/test_config_fail_closed.py::test_missing_required_key_refuses_startup -v` |
| **F2** | Placeholder value (`changethis`) in a non-development environment | startup refused; no warning-only path | `cd backend && uv run pytest tests/foundations/test_config_fail_closed.py::test_placeholder_secret_refuses_startup_in_every_environment -v` |
| **F3** | `FASTAPI_ENV=development` with a placeholder secret | still refused; the development switch cannot disable the check | `cd backend && uv run pytest tests/foundations/test_config_fail_closed.py::test_development_env_cannot_bypass_secret_check -v` |
| **F4** | Configuration key present only in the environment | loaded; precedence order honoured | `cd backend && uv run pytest tests/foundations/test_config_fail_closed.py::test_process_environment_precedence -v` |
| **F5** | Missing required key in the middle of a key set | all missing keys reported in the failure, none defaulted | `cd backend && uv run pytest tests/foundations/test_config_fail_closed.py::test_all_missing_keys_reported -v` |
| **F6** | `.env` tracked in git | failure: the file must be untracked and ignored | `cd backend && uv run pytest tests/foundations/test_secret_hygiene.py::test_root_env_is_not_tracked_in_git -v` |
| **F7** | `.env.example` content | every required key name present, **no secret value** | `cd backend && uv run pytest tests/foundations/test_secret_hygiene.py::test_env_example_has_names_and_no_values -v` |
| **F8** | Image definition | three images; multi-stage; digest-pinned base; no floating tag | `cd backend && uv run pytest tests/foundations/test_docker_hardening.py::test_three_images_multistage_and_digest_pinned -v` |
| **F9** | Runtime container user | explicit `USER`, non-zero uid | `cd backend && uv run pytest tests/foundations/test_docker_hardening.py::test_runtime_stage_sets_non_root_user -v` |
| **F10** | Read-only root filesystem | `read_only` set with an explicit writable `tmp`, or a listed exception | `cd backend && uv run pytest tests/foundations/test_docker_hardening.py::test_read_only_root_filesystem_or_listed_exception -v` |
| **F11** | Health checks | liveness and readiness declared for each service | `cd backend && uv run pytest tests/foundations/test_docker_hardening.py::test_liveness_and_readiness_declared_per_service -v` |
| **F12** | Build context | `.dockerignore` excludes `.git`, `.venv`, `node_modules`, build/test output and `.env` | `cd backend && uv run pytest tests/foundations/test_docker_hardening.py::test_dockerignore_excludes_env_and_vcs -v` |
| **F13** | Pipeline stage order | the eleven stages exist in the fixed order, as separate steps | `cd backend && uv run pytest tests/foundations/test_ci_pipeline_contract.py::test_pipeline_defines_fixed_stage_order -v` |
| **F14** | Pipeline triggers and required checks | runs on pull request and main; checks match branch protection | `cd backend && uv run pytest tests/foundations/test_ci_pipeline_contract.py::test_pipeline_runs_on_pr_and_main -v` |
| **F15** | Resource limits | CPU and memory limits present; backend and worker profiles differ | `cd backend && uv run pytest tests/foundations/test_docker_hardening.py::test_resource_limits_per_service -v` |

## Security tests

| ID | Case | Expected result | Command (exact) |
| --- | --- | --- | --- |
| **S1** | **Planted secret fixture** in a tracked file | the `secret scan` stage fails and blocks the run | `cd backend && uv run pytest tests/foundations/test_pipeline_blocks_bad_fixture.py::test_planted_secret_blocks_secret_scan_stage -v` |
| **S2** | **Planted vulnerable dependency fixture** in the lockfile | the `dependency scan` stage fails and blocks the run | `cd backend && uv run pytest tests/foundations/test_pipeline_blocks_bad_fixture.py::test_planted_vulnerable_dependency_blocks_dependency_scan -v` |
| **S3** | **Planted type error fixture** in application code | the `typecheck` stage (mypy) fails **before** `unit` runs | `cd backend && uv run pytest tests/foundations/test_pipeline_blocks_bad_fixture.py::test_planted_type_error_blocks_typecheck_stage -v` |
| **S4** | Critical image finding | build and deploy blocked; severity threshold enforced | `cd backend && uv run pytest tests/foundations/test_ci_pipeline_contract.py::test_critical_finding_blocks_build_and_deploy -v` |
| **S5** | Working-tree and full-history secret scan | zero findings in the tree; history findings are reported, not hidden | `cd backend && uv run pytest tests/foundations/test_secret_hygiene.py::test_gitleaks_working_tree_and_history_report -v` |
| **S6** | Committed secrets rotated | old `SECRET_KEY`/`POSTGRES_PASSWORD` values no longer authenticate | `cd backend && uv run pytest tests/foundations/test_secret_hygiene.py::test_committed_secret_values_are_rotated -v` |
| **S7** | `SECRET_KEY` value in a log or error payload | no secret value in a log line, response body or stack trace | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_no_secret_value_in_logs_or_errors -v` |
| **S8** | **Grant inspection:** app role owns no table and holds no `BYPASSRLS` | non-owner and `rolbypassrls = false` for `clinos_app` | `cd backend && uv run pytest tests/security/test_app_role_has_no_bypassrls.py::test_app_role_not_owner_and_no_bypassrls -v` |
| **S9** | Append-only grant on the audit table | `{SELECT, INSERT}` only; live `UPDATE`/`DELETE`/`TRUNCATE` raise `42501` | `cd backend && uv run pytest tests/security/test_app_role_has_no_bypassrls.py::test_audit_table_is_append_only_by_grant -v` |
| **S10** | Static check: no security scanner in any workflow | fails today; passes only once the eleven stages exist | `cd backend && uv run pytest tests/foundations/test_ci_pipeline_contract.py::test_no_workflow_lacks_security_scanning -v` |
| **S11** | Static check: all workflow actions and scanner images pinned | every `uses:` is SHA-pinned; no floating tag | `cd backend && uv run pytest tests/foundations/test_ci_pipeline_contract.py::test_workflow_actions_are_pinned -v` |
| **S12** | Environment namespacing | a Development value cannot be loaded as a Production value | `cd backend && uv run pytest tests/foundations/test_config_fail_closed.py::test_environment_namespacing_prevents_cross_load -v` |
| **S13** | Secret-store interface boundary | application imports the interface, never the store SDK | `cd backend && uv run pytest tests/foundations/test_secret_hygiene.py::test_application_uses_secret_store_interface_only -v` |
| **S14** | Error contract | every error body matches the standard shape and leaks no internal detail | `cd backend && uv run pytest tests/security/test_errors_never_leak_internal_detail.py::test_error_envelope_and_no_internal_detail -v` |
| **S15** | Fail-closed authorisation/tenant resolution | an error resolving tenant or permission denies, never continues unscoped | `cd backend && uv run pytest tests/security/test_errors_fail_closed.py::test_tenant_resolution_error_denies -v` |

**How S1–S3 prove the stages are real.** Each fixture is committed on a throwaway branch, the pipeline
is run, the **stage that must catch it** is asserted to fail, and the resulting run id is recorded as
evidence. The fixture is reverted before merge. A stage that passes with its fixture planted is
recorded as a **failed gate check**, not a passing one (`23-sprint-plan.md` §2 exit criteria).

## Audit tests

| ID | Case | Expected result | Command (exact) |
| --- | --- | --- | --- |
| **A1** | CI event written with the full envelope | `ci.pipeline.completed` and `ci.security_stage.failed` carry every envelope field | `cd backend && uv run pytest tests/foundations/test_foundations_audit_events.py::test_ci_events_carry_full_envelope -v` |
| **A2** | Configuration denial audited | `config.validation_failed` records the key **name**, never the value | `cd backend && uv run pytest tests/foundations/test_foundations_audit_events.py::test_config_validation_failure_audited_with_key_name_only -v` |
| **A3** | Refusals audited as successes are | a refused stage keeps `result = DENIED`/`FAILED` with a reason, not silence | `cd backend && uv run pytest tests/foundations/test_foundations_audit_events.py::test_denied_attempts_audited_with_equal_fidelity -v` |
| **A4** | Audit write fails | the audited operation does not complete (fail closed) and an alert fires | `cd backend && uv run pytest tests/foundations/test_foundations_audit_events.py::test_audit_write_failure_blocks_operation -v` |

## Traceability

- **F1–F15 → R1–R30.** F1–F5 → R1–R4; F6–F7 → R5; F8–F12, F15 → R16–R24; F13–F14 → R11, R13, R15, R29.
- **S1–S15 → threats.** S1–S5, S7 → T-F1, T-F2; S4, S11 → T-F3; S10 → T-F2; S6, S13 → T-F1; S8, S9 →
  T-F4; S12 → T-F5; F1–F4, S6 → T-F6; S1–S3 → T-F7.
- **A1–A4 → events** in `05-data-and-audit.md`: A1 → `ci.*`; A2 → `config.validation_failed`;
  A3 → the denial events; A4 → the append-only guarantee.
- **R5, R6, R12, S1–S3, S10** are the two verified repo defects: the tracked `.env` holding
  `changethis` secrets, and the absence of any security scanning across all 15 workflows.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Where the S1–S3 fixture runs (a dedicated workflow on a throwaway branch vs a pipeline self-test) | Security Lead + Head of Platform | OPEN |
| Which scanner version is pinned, and who reviews the pin (`ADR-004` F3) | Security Lead | OPEN |
| `A1`–`A4` depend on the `audit_log` table from feature 04, which does not exist yet | CTO | OPEN — blocks Done |
| Severity threshold per stage and the suppression approval path | Security Lead | OPEN |
