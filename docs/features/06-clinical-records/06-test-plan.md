---
doc_id: FEAT-CLIN-06
title: Clinical records, test plan
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Test plan

All tests run in CI on synthetic data only (`27` §6). A failing security or immutability test blocks
merge. Every test carries the exact command that produces its evidence.

```bash
# Run all clinical record, immutability, isolation and log-redaction tests
cd backend && uv run pytest tests/clinical tests/isolation/test_clinical_isolation.py \
  tests/security/test_clinical_immutability.py tests/security/test_clinical_no_phi_in_logs.py \
  tests/security/test_clinical_rbac.py tests/security/test_clinical_audit.py -v
```

## Functional tests (F)

| ID | Case | Expected Result | Evidence (command) |
|---|---|---|---|
| **F1** | Create a note for a patient in care | `201`; `version = 1`; `signed_at` null; tenant and author from session | `cd backend && uv run pytest tests/clinical/test_authoring.py::test_create_note_tenant_and_author_from_session -v` |
| **F2** | Body carries `tenant_id`, `author_id`, `signed_at` or `version` | `422`; zero rows written | `cd backend && uv run pytest tests/clinical/test_authoring.py::test_create_note_rejects_unknown_fields -v` |
| **F3** | SOAP authoring surface submitted | Serialised into `clinical_record_versions.body`; no SOAP columns exist | `cd backend && uv run pytest tests/clinical/test_authoring.py::test_narrative_is_single_body_column -v` |
| **F4** | Author signs their own version | `200`; `signed_at` set; author recorded | `cd backend && uv run pytest tests/clinical/test_signing.py::test_sign_is_identity_bound_to_version_author -v` |
| **F5** | `PATCH` on a signed record | `403 NOTE_ALREADY_SIGNED`; no version written | `cd backend && uv run pytest tests/clinical/test_signing.py::test_patch_signed_note_returns_403 -v` |
| **F6** | Amend a signed note with a reason | `version + 1` with `supersedes_version` and `reason`; original readable | `cd backend && uv run pytest tests/clinical/test_amendments.py::test_amendment_creates_new_version_with_provenance -v` |
| **F7** | Amend without a reason (`version > 1`) | `422 AMENDMENT_REASON_REQUIRED`; zero rows | `cd backend && uv run pytest tests/clinical/test_amendments.py::test_amendment_reason_required_from_version_two -v` |
| **F8** | Two concurrent amendments | Unique collision; one wins; loser gets `409 VERSION_CONFLICT`; no lost update | `cd backend && uv run pytest tests/clinical/test_amendments.py::test_concurrent_amendments_no_lost_update -v` |
| **F9** | Read version 1 after an amendment | Byte-for-byte identical to the signed content | `cd backend && uv run pytest tests/clinical/test_amendments.py::test_version_one_preserved_byte_for_byte -v` |
| **F10** | Read the version history | Versions returned `ORDER BY version ASC` | `cd backend && uv run pytest tests/clinical/test_read_path.py::test_versions_returned_in_ascending_order -v` |
| **F11** | Read with no treating relationship | `403 AUTHZ_CARE_RELATIONSHIP_DENIED`; audited as denied | `cd backend && uv run pytest tests/clinical/test_read_path.py::test_read_requires_active_treating_relationship -v` |
| **F12** | Cross-tenant read by ID | `404 Not Found`, never `403`; no existence leak | `cd backend && uv run pytest tests/isolation/test_clinical_isolation.py::test_cross_tenant_record_returns_404 -v` |
| **F13** | No delete route; soft delete the parent | No `DELETE` route; `deleted_at` set; versions retained | `cd backend && uv run pytest tests/security/test_clinical_immutability.py::test_no_delete_route_and_no_delete_grant -v` |
| **F14** | Missing version | `404`; no partial record returned | `cd backend && uv run pytest tests/clinical/test_read_path.py::test_missing_version_returns_404 -v` |
| **F15** | Read a record plus 50 prior versions | Under `200 ms` p95 at pilot load | `cd backend && uv run pytest tests/clinical/test_latency.py::test_record_with_fifty_versions_p95_under_200ms -v` |
| **F16** | Retention floor and legal hold | 7-year floor / age-25 rule enforced; a hold suspends automated archiving | `cd backend && uv run pytest tests/clinical/test_retention.py::test_retention_floor_and_legal_hold_suspends_archive -v` |

## Security tests (S)

