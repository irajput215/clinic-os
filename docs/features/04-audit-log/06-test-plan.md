---
doc_id: FEAT-AUD-06
title: Audit log, test plan
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 07-audit-architecture, 21-technical-design, 26-security-gates
source:
  - clinic-os-secure-by-design/07-audit-architecture.md §10, §11, §12
  - clinic-os-secure-by-design/04-database-erd.md §9
  - clinic-os-secure-by-design/26-security-gates.md §3
  - clinic-os-secure-by-design/27-security-testing.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI on synthetic data against a real PostgreSQL with RLS enabled. A failing security
test blocks merge.

```bash
cd backend && uv run pytest tests/audit tests/security/test_audit_append_only_grants.py tests/security/test_audit_hash_chain.py tests/security/test_no_phi_in_log_payload.py -v
```

## Functional tests

| ID | Case | Expected result | Verified by |
| --- | --- | --- | --- |
| **F1** | Write an event inside a domain transaction | Domain change and audit row commit together; exactly one event | `cd backend && uv run pytest tests/audit/test_write_path.py::test_audit_writes_in_same_transaction -v` |
| **F2** | Roll back the domain transaction | No `audit_log` row and no outbox row survive | `cd backend && uv run pytest tests/audit/test_write_path.py::test_rollback_leaves_no_orphan_event -v` |
| **F3** | Emit each action in the doc 07 §1 catalogue at its trigger | Coverage test asserts every action is produced; no action outside the catalogue | `cd backend && uv run pytest tests/audit/test_coverage.py::test_mandatory_event_catalogue_covered -v` |
| **F4** | Validate an event against the envelope | All fifteen envelope fields present; `result` ∈ `{SUCCESS, DENIED, FAILED, UNKNOWN}` | `cd backend && uv run pytest tests/audit/test_envelope.py::test_envelope_is_fixed_and_complete -v` |
| **F5** | Write a failed and a denied operation | `auth.login_failed` / `prescription.dispatch_blocked` written with a reason code and `result = DENIED` or `FAILED` | `cd backend && uv run pytest tests/audit/test_coverage.py::test_denied_and_failed_attempts_audited -v` |
| **F6** | First event in a tenant chain | `prev_hash` is 64 zeroes; `hash` matches the canonical recomputation | `cd backend && uv run pytest tests/audit/test_hash_chain.py::test_hash_chain_links_consecutive_events -v` |
| **F7** | Read with filters and keyset pagination | Default 50, max 200, opaque cursor; `(timestamp, event_id)` ordering | `cd backend && uv run pytest tests/audit/test_read_api.py::test_read_pagination_and_filters -v` |
| **F8** | Read with no filter and a range over 90 days | `422 Unprocessable Entity`; unbounded scan refused | `cd backend && uv run pytest tests/audit/test_read_api.py::test_unbounded_scan_and_wide_range_refused -v` |
| **F9** | Every audit read, including an empty result | One `audit.read` event with `query_filters` and `result_count` | `cd backend && uv run pytest tests/audit/test_read_api.py::test_audit_read_is_itself_audited -v` |
| **F10** | Export a range | Tenant-scoped CSV/JSONL bundle; short-lived presigned URL; `audit.read` with `reason = EXPORT` | `cd backend && uv run pytest tests/audit/test_export.py::test_export_bundle_is_tenant_scoped -v` |
| **F11** | Stream committed events through the outbox | Every committed event appears exactly once in the immutable store after the writer drains | `cd backend && uv run pytest tests/audit/test_export.py::test_outbox_streams_every_committed_event -v` |
| **F12** | Partition drop under legal hold | Refused; the hold and the release are audit events | `cd backend && uv run pytest tests/audit/test_retention.py::test_legal_hold_blocks_partition_drop -v` |

## Security tests

