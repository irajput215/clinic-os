---
doc_id: OZ-FEAT-04-DOD
title: "FEAT-04 — TGA Approval Module: Definition of Done & Gate Sign-off"
owner: CTO + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-04
phase: 02-phase-2-tga-approval-engine
gate: [2, 4]
source:
  - clinic-os-secure-by-design/17-compliance-control-matrix.md
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Definition of Done

The six parts are from doc 24. Tick only with a link to evidence.

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in 01-requirements.md has a passing test | [ ] | |
| 2 | Security: deny-by-default path, RLS, permissions, step-up, strict schemas implemented | [ ] | |
| 3 | Security tests pass in CI: S1–S16 | [ ] | |
| 4 | Audit: events emitted and verified; A1–A3 | [ ] | |
| 5 | Operations & compliance: classification applied, no PHI in logs, residency register updated, logs/metrics/alerts present | [ ] | |
| 6 | Deployment: image builds, scans clean, migration expand-and-contract, verified in Staging | [ ] | |

**No part is Done with an open High or Critical finding.**

## Gate sign-off & Verification Governance

Who verifies these controls and signs the security gates:

| Stage / Gate | What is Verified | Verifier (Decision Maker) | Approver | Pass Policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Post-migration `information_schema.role_table_grants` inspection (`S12a-S12d`), grant denial tests | CI Pipeline (pytest) | Automated Gate | Hard block on failure |
| **Gate 2 (Data Model & Grants)** | Append-only grant enforcement (`tga_approval_events`), NO `DELETE` grant on `tga_approval`, table ownership (not app role), GiST exclusion constraint | **Security Lead** | **CTO** | **NO conditional pass allowed** |
| **Gate 4 (APIs & RBAC)** | Post-verification immutability (`S12d`), four-eyes separation (`verifier <> creator`), step-up auth, prescription safety gate matching | **Security Lead** | **CTO** + **Clinical Safety Officer (CSO)** | No conditional pass for safety gate |
| **Independent Compliance** | Audit trail integrity, retention policy, immutability proof for legal/regulator reporting | **Privacy Officer / Compliance Lead** | **External Auditor** (TGA / ISO 27001) | Periodic / Pre-launch |

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| A clinic cannot see another clinic's approvals | RLS, tenant from session | `tga_approval` policy | S1–S4 | CTO | planned |
| No dispatch without an active approval | Server-side gate at the grain, at `date_of_service` | gate.check_active_approval | F11–F14, S10, S11, S16 | CSO | planned |
| One live approval per grain | Partial GiST exclusion constraint | `no_overlapping_active_approvals` | F8, F9 | CTO | planned |
| Audit trail is append-only | `GRANT SELECT, INSERT` only; `UPDATE/DELETE/TRUNCATE` revoked | `information_schema.role_table_grants` query + negative SQL execution | A1–A3, S12a, S12b | Security Lead | planned |
| Verified approvals are immutable | Database trigger locks core fields on `active` rows | `trg_tga_approval_lock_verified` raising `VERIFIED_APPROVAL_IMMUTABLE` | F10, S12d | Clinical Safety Officer | planned |
| Approval records are not destroyed | No `DELETE` grant to app role; no delete endpoint | Table grant revocation (`REVOKE DELETE`) | R13, S12c | Privacy Officer | planned |
| Health data stays in Australia | Residency register | region-pinned storage | register entry | Compliance Lead | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 grain enforcement (doc 08 §4 contradiction) — decision recorded as D-006 | CTO + CSO | OPEN |
| OPEN-2 `valid_to` inclusive vs half-open — clinical safety parameter | CSO | OPEN |
| OPEN-4 four-eyes verification rule | Practice Owner + CSO | OPEN |
| OPEN-6 retention and deletion position | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