| ID | Case | Expected Result | Evidence (command) |
|---|---|---|---|
| **S1** | Clinic A requests clinic B's record ID | `404 Not Found` | `cd backend && uv run pytest tests/isolation/test_clinical_isolation.py::test_cross_tenant_record_returns_404 -v` |
| **S2** | Raw SQL as the app role with no tenant filter | Zero foreign rows | `cd backend && uv run pytest tests/isolation/test_clinical_isolation.py::test_raw_sql_app_role_sees_zero_foreign_rows -v` |
| **S3** | Tenant setting unset on the connection | Zero rows (fail-closed `NULLIF`) | `cd backend && uv run pytest tests/isolation/test_clinical_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` |
| **S4** | Pool reuse: tenant A then tenant B | No context or row leakage | `cd backend && uv run pytest tests/isolation/test_clinical_isolation.py::test_connection_pool_reuse_no_leakage -v` |
| **S5** | Body sets `author_id`, `signed_at`, `version` | `422`; mass assignment blocked | `cd backend && uv run pytest tests/security/test_clinical_rbac.py::test_body_mass_assignment_rejected -v` |
| **S6** | Role × endpoint matrix (`27` §5) | Only authorised roles succeed; denials audited | `cd backend && uv run pytest tests/security/test_clinical_rbac.py::test_role_endpoint_matrix -v` |
| **S7** | App role `UPDATE`s `clinical_record_versions` | `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_clinical_immutability.py::test_app_role_cannot_mutate_versions -v` |
| **S8** | App role `DELETE`s `clinical_record_versions` | `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_clinical_immutability.py::test_app_role_cannot_mutate_versions -v` |
| **S9** | Owner role `UPDATE`s a version | Trigger exception `CLINICAL_RECORD_VERSION_IMMUTABLE` | `cd backend && uv run pytest tests/security/test_clinical_immutability.py::test_trigger_blocks_owner_and_migration_role -v` |
| **S10** | Migration role `DELETE`s a version | Trigger exception `CLINICAL_RECORD_VERSION_IMMUTABLE` | `cd backend && uv run pytest tests/security/test_clinical_immutability.py::test_trigger_blocks_owner_and_migration_role -v` |
| **S11** | `information_schema.role_table_grants` inspection | Versions grants are exactly `{SELECT, INSERT}`; no `DELETE`/`TRUNCATE` on `clinical_records` | `cd backend && uv run pytest tests/security/test_clinical_immutability.py::test_role_table_grants_exact -v` |
| **S12** | Sentinel `SENTINEL-CLINICAL-4B2E` in the narrative | Absent from stdout and from every audit row | `cd backend && uv run pytest tests/security/test_clinical_no_phi_in_logs.py::test_narrative_never_reaches_logs_or_audit -v` |
| **S13** | Cross-tenant access denied | Denial audited with the same fidelity as a success | `cd backend && uv run pytest tests/security/test_clinical_no_phi_in_logs.py::test_cross_tenant_denial_audited_with_equal_fidelity -v` |
| **S14** | Single-resource read limit exceeded | `429 Too Many Requests` | `cd backend && uv run pytest tests/security/test_clinical_rbac.py::test_sensitive_read_rate_limit -v` |
| **S15** | Forced server error | Standard envelope, `request_id`, no stack trace, no narrative | `cd backend && uv run pytest tests/security/test_clinical_rbac.py::test_error_envelope_has_no_internals -v` |
| **S16** | Sign concurrent with an amendment | Exactly one outcome; no unsigned overwrite of a signed version | `cd backend && uv run pytest tests/clinical/test_amendments.py::test_concurrent_sign_during_amendment_blocks -v` |

## Audit tests (A)

| ID | Case | Expected Result | Evidence (command) |
|---|---|---|---|
| **A1** | Each successful action | One event, full `07` §2 envelope, no clinical text | `cd backend && uv run pytest tests/security/test_clinical_audit.py::test_success_event_full_envelope -v` |
| **A2** | Each refusal | `clinical_record.read`/`.write` with `result = DENIED` and a reason code | `cd backend && uv run pytest tests/security/test_clinical_audit.py::test_denied_event_written -v` |
| **A3** | Audit write fails | Clinical write does not commit; alert raised | `cd backend && uv run pytest tests/security/test_clinical_audit.py::test_audit_write_failure_blocks_commit -v` |

## Immutability suite (Gate 2 / Gate 4) — both layers

Source: `04-database-erd.md` §9 (*enforcement is by grant, not by convention*); `07` §3; Gate 2.
Command:
`cd backend && uv run pytest tests/security/test_clinical_immutability.py -v`

```python
def test_role_table_grants_exact(db_admin_role):
    grants = db_admin_role.execute("""
        SELECT table_name, privilege_type
        FROM information_schema.role_table_grants
        WHERE grantee = 'clinos_app'
          AND table_name IN ('clinical_records', 'clinical_record_versions')
    """).fetchall()
    version_privileges = {g.privilege_type for g in grants
                          if g.table_name == 'clinical_record_versions'}
    record_privileges = {g.privilege_type for g in grants
                         if g.table_name == 'clinical_records'}
    assert version_privileges == {"SELECT", "INSERT"}, version_privileges
    assert "DELETE" not in record_privileges and "TRUNCATE" not in record_privileges


def test_app_role_cannot_mutate_versions(db_app_role, version_id):
    # Layer 2 (primary): the grant denies the statement.
    with pytest.raises(DBAPIError) as exc_update:
        db_app_role.execute(
            "UPDATE clinical_record_versions SET body = 'tampered' WHERE id = :id",
            {"id": version_id})
    assert "42501" in str(exc_update.value) or "permission denied" in str(exc_update.value).lower()

    with pytest.raises(DBAPIError) as exc_delete:
        db_app_role.execute("DELETE FROM clinical_record_versions WHERE id = :id",
                            {"id": version_id})
    assert "permission denied" in str(exc_delete.value).lower()


def test_trigger_blocks_owner_and_migration_role(db_admin_role, db_migration_role, version_id):
    # Layer 3 (defence in depth): the trigger binds every role, including the owner
    # and the migration role, because a grant binds only its grantee.
    for role in (db_admin_role, db_migration_role):
        for statement in (
            "UPDATE clinical_record_versions SET body = 'tampered' WHERE id = :id",
            "DELETE FROM clinical_record_versions WHERE id = :id",
        ):
            with pytest.raises(DBAPIError) as exc:
                role.execute(statement, {"id": version_id})
            assert "CLINICAL_RECORD_VERSION_IMMUTABLE" in str(exc.value)
```

## Traceability
F1–F16 cover R1–R17 in [01-requirements.md](01-requirements.md). S1–S16 cover the S: criteria in
[02-user-stories.md](02-user-stories.md) and the controls in
[04-threat-model.md](04-threat-model.md) (S7–S11 cover T-CLIN-03 and T-CLIN-04; S1–S4 cover T-CLIN-09;
S12 covers T-CLIN-08; S16 covers T-CLIN-05). A1–A3 cover the event catalogue and the audit-metadata
rule in [05-data-and-audit.md](05-data-and-audit.md).
