---
doc_id: OZ-FEAT-04-TEST
title: "FEAT-04 — TGA Approval Module: Test Plan & Invariant Catalog"
owner: Clinical Safety Officer + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-04
phase: 02-phase-2-tga-approval-engine
gate: [2, 4]
source:
  - clinic-os-secure-by-design/08-tga-approval-model.md §8
  - clinic-os-secure-by-design/09-prescription-safety-gate.md §11
  - clinic-os-secure-by-design/27-security-testing.md §2.3
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI on synthetic data. A failing security test blocks merge.

## Test Execution Suite

```bash
# Run all TGA approval functional, security, and isolation tests
cd backend && uv run pytest tests/tga tests/security/test_tga_append_only_grants.py -v
```

## Functional Tests & Negative Decision Coverage

| ID | Case | Expected Result / Error Code | Verified By (Pytest Function) |
|---|---|---|---|
| **F1** | Create with a valid body | `201 Created`, status `pending_verification` | `tests/tga/test_lifecycle.py::test_create_approval_valid` |
| **F2** | Missing category or dosage form | `422 Unprocessable Entity`, zero rows | `tests/tga/test_lifecycle.py::test_create_approval_rejects_missing_fields` |
| **F3** | `valid_to` > 2 years after `valid_from` | `422 ERR_WINDOW_EXCEEDS_MAX_DURATION` | `tests/tga/test_lifecycle.py::test_approval_window_max_two_years` |
| **F4** | Verify by independent clinical role | `200 OK`, status `active`, `verified_at` set | `tests/tga/test_verification.py::test_verify_by_independent_clinician` |
| **F5** | Revoke with a valid reason code | `200 OK`, status `revoked`, reason audited | `tests/tga/test_lifecycle.py::test_revoke_with_reason_code` |
| **F6** | Invalid transition (`revoked → active`) | `409 Conflict`, code `INVALID_STATE_TRANSITION` | `tests/tga/test_lifecycle.py::test_illegal_transition_returns_409` |
| **F7** | Expiry job runs after `valid_to` | Status updated to `expired` (idempotent) | `tests/tga/test_lifecycle.py::test_expiry_job_updates_expired` |
| **F8** | Overlapping active approval at same grain | Rejected by GiST constraint, `409 TGA_OVERLAPPING_ACTIVE_APPROVAL` | `tests/tga/test_constraints.py::test_tga_overlapping_active_approval_rejected` |
| **F9** | Supersede: new grant replaces active | Old row `active → superseded`, `superseded_by_id` set | `tests/tga/test_lifecycle.py::test_supersede_active_approval_atomic` |
| **F10** | Attempt to modify `valid_to` on verified row | Rejection `VERIFIED_APPROVAL_IMMUTABLE`; extension requires new grant | `tests/tga/test_security.py::test_verified_approval_immutable` |
| **F11** | Match at grain: all 4 dimensions match | Gate returns `ALLOW` | `tests/tga/test_match.py::test_match_all_dimensions_allow` |
| **F12** | Match with wrong category or dosage form | Gate returns `BLOCKED`, code `TGA_CATEGORY_MISMATCH` / `TGA_DOSAGE_FORM_MISMATCH` | `tests/tga/test_match.py::test_match_dimension_mismatch` |
| **F13** | Match on date outside validity interval | Gate returns `BLOCKED`, code `TGA_APPROVAL_EXPIRED` / `TGA_APPROVAL_NOT_YET_EFFECTIVE` | `tests/tga/test_match.py::test_match_outside_window` |
| **F14** | Match boundary at 23:59:59 on `valid_to` | Evaluated strictly against half-open interval `[valid_from, valid_to)` | `tests/tga/test_match.py::test_match_boundary_half_open` |
| **F15** | Read/list approvals by patient | Cursor-paginated, tenant-scoped, `404` on cross-tenant ID | `tests/tga/test_isolation.py::test_read_list_tenant_scoped` |

## Security Test Suite

