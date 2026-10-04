---
doc_id: OZ-FEAT-04-REQ
title: "FEAT-04 — TGA Approval Module: Requirements & Decision Matrix"
owner: CTO (interim: Ishu Rajput)
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-04
phase: 02-phase-2-tga-approval-engine
gate: [2, 4]
source:
  - Therapeutic Goods Act 1989 (Cth)
  - clinic-os-secure-by-design/08-tga-approval-model.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/20-product-requirements.md §5
  - clinic-os-secure-by-design/27-security-testing.md §2.3
repo_docs:
  - 02-user-stories.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# TGA Approval: Requirements & Decision Matrix

## Purpose
Record, verify, and evaluate regulatory TGA approvals permitting a patient to receive a specific product category and dosage form, providing the fail-closed evaluation consumed by the prescription safety gate.

## Approval Grain (from doc 08)
$$\text{Approval Grain} = \text{Tenant ID} + \text{Patient ID} + \text{TGA Category} + \text{Dosage Form} + \text{Validity Window}$$

---

## Functional Requirements & Test Traceability

| ID | Requirement | Acceptance Criteria | Verified By (Pytest File & Test) |
|---|---|---|---|
| **R1** | Authorised user creates an approval in their own clinic | `POST` returns `201`; `tenant_id` resolved from authenticated session, never request body | `tests/tga/test_lifecycle.py::test_create_approval_tenant_from_session` |
| **R2** | Schema validation on category, dosage form, approval reference, `valid_from`, `valid_to` | Missing or invalid field returns `422` with zero DB rows written; mass assignment blocked | `tests/tga/test_lifecycle.py::test_create_approval_rejects_missing_or_extra_fields` |
| **R3** | `valid_to` is at most 2 years after `valid_from` | Interval $> 2$ years returns `422 ERR_WINDOW_EXCEEDS_MAX_DURATION` | `tests/tga/test_lifecycle.py::test_approval_window_max_two_years` |
| **R4** | State machine restricted to controlled vocabulary | Status strictly in `{'pending_verification', 'active', 'expired', 'revoked'}`; other values return `422` | `tests/tga/test_lifecycle.py::test_approval_status_controlled_vocabulary` |
| **R5** | Manual creation requires independent clinical verification | Newly created rows start `pending_verification`; cannot be verified by creator | `tests/tga/test_verification.py::test_tga_verifier_cannot_be_creator` |
| **R6** | State transition validation | Allowed: `pending → active`, `pending → revoked`, `active → revoked`, `active → expired`. All others return `409` | `tests/tga/test_lifecycle.py::test_illegal_transition_returns_409` |
| **R7** | Expiry evaluated server-side | Nightly job and real-time gate evaluate `date_of_service` against DB interval; client clock ignored | `tests/tga/test_lifecycle.py::test_expiry_job_and_point_in_time_evaluation` |
| **R8** | Tenant isolation on read/list | Cross-tenant lookup returns `404 Not Found` (never `403` to prevent ID enumeration) | `tests/tga/test_isolation.py::test_cross_tenant_lookup_returns_404` |
| **R9** | Step-up auth required for verify and revoke | Re-auth required within 15 minutes; missing reason returns `422`; missing step-up returns `401` | `tests/tga/test_verification.py::test_verify_revoke_requires_step_up` |
| **R10** | Deterministic point-in-time safety gate match | Returns `ALLOW` only when single active, in-window approval matches all 4 grain dimensions at `date_of_service` | `tests/tga/test_match.py::test_tga_match_grain_and_point_in_time` |
| **R11** | Exclusion of overlapping active approvals | DB GiST constraint rejects overlapping active intervals for same grain; superseding replaces atomically | `tests/tga/test_constraints.py::test_tga_overlapping_active_approval_rejected` |
| **R12** | Verified approvals are immutable | Once `active`, core grain & dates cannot be mutated; extensions require a new superseding grant | `tests/tga/test_security.py::test_verified_approval_immutable` |
| **R13** | Records are never hard-deleted | No `DELETE` endpoint; application DB role has `REVOKE DELETE` on `tga_approval` | `tests/security/test_tga_append_only_grants.py::test_app_cannot_delete_approvals` |

