---
doc_id: OZ-FEAT-04-STORY
title: "FEAT-04 — TGA Approval Module: User Stories & Acceptance Criteria"
owner: Head of Product
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-04
phase: 02-phase-2-tga-approval-engine
gate: [2, 4]
source:
  - clinic-os-secure-by-design/22-user-stories.md
  - clinic-os-secure-by-design/06-authentication-rbac.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A).

## Prescriber
**US-1** As a prescriber, I want to record a TGA approval for my patient so that I can prescribe the
approved product.
- Acceptance: approval saved as `pending_verification` with all grain fields.
- S: only users holding `tga_approval:create` in the same tenant; tenant is never read from the request.
- A: `approval.created` with actor, tenant, patient reference, grain, request ID.

**US-2** As a prescriber, I want to see which approvals are active, expiring or expired for a patient.
- Acceptance: list shows status and `valid_to`; expired items are visually distinct.
- S: results restricted to the caller's tenant by RLS, and by `tga_approval:read`.
- A: `approval.read` once per patient-level access, not per row.

## Clinic administrator
**US-3** As an administrator, I want to enter an approval received from the TGA on a prescriber's behalf.
- Acceptance: record created `pending_verification`, linked to the prescriber.
- S: admin cannot verify their own entry.
- A: created and verified events carry different actor IDs.

**US-4** As an administrator, I want to be warned about approvals expiring in the next 90 days.
- Acceptance: warning list computed server-side.
- S: warning data respects tenant scope.
- A: none beyond read-access logging.

## Verifier (prescriber or practice owner)
**US-5** As a verifier, I want to confirm a pending approval against the source document.
- Acceptance: status becomes `active`, verifier recorded, `verified_at` set.
- S: verifier must differ from creator; step-up required.
- A: `approval.verified` with before and after status.

## Practice owner
**US-6** As a practice owner, I want to revoke an approval with a reason.
- Acceptance: status becomes `revoked`, reason code stored, the gate refuses dispatch immediately.
- S: step-up; `tga_approval:revoke`.
- A: `approval.revoked` with reason **code** (free text never written to the log line).

## Compliance auditor
**US-7** As an auditor, I want read-only access to approvals and their history.
- Acceptance: can list and view, cannot change anything.
- S: write endpoints return `403` and are audited.
- A: every auditor read is logged.

## Pharmacy (if in MVP scope)
**US-8** As a dispensing pharmacy user, I want to see only the approval status needed to dispense.
- Acceptance: response carries status and grain only.
- S: field-level minimisation; no unrelated patient data.
- A: `approval.read` with role `pharmacy`.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Role names above are placeholders; align to doc 06 before build | CTO | OPEN |
| Is the pharmacy story in MVP scope? | Head of Product | OPEN |
