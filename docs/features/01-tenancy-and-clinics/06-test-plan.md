---
doc_id: FEAT-TEN-01
title: Tenancy and clinics, test plan
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 04-database-erd, 06-authentication-rbac
---

# Tenancy and clinics: test plan

All tests run in CI on synthetic data with **RLS enabled**. Every test runs as `clinos_app`, never as
the owner or a superuser, and asserts **absence** (`05-tenant-isolation.md` §8). A failing isolation or
security test blocks merge and fails Gate 2.

## How to run

```bash
# Whole tenancy and isolation suite
cd backend && uv run pytest tests/tenancy tests/isolation tests/security/test_tenancy_audit.py tests/security/test_tenant_grants.py -v
```

## Functional tests (F)

| ID | Case | Expected result | Verified by |
|---|---|---|---|
| **F1** | `GET /api/v1/tenants/current` | `200`; the resolved tenant only | `cd backend && uv run pytest tests/tenancy/test_tenants.py::test_get_tenants_current_resolves_from_session -v` |
| **F2** | Body/header/query carries another `tenant_id` | Value ignored; caller's own data returned; denial event written | `cd backend && uv run pytest tests/tenancy/test_tenant_resolution.py::test_supplied_tenant_id_is_ignored_and_audited -v` |
| **F3** | Tenant `status` value outside the vocabulary | `422`; no row written | `cd backend && uv run pytest tests/tenancy/test_tenants.py::test_tenant_status_controlled_vocabulary -v` |
| **F4** | `slug` used as an authorisation input | Refused; slug never substitutes for the resolved tenant | `cd backend && uv run pytest tests/tenancy/test_tenant_resolution.py::test_slug_is_not_an_authorisation_input -v` |
| **F5** | Create a clinic with a valid body | `201`; row carries the session tenant | `cd backend && uv run pytest tests/tenancy/test_clinics.py::test_create_clinic_scoped_to_session_tenant -v` |
| **F6** | `POST /api/v1/clinics` with `tenant_id` in the body | `422` unknown field; never created in the other tenant | `cd backend && uv run pytest tests/tenancy/test_clinics.py::test_create_clinic_body_tenant_id_rejected -v` |
| **F7** | Rename a clinic onto a unique collision | `422`, not `500` | `cd backend && uv run pytest tests/tenancy/test_clinics.py::test_clinic_rename_conflict_returns_422 -v` |
| **F8** | List clinics with pagination and a cross-tenant filter | `200`; only the caller's clinics; bounded `limit` | `cd backend && uv run pytest tests/isolation/test_clinics_absence.py::test_clinic_list_filter_sort_absent -v` |
| **F9** | Direct id read of another tenant's clinic | `404`, never `403` | `cd backend && uv run pytest tests/isolation/test_clinics_absence.py::test_clinic_direct_id_cross_tenant_returns_404 -v` |
| **F10** | Nested resource under another tenant's clinic | `404`; no child row returned | `cd backend && uv run pytest tests/isolation/test_clinics_absence.py::test_clinic_nested_resource_cross_tenant_returns_404 -v` |
| **F11** | `SUSPENDED` tenant with a valid unexpired session | Refused at resolution on every request | `cd backend && uv run pytest tests/tenancy/test_tenant_resolution.py::test_suspended_tenant_refused_on_every_request -v` |
| **F12** | Security-config change without a fresh factor | `403`; after step-up applied and versioned | `cd backend && uv run pytest tests/security/test_tenancy_step_up.py::test_tenant_security_config_requires_step_up -v` |

## Security and isolation tests (S)

