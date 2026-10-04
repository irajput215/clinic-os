---
doc_id: FEAT-CLIN-01
title: Clinical records, requirements
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Clinical records: requirements

## Purpose
Record the clinical narrative for a patient as a versioned, attributable, immutable clinical record, so
that a signed note is defensible evidence and a correction is visible without destroying the original.
Grain: **Tenant ID + Patient ID + Clinical Record ID + Version**. Source: `04-database-erd.md` §3.5;
`20-product-requirements.md` §4; `22-user-stories.md` US-11, US-12, US-13.

## The core clinical and legal invariant
> **A signed clinical note is strictly immutable. In-place update or delete is impossible at both the
> API and the database level. Amendments spawn new version records with explicit provenance.**

The same rule is stated in `04-database-erd.md` §3.5 (*"A signed note is never updated in place"*),
`04-database-erd.md` §6, `20-product-requirements.md` §4 acceptance criteria, and
`22-user-stories.md` US-12. It is enforced twice in the database and once in the API — see
[03-design.md](03-design.md#immutability-mechanism-at-two-layers). No route, migration or admin path
may weaken it; §9 of `04-database-erd.md` states the principle as *"enforcement is by grant, not by
convention"*.

## Functional requirements & test traceability

| ID | Requirement | Acceptance Criteria | Verified By (Pytest File & Test) |
|---|---|---|---|
| **R1** | Create a clinical record and its first version | `POST` returns `201`; `version = 1`; `signed_at` null; `tenant_id` and `author_id` from session, never the body | `tests/clinical/test_authoring.py::test_create_note_tenant_and_author_from_session` |
| **R2** | Strict schema on create and amend | Unknown or extra fields (`tenant_id`, `author_id`, `signed_at`, `version`) return `422` with zero rows written | `tests/clinical/test_authoring.py::test_create_note_rejects_unknown_fields` |
| **R3** | Narrative is stored once, in a single `body` column | The `subjective`/`objective`/`assessment`/`plan` authoring surface serialises into `clinical_record_versions.body`; no SOAP columns and no separate notes table exist | `tests/clinical/test_authoring.py::test_narrative_is_single_body_column` |
| **R4** | Signing is identity-bound | Only the version author may sign it; `signed_at` set; another clinician signing returns `403` | `tests/clinical/test_signing.py::test_sign_is_identity_bound_to_version_author` |
| **R5** | Signed note strictly immutable at the API | No route mutates a version; `PATCH` on a signed record returns `403 NOTE_ALREADY_SIGNED` | `tests/clinical/test_signing.py::test_patch_signed_note_returns_403` |
| **R6** | Amendment spawns a new version with explicit provenance | New row with `version + 1`, `supersedes_version = version`, `author_id` and `reason`; original readable | `tests/clinical/test_amendments.py::test_amendment_creates_new_version_with_provenance` |
| **R7** | Amendment reason mandatory above version 1 | `version > 1` without `amendment_reason` returns `422 AMENDMENT_REASON_REQUIRED` | `tests/clinical/test_amendments.py::test_amendment_reason_required_from_version_two` |
| **R8** | One row per `(record_id, version)` | Concurrent inserts of the same version collide on the unique constraint; one wins, the other returns `409 VERSION_CONFLICT`, no lost update | `tests/clinical/test_amendments.py::test_concurrent_amendments_no_lost_update` |
| **R9** | Read order is deterministic | Versions returned `ORDER BY version ASC`; the unique constraint makes the order total within a record | `tests/clinical/test_read_path.py::test_versions_returned_in_ascending_order` |
| **R10** | Tenant isolation on every read and write | Cross-tenant lookup by ID returns `404 Not Found`, never `403` | `tests/isolation/test_clinical_isolation.py::test_cross_tenant_record_returns_404` |
| **R11** | Treating relationship required | Read or write without an active care relationship returns `403` (`AUTHZ_CARE_RELATIONSHIP_DENIED`) and is audited as denied | `tests/clinical/test_read_path.py::test_read_requires_active_treating_relationship` |
| **R12** | Records and versions are never hard-deleted | No `DELETE` route exists; the app role has `REVOKE DELETE, TRUNCATE` on both tables; only the parent may be soft-deleted (`deleted_at` + reason) | `tests/security/test_clinical_immutability.py::test_no_delete_route_and_no_delete_grant` |
| **R13** | Immutability holds in the database, primary layer | App role `UPDATE`/`DELETE` on `clinical_record_versions` raises `42501 insufficient_privilege` | `tests/security/test_clinical_immutability.py::test_app_role_cannot_mutate_versions` |
| **R14** | Immutability holds in the database, defence in depth | `UPDATE`/`DELETE` as the table owner or migration role raises `CLINICAL_RECORD_VERSION_IMMUTABLE` | `tests/security/test_clinical_immutability.py::test_trigger_blocks_owner_and_migration_role` |
| **R15** | Audit metadata never contains clinical text | Create, sign, amend and read each emit one event carrying the action, not the narrative | `tests/security/test_clinical_no_phi_in_logs.py::test_narrative_never_reaches_logs_or_audit` |
| **R16** | Read performance | Record plus 50 prior versions returns under `200 ms` p95 at pilot load | `tests/clinical/test_latency.py::test_record_with_fifty_versions_p95_under_200ms` |
| **R17** | Retention floor and legal hold | Retention is at least 7 years from the last date of service (until age 25 for a minor); a legal hold suspends automated archiving indefinitely | `tests/clinical/test_retention.py::test_retention_floor_and_legal_hold_suspends_archive` |

---

## Out of scope for the MVP
- Document and attachment handling (`07-documents`; `POST /clinical-records/{id}/documents`).
- Observations and results as first-class resources beyond the `record_type` values `OBSERVATION` and `RESULT`.
- A full-text search API surface over `body`; the MVP ships the index only (R16, `02-security-architecture.md` §5.1).
- Export, reporting and DSAR handling (`14-reports-and-exports`).
- Patient merge and reverse-merge (`22-user-stories.md` US-14).
- An `encounters` resource or `clinical_encounters` table: **it does not exist in the source contract and is not introduced here**.
- Cryptographic signing beyond identity-bound attribution; `signature_digest` is OPEN (OPEN-5).

## Open items
| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | `04-database-erd.md` §3.5 classifies the narrative `body` as `HEALTH_INFORMATION`; `12-data-classification.md` §3 classifies `note_body` `HIGHLY_SENSITIVE`. R3/R15 and 05 apply the stricter level | Privacy Officer | OPEN |
| OPEN-2 | `04-database-erd.md` §3.5 requires `reason` only *"when superseding a signed version"*; R7 requires it whenever `version > 1`, which is stricter. Confirm the stricter rule is correct | Clinical Safety Officer | OPEN |
| OPEN-3 | `care_relationships` is named in `06-authentication-rbac.md` §10 but has no ERD table definition in `04-database-erd.md`; R11 cannot be fully evidenced until the table is defined | Clinical Safety Officer + Engineering Lead | OPEN — blocked |
| OPEN-4 | Per-jurisdiction retention periods, the clock trigger, legal-hold ownership, and jurisdiction-move and erasure interactions | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 | `signature_digest` has no source field. It is a repo-proposed column and is not required by R1–R17; if kept it needs a key-custody decision | Security Lead | OPEN |
| OPEN-6 | Role labels in [02-user-stories.md](02-user-stories.md) ("Nurse Practitioner", "Consulting Doctor") must be aligned to the roles in `06-authentication-rbac.md` §9 before build | CTO | OPEN |
| OPEN-7 | Permission vocabulary conflict: `06-authentication-rbac.md` §10 defines `clinical_record:read`/`clinical_record:write`; `20-product-requirements.md` §4 names `clinical_record:create`/`clinical_record:amend`. R1–R17 use the §10 union | CTO | OPEN |
