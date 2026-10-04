---
doc_id: FEAT-PAT-06
title: Patients, test plan
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Test plan

All tests run in CI on synthetic data. A failing security test blocks merge. Stack: Python 3.14 /
FastAPI / Pydantic v2 / SQLModel / psycopg3 / Alembic / pytest.

```bash
cd backend && uv run pytest tests/patients tests/isolation/test_patients_isolation.py tests/security/test_patient_grants.py -v
```

## Functional

| ID | Case | Expected result | Verified by (pytest) |
|---|---|---|---|
| **F1** | Create with a valid body | `201`; `tenant_id` from the session | `tests/patients/test_lifecycle.py::test_create_patient_valid` |
| **F2** | Body carries `tenant_id`, `deleted_at` or `merged_into_patient_id` | `422`; zero rows written | `tests/security/test_validation_rejects_unknown_field.py::test_patient_body_extra_fields_rejected` |
| **F3** | Identifier value fails shape validation | `422` before any query is issued | `tests/patients/test_identifiers.py::test_identifier_validation_before_database` |
| **F4** | Duplicate: same name + DOB match | `409` with candidate and reason `NAME_DOB_MATCH` | `tests/patients/test_duplicates.py::test_name_dob_match_returns_candidate` |
| **F5** | Duplicate: same Medicare blind index | `409` with candidate and reason `MEDICARE_EXACT_MATCH` | `tests/patients/test_duplicates.py::test_medicare_blind_index_match_returns_candidate` |
| **F6** | Duplicate: same IHI blind index | `409` with candidate and reason `IHI_EXACT_MATCH` | `tests/patients/test_duplicates.py::test_ihi_blind_index_match_returns_candidate` |
| **F7** | Duplicate: no two-identifier match | `201`; no candidate returned | `tests/patients/test_duplicates.py::test_no_match_creates_patient` |
| **F8** | Exact identifier lookup | Returns the single matching patient in the tenant | `tests/patients/test_identifiers.py::test_blind_index_exact_match_only` |
| **F9** | Prefix or fuzzy identifier lookup | No match (field is encrypted; equality only) | `tests/patients/test_identifiers.py::test_identifier_prefix_and_fuzzy_return_nothing` |
| **F10** | Update demographics | `200`; only changed fields written | `tests/patients/test_lifecycle.py::test_update_changed_fields_only` |
| **F11** | Merge two records with reason and step-up | Losing record linked; both identifiers preserved | `tests/patients/test_merge.py::test_merge_preserves_both_identifiers` |
| **F12** | Reverse a merge | Both records restored exactly; lineage readable | `tests/patients/test_merge.py::test_merge_reverse_round_trip` |
| **F13** | Search by name | `POST` body only; `GET ...?q=` not routed | `tests/patients/test_search.py::test_search_is_post_body_only` |
| **F14** | Bulk export with step-up and reason | Output tenant-scoped; `record_count` exact | `tests/security/test_patient_export.py::test_bulk_export_step_up_and_purpose` |

## Security