| ID | Case | Expected result | Verified by |
|---|---|---|---|
| **S1** | **Pool reuse:** tenant A then tenant B then no context on the same pooled connection, 200 concurrent requests alternating tenants | Zero context or session leakage; no response contains another tenant's row; `ZZCANARY` absent | `cd backend && uv run pytest tests/isolation/test_pool_reuse.py::test_connection_pool_reuse_no_tenant_leak -v` |
| **S2** | **No tenant context reads nothing:** raw query with `app.tenant_id` unset | Zero rows **and no error**; the API request is refused, never served unscoped | `cd backend && uv run pytest tests/isolation/test_no_tenant_context.py::test_no_tenant_context_reads_zero_rows_and_is_refused -v` |
| **S3** | **Forged `tenant_id` in a write:** `INSERT` with B's `tenant_id` while A's context is set; `UPDATE` an A row to B | `new row violates row-level security policy`; no row created for B, no A row moved | `cd backend && uv run pytest tests/isolation/test_with_check_blocks_cross_tenant_insert.py::test_forged_tenant_id_write_rejected -v` |
| **S4** | **`NULLIF` empty-string guard:** guarded policy with the setting absent; naive form on a scratch database | Guarded form returns zero rows and does not raise; the naive `::uuid` form **raises** `invalid input syntax for type uuid: ""` | `cd backend && uv run pytest tests/isolation/test_pool_reuse.py::test_nullif_guard_returns_zero_rows_and_naive_form_raises -v` |
| **S5** | **RLS holds without an application filter:** raw query with no `WHERE tenant_id` | Only the caller's tenant rows; result sets for A and B are disjoint | `cd backend && uv run pytest tests/isolation/test_rls_holds_without_app_filter.py::test_rls_holds_without_app_filter -v` |
| **S6** | App role ownership and bypass | `clinos_app` owns no tenant table and holds no `BYPASSRLS` | `cd backend && uv run pytest tests/isolation/test_role_and_policy_coverage.py::test_app_role_is_not_owner_and_has_no_bypassrls -v` |
| **S7** | **Schema lint:** a tenant table with no policy | CI fails; every table with `tenant_id` has a forced policy with `USING` **and** `WITH CHECK`; tables without it are on the global allow-list | `cd backend && uv run pytest tests/isolation/test_role_and_policy_coverage.py::test_schema_lint_fails_when_tenant_table_lacks_policy -v` |
| **S8** | **Absence across every channel** — see the channel table below | Zero foreign-tenant rows in every channel, asserted absent by name | `cd backend && uv run pytest tests/isolation/test_clinics_absence.py::test_absence_across_list_filter_sort_search_id_nested_export_cache -v` |
| **S9** | `tenants` grants | App role cannot write `tenants`; cannot read `retention_profile` | `cd backend && uv run pytest tests/security/test_tenant_grants.py::test_app_role_cannot_write_tenants_and_cannot_read_retention_profile -v` |
| **S10** | `clinics` hard delete | `DELETE`/`TRUNCATE` raise `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_tenant_grants.py::test_app_role_cannot_delete_clinics -v` |
| **S11** | Cross-tenant status selection | `404` on every cross-tenant route; never `403` | `cd backend && uv run pytest tests/isolation/test_clinics_absence.py::test_cross_tenant_never_returns_403 -v` |
| **S12** | Abuse protection on tenancy routes | `429` with `Retry-After` at the administrative class limit | `cd backend && uv run pytest tests/security/test_tenancy_rate_limits.py::test_admin_class_rate_limit_returns_429 -v` |

## S4 in detail: the `NULLIF` guard

```python
def test_nullif_guard_returns_zero_rows_and_naive_form_raises(db_app_role):
    # Guarded form (the required policy expression) with app.tenant_id absent:
    db_app_role.execute("RESET app.tenant_id")
    guarded = db_app_role.execute(
        "SELECT count(*) FROM clinics "
        "WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    ).scalar_one()
    assert guarded == 0                       # matches nothing, does not raise

    # Naive form (a defect) must raise, proving this test detects the regression:
    with pytest.raises(DBAPIError) as exc:
        db_app_role.execute(
            "SELECT count(*) FROM clinics "
            "WHERE tenant_id = current_setting('app.tenant_id', true)::uuid"
        )
    assert "invalid input syntax for type uuid" in str(exc.value)
```

## Absence channels asserted (S8, Gate 2)

| Channel | What is asserted absent | Source test |
|---|---|---|
| List | Tenant B's clinics are absent from tenant A's list, including counts | I-002 |
| Filter | A filter matching across tenants returns only the caller's rows | I-002 |
| Sort | Ordering cannot surface another tenant's row | I-016 |
| Search | Autocomplete returns no other tenant's clinic, including highlighted snippets | I-025, I-026 |
| Direct id | Another tenant's clinic id returns `404`, not `403` | I-001, I-009 |
| Nested resource | A child row of another tenant's parent returns `404` | I-006, I-012 |
| Export | A tenant-parameterised export contains only that tenant's rows; count asserted exactly | I-027, I-028 |
| Cache | A key built without a tenant throws; a warm entry for A is a miss for B | I-023, I-024 |

## Audit tests (A)

| ID | Case | Expected | Verified by |
|---|---|---|---|
| **A1** | Tenant and clinic read | `tenant.viewed` with the full envelope | `cd backend && uv run pytest tests/security/test_tenancy_audit.py::test_tenant_viewed_full_envelope -v` |
| **A2** | Security-config change | `tenant.config_changed` with step-up recorded | `cd backend && uv run pytest tests/security/test_tenancy_audit.py::test_tenant_config_changed_envelope -v` |
| **A3** | Clinic create and rename | `clinic.created`, `clinic.updated` with actor, tenant, clinic ID | `cd backend && uv run pytest tests/security/test_tenancy_audit.py::test_clinic_created_and_updated_events -v` |
| **A4** | Cross-tenant attempt | `TENANT_CROSS_ACCESS_ATTEMPT`, `result = DENIED`, audited with equal fidelity | `cd backend && uv run pytest tests/security/test_tenancy_audit.py::test_tenant_cross_access_attempt_audited -v` |
| **A5** | Audit write fails | The action does not complete (fail closed); alert raised | `cd backend && uv run pytest tests/security/test_tenancy_audit.py::test_audit_write_failure_fails_closed -v` |

## Traceability
F1–F12 cover the acceptance criteria in R1–R15 of `01-requirements.md` and the security criteria in
`02-user-stories.md`. S1–S12 cover the controls in `04-threat-model.md` (S1→T-TEN-2, S2/S4→T-TEN-4 and
T-TEN-7, S3→T-TEN-1, S5/S8→T-TEN-3 and T-TEN-6, S6→T-TEN-8, S7→T-TEN-3, S11→T-TEN-6, S12→T-TEN-10).
A1–A5 cover the event catalogue in `05-data-and-audit.md`. S7 is the Gate 2 schema-lint check.
