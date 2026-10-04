---
doc_id: FEAT-PAT-01
title: Patients, requirements
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Patients: Requirements

## Purpose
Maintain the authoritative patient record for a tenant — demographics, identifiers and merge lineage —
so that every clinical action can be attributed to the right person. There is one record per patient per
tenant, and it is the join point for clinical records, TGA approvals and prescriptions.

## The clinical invariant
1. **A patient record is medical history and is never hard-deleted.** Enforcement is by database grant,
   not convention: `REVOKE DELETE ON patients FROM clinos_app` (`04-database-erd.md` §6, §8, §9).
2. **Merges are reversible.** Duplicate records are merged via the `merged_into_patient_id` self-FK; both
   original identifiers are preserved and the merge is undone by a designed procedure, never a database
   restore (`22-user-stories.md` US-14; `20-product-requirements.md` §3).
3. **Viewing is an audited clinical action.** Every read — list, search, direct read and every refusal —
   writes `patient.read` with `care_relationship_id` and `purpose` (`07-audit-architecture.md` §1).

## Functional requirements & test traceability

| ID | Requirement | Acceptance criteria | Verified by (pytest) |
|---|---|---|---|
| **R1** | Create a patient in the caller's own tenant | `POST /api/v1/patients` returns `201`; `tenant_id` resolved from the session, never the body | `tests/patients/test_lifecycle.py::test_create_patient_tenant_from_session` |
| **R2** | Strict input schema; no identifier column is mass-assignable | Unknown field (incl. `tenant_id`, `merged_into_patient_id`, `deleted_at`) returns `422`, zero rows written | `tests/security/test_validation_rejects_unknown_field.py::test_patient_body_extra_fields_rejected` |
| **R3** | Identifier values are validated **before** the database; the algorithm is not asserted here | Invalid shape rejected at the schema boundary with `422`; no query issued | `tests/patients/test_identifiers.py::test_identifier_validation_before_database` |
| **R4** | Duplicate detection on an exact two-identifier match | Create is refused with a duplicate candidate and a machine-readable match reason; the existing record can be opened | `tests/patients/test_duplicates.py::test_two_identifier_match_refuses_create` |
| **R5** | Tenant isolation on read, list and search | Cross-tenant rows are **absent** from list and search results (`200`, empty) | `tests/isolation/test_patients_isolation.py::test_cross_tenant_list_and_search_absent` |
| **R6** | Cross-tenant direct read returns `404`, never `403` | `404` with no body fields; a denial audit event is written | `tests/isolation/test_patients_isolation.py::test_cross_tenant_get_returns_404` |
| **R7** | Read requires permission **and** the treating-relationship rule | Care-relationship role outside the relationship receives `403` (`AUTHZ_CARE_RELATIONSHIP_DENIED`); denial audited | `tests/patients/test_access.py::test_read_outside_care_relationship_denied` |
| **R8** | Medicare and IHI are field-encrypted with a keyed blind index for **exact match only** | Equality lookup returns the row; prefix, fuzzy and sort on the encrypted column are impossible | `tests/patients/test_identifiers.py::test_blind_index_exact_match_only` |
| **R9** | `HIGHLY_SENSITIVE` identifiers are always masked in responses and logs | Response carries a mask (`•••• ` + last 3) not the value; sentinel absent from logs | `tests/security/test_patient_masking.py::test_identifiers_masked_in_response_and_logs` |
| **R10** | Merge requires step-up and `patient:merge`, and is reversible | Missing step-up `401`; merge sets `merged_into_patient_id`; reverse restores both records | `tests/patients/test_merge.py::test_merge_requires_step_up_and_is_reversible` |
| **R11** | A patient is never hard-deleted by the application | No `DELETE` route; app role has no `DELETE` grant on `patients` | `tests/security/test_patient_grants.py::test_app_role_has_no_delete_on_patients` |
| **R12** | Search terms never appear in a URL | Search is `POST /api/v1/patients/search` with a body; a `q=` query string is not routed | `tests/patients/test_search.py::test_search_is_post_body_only` |
| **R13** | Denied and failed attempts are audited with equal fidelity | Permission, tenant, validation and relationship denials all write an event with `result=DENIED` | `tests/patients/test_audit.py::test_denials_audited_with_equal_fidelity` |
| **R14** | Bulk export requires step-up, a typed reason and permission | `401` without step-up; export audited with `record_count` and `purpose` | `tests/security/test_patient_export.py::test_bulk_export_step_up_and_purpose` |

## Identifier boundary (source contract)
`medicare_number` and `ihi` are inline columns on `patients` (`04-database-erd.md` §3.4). The ERD
defines no minimum identifier: both may be null, and no constraint requires one. Validation happens
before the database, per security control 4 (`02-security-architecture.md` §1). The Medicare check-digit
algorithm, any Individual Reference Number rule, the IHI format, the minimum search-query length and any
DVA identifier are **not** source requirements — see Open items.

## Negative decision matrix

| Condition | System state | HTTP / decision | Code |
|---|---|---|---|
| Cross-tenant direct read | Row owned by another tenant | `404` | `NOT_FOUND` (no existence leak) |
| Read outside treating relationship | Permission held, no care relationship | `403` | `AUTHZ_CARE_RELATIONSHIP_DENIED` |
| No tenant context on the connection | `app.tenant_id` unset | Empty result | fail-closed (`NULLIF`) |
| Missing permission | Role does not hold `patient:read` | `403` | `AUTHZ_DENIED` |
| Duplicate two-identifier match | Existing live record | `409` + candidate | `PATIENT_DUPLICATE_CANDIDATE` |
| Merge without step-up | Fresh factor absent | `401` | `AUTH_STEP_UP_REQUIRED` |
| Direct `DELETE` as app role | Grant absent | `42501 permission denied` | n/a (database) |
| Search term in a URL | `GET ...?q=` | Route not served | `405` / `404` |

## Out of scope for the MVP
- The normalised `patient_identifiers` table (not in the ERD — identifiers are inline; see Open items).
- `care_relationships` design (required by the authorisation layer, undefined in the source; blocked).
- DVA file numbers, Medicare IRN/expiry columns, and any check-digit algorithm.
- Appointments, booking and intake; My Health Record integration; patient-facing access.
- Population-level or cross-tenant matching of any kind.

## Open items
| # | Item | Owner | Status |
|---|---|---|---|
| OPEN-1 | Medicare check-digit algorithm, IRN rule and IHI format are unspecified in the source | Head of Product + Privacy Officer | OPEN — **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OPEN-2 | Minimum search-query length (any floor) is not a source requirement | Clinical Safety Officer | OPEN |
| OPEN-3 | `patient_identifiers` is named in `20-product-requirements.md` §3 but absent from `04-database-erd.md` §3.4; this feature uses the inline ERD columns | CTO + Head of Product | OPEN |
| OPEN-4 | `care_relationships` is read by the policy layer (`06-authentication-rbac.md` §10) but has no ERD table and no named owner | Clinical Safety Officer | **OPEN — blocked dependency** |
| OPEN-5 | `GET /patients/search?q=` is forbidden by `02-security-architecture.md` §10 requirement 10 (no search terms in URLs); re-expressed as `POST` (R12) | Security Lead | OPEN — conflict logged |
| OPEN-6 | Retention periods per jurisdiction | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