| ID | Case | Expected result | Verified by (pytest) |
|---|---|---|---|
| **S1** | Tenant A lists patients while B has matching rows | B's rows **absent**; `200`, empty (I-002) | `tests/isolation/test_patients_isolation.py::test_cross_tenant_list_and_search_absent` |
| **S2** | Tenant A searches a term matching a B patient | B's row absent from results and snippets (I-025) | `tests/isolation/test_patients_isolation.py::test_cross_tenant_search_absent` |
| **S3** | Tenant A requests B's patient id | `404`, no body fields, denial audited (I-001) | `tests/isolation/test_patients_isolation.py::test_cross_tenant_get_returns_404` |
| **S4** | Tenant A PATCHes B's patient | `404`; B's row unchanged; denial audited (I-003) | `tests/isolation/test_patients_isolation.py::test_cross_tenant_update_returns_404` |
| **S5** | Raw SQL as app role with no tenant filter | Only the caller's rows (I-016) | `tests/isolation/test_patients_isolation.py::test_rls_holds_without_app_filter` |
| **S6** | No `app.tenant_id` on the connection | Zero rows, no error; fail closed (I-017) | `tests/isolation/test_patients_isolation.py::test_missing_tenant_setting_returns_zero_rows` |
| **S7** | Forged `tenant_id` write | Rejected by `WITH CHECK` (I-018) | `tests/isolation/test_patients_isolation.py::test_with_check_blocks_cross_tenant_insert` |
| **S8** | Cache warmed for A, read as B | Cache miss for B (I-023) | `tests/isolation/test_patients_isolation.py::test_cache_tenant_namespace_isolation` |
| **S9** | Export job run as A while B matches | Only A's rows; count asserted (I-027) | `tests/isolation/test_patients_isolation.py::test_export_job_tenant_scoped` |
| **S10** | `patient:read` without a treating relationship | `403 AUTHZ_CARE_RELATIONSHIP_DENIED`; denial audited | `tests/patients/test_access.py::test_read_outside_care_relationship_denied` |
| **S11** | Merge without step-up / without `patient:merge` | `401 AUTH_STEP_UP_REQUIRED` / `403`; no state change | `tests/patients/test_merge.py::test_merge_requires_step_up` |
| **S12** | Wildcard abuse: `%` and `_` in a name filter | Escaped; result set not widened beyond the match | `tests/security/test_patient_search_abuse.py::test_like_wildcards_escaped` |
| **S13** | Search scraping: repeated broad queries | `429` after the per-identity rate limit; attempt audited | `tests/security/test_patient_search_abuse.py::test_search_rate_limit_and_audit` |
| **S14** | Identifier masking in responses and logs | Masked value in the response; sentinel absent from logs and error bodies | `tests/security/test_patient_masking.py::test_identifiers_masked_in_response_and_logs` |
| **S15** | App role attempts `DELETE FROM patients` | `42501 permission denied`; row still present | `tests/security/test_patient_grants.py::test_app_role_has_no_delete_on_patients` |
| **S16** | Grant inspection after migrations | `clinos_app` holds `{SELECT, INSERT, UPDATE}` and **no `DELETE`/`TRUNCATE`** on `patients` | `tests/security/test_patient_grants.py::test_patient_grants_exact` |
| **S17** | Denied and failed attempts audited | Each denial writes an event with `result=DENIED`, same fidelity as success | `tests/patients/test_audit.py::test_denials_audited_with_equal_fidelity` |
| **S18** | Role × endpoint matrix for patient routes | Only authorised roles succeed; others audited | `tests/security/test_patient_rbac.py::test_patient_role_endpoint_matrix` |

## Detailed specification: grant inspection & no-hard-delete (Gate 2)

* **Command:** `cd backend && uv run pytest tests/security/test_patient_grants.py -v`
* **Source:** `04-database-erd.md` §6, §9; `05-tenant-isolation.md` §4; Gate 2 (no conditional pass).

```python
def test_patient_grants_exact(db_admin_role, db_app_role):
    grants = db_admin_role.execute("""
        SELECT privilege_type FROM information_schema.role_table_grants
        WHERE grantee = 'clinos_app' AND table_name = 'patients'
    """).fetchall()
    privileges = {g.privilege_type for g in grants}

    assert privileges == {"SELECT", "INSERT", "UPDATE"}, f"Grant leak: {privileges}"
    assert "DELETE" not in privileges, "DELETE granted on patients!"
    assert "TRUNCATE" not in privileges, "TRUNCATE granted on patients!"

    with pytest.raises(DBAPIError) as exc:
        db_app_role.execute("DELETE FROM patients WHERE id = :id", {"id": fake_patient_id})
    assert "permission denied" in str(exc.value).lower()
```

## Audit

| ID | Case | Expected |
|---|---|---|
| A1 | Each successful create/read/update/merge/reverse/export | one matching event with the full envelope |
| A2 | Each refusal (tenant, permission, relationship, validation) | event with `result=DENIED` and a controlled reason |
| A3 | Audit write fails | action does not complete (fail closed); alert raised |

## Gap note: identifier check-digit algorithm
The source contract specifies **no** check-digit algorithm (no Modulus-10/Luhn), no IRN rule and no IHI
format. Tests F3, F8 and F9 therefore assert only the boundary — **validation happens before the
database**, per security control 4 (`02-security-architecture.md` §1) — and use synthetic fixtures.
Exact valid/invalid identifier fixtures and the minimum search-query floor are **OPEN /
REQUIRES LEGAL/REGULATORY VALIDATION**.

## Traceability
F1–F14 cover R1–R14 in 01-requirements.md. S1–S18 cover the S: criteria in 02-user-stories.md, the
controls in 04-threat-model.md, and isolation tests I-001…I-004, I-016…I-018, I-023, I-025 and I-027
(`05-tenant-isolation.md` §8). A1–A3 cover the event catalogue in 05-data-and-audit.md.
