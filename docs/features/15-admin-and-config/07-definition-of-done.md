---
doc_id: OZ-FEAT-15-DOD
title: "Administration and configuration — definition of done"
owner: CTO + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-15
phase: 04-phase-4-pilot-go-live
gate: [4]
source:
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md §5, §9
  - clinic-os-secure-by-design/17-compliance-control-matrix.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Definition of done

The six parts are from `24-definition-of-done.md`. Tick only with a link to evidence.

| # | Part | Done | Evidence |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in `01-requirements.md` has a passing test | [ ] | F1–F13 |
| 2 | Security: deny-by-default path, RLS with `FORCE`, strict schemas, step-up, least privilege implemented | [ ] | S1–S9, S18 |
| 3 | Security tests pass in CI: S1–S20, including the safety-gate, fail-closed and legal-hold cases | [ ] | S10–S17, S19, S20 |
| 4 | Audit: the event catalogue is emitted, append-only and same-transaction; A1–A3 | [ ] | A1–A3, S11 |
| 5 | Operations and compliance: classification applied, no secret in a log, residency register updated, metrics and alerts for break-glass and denials present | [ ] | `05-data-and-audit.md`; alert config |
| 6 | Deployment: image builds, scans clean, Alembic expand-and-contract migration, verified in Staging | [ ] | CI run; Staging record |

**No part is Done with an open High or Critical finding.**

## Gate sign-off and verification governance

Who verifies these controls and signs the security gates. **No self-approval:** the person who delivered
the work never signs its gate.

| Stage / Gate | What is verified | Verifier (decision maker) | Approver | Pass policy |
| --- | --- | --- | --- | --- |
| CI / automated | Grant inspection on the history tables (`S11`, `S12`), `SAFETY_GATE_FLAG_IMMUTABLE` (`F3`), fail-closed startup (`F7`), legal hold (`S15`, `S16`) | CI pipeline (pytest) | Automated gate | Hard block on failure |
| Gate 4 (APIs) | Step-up and approval reference on a safety-gate flag (`F2`, `F3`, `S19`), admin rate limit (`S17`), tenant scoping and `404` (`S6`–`S8`), break-glass expiry and dual notification (`F9`, `S13`, `S14`) | **Security Lead** | **CTO** + **Clinical Safety Officer** | No conditional pass for the safety gate |
| Independent compliance | Append-only history, break-glass review records, retention certificates, legal-hold exclusions | **Privacy Officer / Compliance Lead** | **External auditor** | Pre-launch, then periodic |

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| No configuration or flag can disable the safety gate | Non-negotiable rule; the disabled state is unrepresentable | `CHECK (NOT affects_safety_gate OR enabled)` plus `SAFETY_GATE_FLAG_IMMUTABLE` trigger | F3, S19 | Clinical Safety Officer | planned |
| A safety-gate flag change needs an approval reference and step-up | Constraint plus step-up on the route | `CHECK` on `approval_reference`; resource-bound step-up token | F2, S3, S5 | Security Lead | planned |
| Missing required configuration fails closed | Precedence resolver with no permissive default | `app/core/config.py`, `ERR_CONFIG_REQUIRED_KEY_ABSENT` naming the key | F6, F7 | Head of Platform | planned |
| Flag and configuration history is append-only | `GRANT SELECT, INSERT` only; `UPDATE`/`DELETE`/`TRUNCATE` revoked | `information_schema.role_table_grants` query plus a negative SQL execution | S11, S12 | Security Lead | planned |
| Break-glass is time-boxed, scoped, dual-notified and audited | Server-enforced expiry, reason and ticket required, own event type | break-glass service; `auth.break_glass_granted` | F8, F9, S13, S14 | Compliance Lead | planned |
| Retention jobs honour legal hold and fail closed | Dry-run default, manifest, approval by another actor, hold check before every delete | retention job worker as `clinos_retention` | F10, F11, S15, S16 | Privacy Officer | planned |
| Admin routes are rate limited | 20 per minute per session | rate-limit policy on `/api/v1/admin/*` | S17 | Head of Platform | planned |
| A tenant cannot reach another tenant's admin data | Session tenant plus RLS with `NULLIF` and `FORCE`; `404`, never `403` | RLS policies on the seven tables | S6, S7, S8 | Security Lead | planned |
| No secret is readable through the admin surface | ARN reference only; allow-listed response schema | `configuration.secret_ref`; response schema review | S10 | Security Lead | planned |
| The clinical confidence threshold is a recorded clinical decision | CSO sign-off reference required on a clinical safety parameter | `tenant_policy.cso_signoff_reference` constraint | F4 | Clinical Safety Officer | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 `tenant_policy` is Phase 2-required but Phase 4-owned (`docs/reference/build-contract.md` §7; Phase 2 R5) | Head of Platform | OPEN |
| OPEN-2 five admin action names are absent from `07 §1`; doc 07 §1 forbids inventing an action name | Security Lead + Compliance Lead | OPEN |
| OPEN-3 the `admin:*` permission codes are candidates, not granted (feature 03 OPEN-1) | CTO + Security Lead | OPEN |
| OPEN-4 the safety-gate flag allowlist and its approval authority | Clinical Safety Officer + CTO | OPEN |
| OPEN-5 platform-scope flags have no RLS context (`05 §4`) | CTO | OPEN |
| OPEN-6 retention period for configuration and flag history, and legal-hold ownership | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