---

## Explicit Negative Decision Matrix (Safety Gate & API)

The prescription safety gate defaults to **DENY**. Any non-matching condition returns a machine-readable reason code:

| Condition / Test Scenario | System State | Service Date vs Window | HTTP / Gate Decision | Machine-Readable Reason Code |
|---|---|---|---|---|
| **No Record** | No approval row for patient | Any | `404` / `BLOCKED` | `TGA_APPROVAL_NOT_FOUND` |
| **Wrong Category** | Row has Category 5, Prescription asks Category 3 | In window | `400` / `BLOCKED` | `TGA_CATEGORY_MISMATCH` |
| **Wrong Dosage Form** | Row has Oil, Prescription asks Inhalation | In window | `400` / `BLOCKED` | `TGA_DOSAGE_FORM_MISMATCH` |
| **Expired Approval** | Status = `expired` (or date outside interval) | `date_of_service >= valid_to` | `400` / `BLOCKED` | `TGA_APPROVAL_EXPIRED` |
| **Not Yet Effective** | Status = `active` | `date_of_service < valid_from` | `400` / `BLOCKED` | `TGA_APPROVAL_NOT_YET_EFFECTIVE` |
| **Revoked Approval** | Status = `revoked` | Any | `400` / `BLOCKED` | `TGA_APPROVAL_REVOKED` |
| **Pending Verification** | Status = `pending_verification` | In window | `400` / `BLOCKED` | `TGA_APPROVAL_PENDING_VERIFICATION` |
| **Superseded Row** | Status = `superseded` | In window | `400` / `BLOCKED` | `TGA_APPROVAL_SUPERSEDED` |
| **Self-Verification** | Creator attempts to verify | N/A | `403 Forbidden` | `VERIFIER_CANNOT_BE_CREATOR` |
| **Overlapping Active** | Second active approval created at same grain | Overlaps active | `409 Conflict` | `TGA_OVERLAPPING_ACTIVE_APPROVAL` |
| **Cross-Tenant Access** | Tenant B requests Tenant A record | Any | `404 Not Found` | `NO_ACTIVE_TGA_APPROVAL_FOR_PATIENT` |
| **Gate Error / Timeout** | DB error or unhandled exception | Any | `500` / `BLOCKED` | `TGA_GATE_FAIL_CLOSED` |

---

## Out of scope for the MVP
- Email and PDF ingestion (doc 11)
- OCR / extraction and confidence scoring (doc 11)
- Automatic regulator lookups
- Bulk import
- Regulator-defined exceptions to the 2-year window (R3)

## Open items
| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | Doc 08 §4 says *"an exclusion constraint is deliberately not used"* and defines a plain `UNIQUE` at the grain; docs 04, 20, 23 and Gate 2 require a partial GiST exclusion on overlapping `active` intervals. A unique-at-grain is incompatible with the supersede chain. R11 adopts the exclusion constraint | CTO + Clinical Safety Officer | OPEN — decision recorded as D-006 |
| OPEN-2 | Is `valid_to` inclusive or exclusive? Doc 08 §5 says inclusive, doc 04 §3.6 says half-open — a one-day difference at the safety boundary | Clinical Safety Officer | OPEN — interim fail-safe is half-open |
| OPEN-3 | Exceptions to the 2-year window | Legal/regulatory adviser | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-4 | Is four-eyes verification mandatory for every approval, or only where configured? | Practice Owner + CSO | OPEN |
| OPEN-5 | Whether a verified approval can be reversed in place, or only revoked | Clinical Safety Officer | OPEN |
| OPEN-6 | Retention period for approval records | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