| ID | Case | Expected result | Verified by |
| --- | --- | --- | --- |
| **S1** | Cross-tenant read: auditor at A queries B identifiers | `200` with zero rows; no B row, not even as a count | `cd backend && uv run pytest tests/isolation/test_audit_isolation.py::test_cross_tenant_audit_read_returns_empty -v` |
| **S2** | Cross-tenant event id lookup | `404 Not Found`, never `403` | `cd backend && uv run pytest tests/isolation/test_audit_isolation.py::test_cross_tenant_event_id_returns_404 -v` |
| **S3** | Tenant setting unset on the connection | Zero rows (fail closed via `NULLIF`), not all rows | `cd backend && uv run pytest tests/isolation/test_audit_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` |
| **S4** | Connection-pool reuse across two tenants | No context or session leakage | `cd backend && uv run pytest tests/isolation/test_pool_reuse.py::test_pool_reuse_no_tenant_leak -v` |
| **S5** | Role × endpoint matrix on `/api/v1/audit` | Only `audit:read` roles succeed; refusals audited | `cd backend && uv run pytest tests/security/test_audit_rbac.py::test_audit_role_endpoint_matrix -v` |
| **S6** | Unauthenticated or expired session | `401 Unauthorized` | `cd backend && uv run pytest tests/security/test_audit_rbac.py::test_audit_unauthenticated_returns_401 -v` |
| **S7** | Unknown or forbid-extra filter field | `422`; mass assignment blocked | `cd backend && uv run pytest tests/security/test_audit_validation.py::test_audit_filter_mass_assignment_rejected -v` |
| **S8** | Filter value containing SQL, newline and control characters | Parameterised; no injection; serialiser escapes it and the JSONL boundary holds | `cd backend && uv run pytest tests/security/test_audit_validation.py::test_audit_filter_injection_and_log_injection_rejected -v` |
| **S9** | Audit read rate limit exceeded | `429 Too Many Requests` | `cd backend && uv run pytest tests/security/test_audit_rate_limits.py::test_audit_read_rate_limit -v` |
| **S10** | Response and log payload inspection after a full audit read | Zero `HIGHLY_SENSITIVE` value, zero clinical value, zero secret in logs, traces or error telemetry | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_no_clinical_value_in_audit_payload -v` |

## The strongest evidence set — SQL grant, ownership and immutability suite (Gate 2)

Command: `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py -v`
Source: `07-audit-architecture.md` §3, §12 tests 1–2; `04-database-erd.md` §9; Gate 2.

| ID | Case | Expected result | Verified by |
| --- | --- | --- | --- |
| **S12a** | Inspect `information_schema.role_table_grants` for grantee `clinos_app` on `audit_log` after every migration | The privilege set is **exactly `{SELECT, INSERT}`**; no `UPDATE`, `DELETE` or `TRUNCATE` | `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py::test_app_role_has_exactly_select_insert -v` |
| **S12b** | App role attempts direct `UPDATE audit_log SET reason = 'tampered'` | `42501 insufficient_privilege`; the statement is refused by the engine | `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py::test_app_role_cannot_update_audit_log -v` |
| **S12c** | App role attempts direct `DELETE FROM audit_log` | `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py::test_app_role_cannot_delete_audit_log -v` |
| **S12d** | App role attempts direct `TRUNCATE audit_log` | `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py::test_app_role_cannot_truncate_audit_log -v` |
| **S12e** | Inspect `pg_class.relowner` and `pg_roles.rolbypassrls` for `audit_log` and `clinos_app` | The app role **is not the table owner** and has **no `BYPASSRLS`**; `clinos_readonly_audit` holds `SELECT` only | `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py::test_app_role_is_not_owner_and_has_no_bypassrls -v` |
| **S12f** | No `UPDATE` or `DELETE` policy exists on `audit_log`; `FORCE ROW LEVEL SECURITY` is set | Zero such policies in `pg_policies`; the owner role sees only its tenant's rows | `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py::test_no_update_or_delete_policy_and_force_rls -v` |
| **S12g** | Repository lint rule over the source tree | Build fails on any `UPDATE audit_log` or `DELETE FROM audit_log` string | `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py::test_no_update_or_delete_statement_in_source -v` |
| **S12h** | Business write whose audit insert raises | The business operation **rolls back**; `500` with a request ID; no domain change survives; alert raised | `cd backend && uv run pytest tests/security/test_audit_append_only_grants.py::test_audit_write_failure_rolls_back_business_operation -v` |
| **S13** | Hash-chain verification after a direct SQL modification of one row's `reason` by the migrator role | The verifier reports a break at that sequence number | `cd backend && uv run pytest tests/security/test_audit_hash_chain.py::test_hash_chain_verification_detects_a_modified_row -v` |
| **S14** | Hash-chain verification after a row is deleted | The `prev_hash` linkage breaks and the verifier reports a break | `cd backend && uv run pytest tests/security/test_audit_hash_chain.py::test_hash_chain_verification_detects_a_deleted_row -v` |
| **S15** | Sentinel test: inject a known clinical sentinel value (`PATIENT_NAME_SENTINEL`, `MEDICINE_SENTINEL`, `DIRECTIONS_SENTINEL`) through a clinical endpoint | No sentinel value appears anywhere in the audit payload, the outbox, the exported JSONL, log lines, error bodies or traces | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_sentinel_clinical_value_never_reaches_audit_payload -v` |
| **S16** | `metadata` key not on the per-action allow-list | Insert throws; request fails `500 AUDIT_PAYLOAD_REJECTED`; no partial row | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_payload_allowlist_rejects_clinical_content -v` |

## Audit evidence

| ID | Case | Expected |
| --- | --- | --- |
| A1 | Each successful audited operation | One event with the full envelope, action from the catalogue |
| A2 | Each refusal | An event with `result = DENIED` and a controlled reason code |
| A3 | Audit write fails | The operation does not complete; rollback; SEV2 alert |
| A4 | Export is written | `audit.read` with `reason = EXPORT`, filters and result count |

## Traceability

F1–F12 cover R1, R3–R8, R12 and R13. S1–S16 cover the security criteria in
[`02-user-stories.md`](02-user-stories.md) and the controls in [`04-threat-model.md`](04-threat-model.md):
S12a–S12d cover R1, R2 and R15; S12h covers R4; S13–S14 cover R8; S15–S16 cover R11. A1–A4 cover the
event catalogue and retention behaviour in [`05-data-and-audit.md`](05-data-and-audit.md). R9 (continuous
verification) and R10/R14 (immutable export and RLS policy inspection) are evidenced by the scheduled
verification report and the policy listing taken at Gate 2.
