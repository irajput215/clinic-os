---
doc_id: FEAT-CLIN-07
title: Clinical records, definition of done
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Definition of Done

The six parts are from `24-definition-of-done.md`. Tick only with a link to evidence.

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in [01-requirements.md](01-requirements.md) has a passing test | [ ] | F1–F16 in [06-test-plan.md](06-test-plan.md) |
| 2 | Security: deny-by-default path, RLS, exact grants, append-only versions, strict schemas, treating-relationship check implemented | [ ] | S1–S16; grant listing; migration review |
| 3 | Security tests pass in CI: S1–S16 | [ ] | CI run for the release commit |
| 4 | Audit: events emitted in the same transaction and verified; A1–A3; `07` §1 label registration complete | [ ] | A1–A3; registration change to `07` §1 |
| 5 | Operations & compliance: classification applied, narrative excluded from logs/analytics/telemetry, residency register updated, retention and legal-hold job behaviour present | [ ] | Sentinel test S12; residency register entry |
| 6 | Deployment: image builds, scans clean, expand-and-contract migration verified in Staging | [ ] | Migration run log; scan report |

**No part is Done with an open High or Critical finding.**

## Gate sign-off & Verification Governance

Who verifies these controls and signs the gates. Evidence must be produced **during** the phase, not on
gate day. **No self-approval: the person who delivered the work never signs its gate.** The CSO who
owns this feature documents it; the CSO does not sign it alone.

| Stage / Gate | What is Verified | Verifier (Decision Maker) | Approver | Pass Policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Grant inspection (`S11`), app-role denial (`S7`, `S8`), trigger denial as owner and migration role (`S9`, `S10`), log-redaction sentinel (`S12`) | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 2 (Data Model & Grants)** | App role holds exactly `SELECT, INSERT` on `clinical_record_versions`; `REVOKE UPDATE, DELETE, TRUNCATE`; `BEFORE UPDATE OR DELETE` trigger binding owner and migration role; `FORCE ROW LEVEL SECURITY` and `NULLIF` policy; `UNIQUE (record_id, version)` | **Security Lead** | **CTO** | **NO conditional pass allowed** (`gates.md` Gate 2: *"Conditional pass. ❌ NOT AVAILABLE"*) |
| **Gate 4 (APIs & RBAC)** | No mutating route; `403 NOTE_ALREADY_SIGNED`; treating-relationship check; cross-tenant `404`; mass-assignment rejection; error envelope; append-only versions | **Security Lead** | **CTO** + **Clinical Safety Officer** | Conditional pass only for a non-clinical endpoint; **not available** for note immutability or the treating-relationship check |
| **Independent Compliance** | Immutability proof, retention floor, legal-hold register, audit-trail integrity for regulator reporting | **Privacy Officer / Compliance Lead** | **External auditor** | Pre-launch / periodic |

**Gate 2 permits no conditional pass.** Tenant isolation and the immutability schema are the controls
the clinical record depends on; a partial pass is a failed gate and dependent work stops
(`gates.md` Gate 2).

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| A signed note cannot be altered in place | Append-only versions plus a role-independent trigger | `REVOKE UPDATE, DELETE, TRUNCATE`; `trg_clinical_record_versions_immutable` | F5, F9, S7–S11 | Clinical Safety Officer | planned |
| No delete path for clinical content | No `DELETE` route; soft delete on the parent only | `clinical_records.deleted_at`; no grant on versions | F13, S11 | Privacy Officer | planned |
| An amendment preserves the original | New version with explicit provenance and deterministic order | `supersedes_version`, `reason`; unique `(record_id, version)`; `ORDER BY version ASC` | F6–F10 | Clinical Safety Officer | planned |
| A clinic cannot see another clinic's chart | RLS with tenant from the session | `FORCE ROW LEVEL SECURITY`; `NULLIF(current_setting(...))`; `404` not `403` | F12, S1–S4 | CTO | planned |
| Only a treating clinician reads or writes a chart | Relationship check in the central policy layer | `hasActiveCareRelationship` (`06` §10) | F11, S6 | Practice Owner | planned |
| The narrative never reaches logs or audit | `HIGHLY_SENSITIVE` handling; action-not-content events | Allow-list logger; redaction before sink; metadata allow-list | S12, A1–A3 | Security Lead | planned |
| The audit trail survives tampering | Append-only by grant plus hash chain and Object Lock export | `audit_log` `SELECT, INSERT` only (feature 04) | A1–A3, S13 | Security Lead | planned |
| Retention floor and hold are honoured | Retention schedule plus fail-closed hold check | Purge job excludes held records; hold register | F16 | Compliance Lead | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| `care_relationships` named by `06` §10 but not defined in `04`; the treating-relationship control cannot be fully evidenced | Clinical Safety Officer + Engineering Lead | OPEN — blocked |
| Per-jurisdiction retention, clock trigger, legal-hold ownership, jurisdiction-move and erasure interactions | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Story labels `CLINICAL_RECORD_VIEWED`, `CLINICAL_NOTE_CREATED`, `CLINICAL_NOTE_SIGNED`, `CLINICAL_NOTE_AMENDED` are not in `07` §1 and must be registered before build | CTO | OPEN |
| `body` classification conflict (`04` §3.5 vs `12` §3); the stricter level is applied | Privacy Officer | OPEN |
| The immutability trigger is repo-proposed defence in depth and needs Gate 2 confirmation | Security Lead + CTO | OPEN |
| `signature_digest` has no source field; keep or drop | Security Lead | OPEN |
| Role labels and permission vocabulary (OPEN-6, OPEN-7 in [01-requirements.md](01-requirements.md)) | CTO | OPEN |