| ID | Case | Expected Result / Status | Verified By (Pytest Function) |
|---|---|---|---|
| **S1** | Clinic A requests clinic B approval ID | `404 Not Found` (no existence leak) | `tests/isolation/test_tga_isolation.py::test_cross_tenant_approval_returns_404` |
| **S2** | Raw SQL as app role with no tenant filter | Zero foreign tenant rows returned | `tests/isolation/test_tga_isolation.py::test_raw_sql_app_role_sees_zero_foreign_rows` |
| **S3** | Tenant setting missing on DB connection | Zero rows returned (fail-closed, `NULLIF`) | `tests/isolation/test_tga_isolation.py::test_missing_tenant_setting_returns_zero_rows` |
| **S4** | Pool reuse: Tenant A request then Tenant B | Zero context or session leakage | `tests/isolation/test_tga_isolation.py::test_connection_pool_reuse_no_leakage` |
| **S5** | Body includes `tenant_id`, `status`, or `verified_by` | `422 Unprocessable Entity` (mass assignment blocked) | `tests/security/test_tga_validation.py::test_body_mass_assignment_rejected` |
| **S6** | Role × endpoint permission matrix | Only authorized roles succeed; unauthorized audited | `tests/security/test_tga_rbac.py::test_role_endpoint_matrix` |
| **S7** | Creator attempts to self-verify approval | `403 Forbidden` (`VERIFIER_CANNOT_BE_CREATOR`) | `tests/tga/test_verification.py::test_tga_verifier_cannot_be_creator` |
| **S8** | Verify or revoke without recent step-up auth | `401 Unauthorized` (`step_up_required`) | `tests/security/test_tga_auth.py::test_verify_revoke_step_up_enforced` |
| **S9** | Missing or expired session token | `401 Unauthorized` | `tests/security/test_tga_auth.py::test_unauthenticated_request_returns_401` |
| **S10** | Gate lookup negative match (expired/revoked/mismatch) | Dispatch blocked, audited, zero outbound calls | `tests/tga/test_match.py::test_gate_lookup_negative_cases_no_outbound_call` |
| **S11** | Gate lookup encounters DB exception/timeout | Fail-closed (`BLOCKED`, `TGA_GATE_FAIL_CLOSED`) | `tests/tga/test_match.py::test_gate_db_error_fails_closed` |
| **S12a** | Inspect `information_schema.role_table_grants` | `tga_approval_events` has `{SELECT, INSERT}`; `tga_approval` has no `DELETE` | `tests/security/test_tga_append_only_grants.py::test_tga_append_only_and_immutability_grants` |
| **S12b** | App role attempts direct `UPDATE`/`DELETE` on events | `42501 insufficient_privilege` permission denied | `tests/security/test_tga_append_only_grants.py::test_tga_append_only_and_immutability_grants` |
| **S12c** | App role attempts direct `DELETE` on approvals | `42501 insufficient_privilege` permission denied | `tests/security/test_tga_append_only_grants.py::test_tga_append_only_and_immutability_grants` |
| **S12d** | Attempt `UPDATE` on verified approval's core fields | Trigger exception `VERIFIED_APPROVAL_IMMUTABLE` | `tests/security/test_tga_append_only_grants.py::test_tga_append_only_and_immutability_grants` |
| **S13** | Response and log payload inspection | Zero PHI / category values in logs or stack traces | `tests/security/test_no_phi_in_log_payload.py::test_tga_payloads_contain_no_phi` |
| **S14** | Sensitive write rate limit exceeded | `429 Too Many Requests` | `tests/security/test_tga_rate_limits.py::test_sensitive_write_rate_limit` |
| **S15** | Cross-tenant or expired signed document URL | `403 Forbidden` / `404 Not Found` | `tests/security/test_tga_storage.py::test_signed_document_url_tenant_isolated_and_expires` |
| **S16** | Concurrent revocation during gate check | Read `FOR SHARE` ensures atomic block | `tests/tga/test_match.py::test_concurrent_revocation_during_gate_check_blocks` |

---

## Detailed Specification: SQL Grant & Immutability Suite (Gate 2 / Gate 4)

* **Command:** `cd backend && uv run pytest tests/security/test_tga_append_only_grants.py -v`
* **Source:** `07-audit-architecture.md` §3; `04-database-erd.md` §9; Gate 2 checklist.

### Execution & Assertions

```python
def test_tga_append_only_and_immutability_grants(db_app_role, db_admin_role):
    # 1. Inspect information_schema.role_table_grants
    grants = db_admin_role.execute("""
        SELECT table_name, privilege_type 
        FROM information_schema.role_table_grants 
        WHERE grantee = 'clinos_app' 
          AND table_name IN ('tga_approval', 'tga_approval_events')
    """).fetchall()
    
    event_privileges = {g.privilege_type for g in grants if g.table_name == 'tga_approval_events'}
    approval_privileges = {g.privilege_type for g in grants if g.table_name == 'tga_approval'}
    
    # Assert exact grants: audit events are append-only
    assert event_privileges == {"SELECT", "INSERT"}, f"Audit events grant leak: {event_privileges}"
    assert "DELETE" not in approval_privileges, "DELETE granted on tga_approval!"
    assert "TRUNCATE" not in approval_privileges, "TRUNCATE granted on tga_approval!"

    # 2. Assert runtime denial of tampering on audit log
    with pytest.raises(DBAPIError) as exc_update:
        db_app_role.execute("UPDATE tga_approval_events SET reason = 'tampered' WHERE id = :id", {"id": fake_id})
    assert "permission denied" in str(exc_update.value).lower()

    with pytest.raises(DBAPIError) as exc_delete:
        db_app_role.execute("DELETE FROM tga_approval_events WHERE id = :id", {"id": fake_id})
    assert "permission denied" in str(exc_delete.value).lower()

    # 3. Assert runtime denial of hard-delete on approval records
    with pytest.raises(DBAPIError) as exc_app_del:
        db_app_role.execute("DELETE FROM tga_approval WHERE id = :id", {"id": fake_id})
    assert "permission denied" in str(exc_app_del.value).lower()

    # 4. Assert post-verification immutability of active approvals
    active_approval = create_active_approval(db_app_role)
    with pytest.raises(DBAPIError) as exc_mutate:
        db_app_role.execute("""
            UPDATE tga_approval 
            SET valid_to = valid_to + interval '1 year' 
            WHERE id = :id
        """, {"id": active_approval.id})
    assert "VERIFIED_APPROVAL_IMMUTABLE" in str(exc_mutate.value)
```

## Audit

| ID | Case | Expected |
| --- | --- | --- |
| A1 | Each successful action | one matching event with the full envelope |
| A2 | Each refusal | `approval.denied` with a reason |
| A3 | Audit write fails | action does not complete (fail closed), alert raised |

## CI pipeline hooks
Dependency scan, SAST, secret scan, and the S-series tests on every pull request.

## Traceability
F1–F15 cover R1–R13. S1–S16 cover the security criteria in 02-user-stories.md and the controls in
04-threat-model.md. A1–A3 cover the event catalogue in 05-data-and-audit.md.
