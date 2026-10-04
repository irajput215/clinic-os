---
doc_id: FEAT-PAT-07
title: Patients, definition of done
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Definition of Done

The six parts are from `24-definition-of-done.md`. Tick only with a link to evidence.

| # | Part | Done | Evidence |
|---|---|---|---|
| 1 | Functional: every acceptance criterion in 01-requirements.md has a passing test | [ ] | `tests/patients/` run output; F1–F14 |
| 2 | Security: deny-by-default path, RLS, permissions, treating-relationship rule, strict schemas implemented | [ ] | `03-design.md` §deny-by-default; S1–S18 |
| 3 | Security tests pass in CI: S1–S18, including the absence assertions and the grant inspection | [ ] | `tests/isolation/test_patients_isolation.py`; `tests/security/test_patient_grants.py` |
| 4 | Audit: events emitted and verified; A1–A3 | [ ] | `tests/patients/test_audit.py`; audit coverage report |
| 5 | Operations & compliance: classification applied, identifiers masked, no PHI in logs, residency register updated | [ ] | `tests/security/test_patient_masking.py`; grant listing; residency register entry |
| 6 | Deployment: image builds, scans clean, migration expand-and-contract, verified in Staging | [ ] | Migration run log; `information_schema.role_table_grants` extract |

**No part is Done with an open High or Critical finding.**

## Gate sign-off & Verification Governance

| Stage / gate | What is verified | Verifier (decision maker) | Approver | Pass policy |
|---|---|---|---|---|
| **CI / automated** | Post-migration grant inspection (S16), `DELETE` denial (S15), isolation absence assertions (S1–S9), masking (S14) | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 2 (database)** | `patients` RLS enabled and forced; `NULLIF` fail-closed; app role is not the owner and has no `BYPASSRLS`; **no `DELETE` grant**; `tenant_id` leading on every index | **Security Lead** | **CTO** | **NO conditional pass allowed** — tenant isolation is the control the multi-tenant model depends on |
| **Gate 4 (APIs)** | Every patient endpoint declares auth, permission, tenant scope, ownership rule, schemas, audit event, rate limit and error behaviour; cross-tenant tests fail through every route | **Security Lead** | **CTO** + **Clinical Safety Officer** | No conditional pass for the cross-tenant or no-hard-delete checks |
| **Independent compliance** | Merge lineage, retention/legal hold, APP 12/13 correction evidence, no-destruction proof | **Privacy Officer / Compliance Lead** | **External auditor** | Periodic / pre-launch |

**No self-approval.** The person who delivered the work never signs its gate (`gates.md`; doc 26).
Gate 2 is a stop condition, not a status report: a partial pass is a failed gate.

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
|---|---|---|---|---|---|
| One clinic cannot see another clinic's patients | RLS forced, tenant from session, `404` across a boundary | `pol_patients_tenant_isolation` | S1–S9; I-001…I-004, I-016…I-018, I-023, I-025, I-027 | Security Lead | planned |
| A patient record is never hard-deleted | No `DELETE` grant to the app role; no delete endpoint | `REVOKE DELETE, TRUNCATE ON patients` | S15, S16; R11 | Privacy Officer | planned |
| Merges are reversible and preserve both originals | `merged_into_patient_id` self-FK; designed reversal; step-up | merge / reverse service | F11, F12; S11 | Clinical Safety Officer | planned |
| Viewing a record is an audited clinical action | `patient.read` on every read and denial, same transaction | audit writer | A1–A3; S17 | Security Lead | planned |
| Identifiers are not usable as join keys | Internal opaque id; Medicare/IHI exact-match only | blind index + masked serialisation | F8, F9, S14 | Privacy Officer | planned |
| Government related identifiers are not misused | APP 9 assessment per use | schema + access control | APP 9 assessment | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Health data stays in Australia | Region-pinned storage | `ap-southeast-2` | residency register entry | Compliance Lead | planned |

## Open items blocking Done

| Item | Owner | Status |
|---|---|---|
| `care_relationships` is undefined and unowned — the treating-relationship rule (R7, S10) cannot be fully evidenced | Clinical Safety Officer + Engineering Lead | **OPEN — blocked** |
| Identifier check-digit algorithm, IRN rule, IHI format and search-query floor are unspecified | Head of Product + Privacy Officer | **OPEN — REQUIRES LEGAL/REGULATORY VALIDATION** (F3 gap note) |
| `patient.merged` / `patient.merge_reversed` / `patient.duplicate_detected` are absent from `07-audit-architecture.md` §1 | Security Lead | OPEN — doc 07 §1 must be extended before build |
| `patient_identifiers` (PRD §3) vs inline ERD identifiers — this feature uses the ERD shape | CTO + Head of Product | OPEN |
| Per-jurisdiction retention periods for patient records | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| `patient:merge` is not in the fixed permission list in `04-database-erd.md` §3.3 | CTO + Head of Product | OPEN |
