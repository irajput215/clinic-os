---
doc_id: FEAT-PAT-02
title: Patients, user stories
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A). Source stories are
`22-user-stories.md` US-10, US-11 and US-14, plus `20-product-requirements.md` §3.

## Receptionist / Administrator
**US-1** As an administrator, I want to register a patient, so that the person has a record before the
first consultation.
- Acceptance: `POST /api/v1/patients` returns `201`; all required demographics stored; `tenant_id` from
  the session.
- S: `patient:create`; strict schema, unknown fields rejected; identifier values validated before the
  database.
- A: `patient.created` with actor, tenant, `resource_id` and `field_set` (field names only, never values).

**US-2** As an administrator, I want to be warned about a likely duplicate, so that one person does not
receive two clinical records.
- Acceptance: an exact two-identifier match refuses the create and returns the candidate; the existing
  record can be opened instead.
- S: tenant-scoped candidate lookup; identifier values masked in the response and absent from logs.
- A: `patient.read` for the candidate lookup; the refusal writes `result=DENIED` with the match reason.

**US-3** As an administrator, I want to merge two records confirmed as the same person, so that the
history is unified.
- Acceptance: merge sets `merged_into_patient_id` on the losing record; both original identifiers are
  preserved; the surviving record is named in the response.
- S: `patient:merge` **and** step-up; the losing record is never deleted or overwritten.
- A: `patient.merged` with survivor id, merged id, reason and `step_up=true`.

**US-4** As an administrator, I want to reverse a wrong merge, so that no clinical history is hidden.
- Acceptance: reverse clears the link and restores both records exactly as before; a designed procedure,
  not a database restore.
- S: `patient:merge` and step-up; reversal is itself reversible and audited.
- A: `patient.merge_reversed` with the merge reference and reason.

## Treating Doctor / Nurse
**US-5** As a nurse, I want to read the records of patients in my care, so that I can coordinate
treatment without seeing patients who are not mine.
- Acceptance: a patient in my care returns only the fields my permission allows; a patient in my clinic
  but not in my care is refused.
- S: `patient:read` plus the treating-relationship rule and RLS; denial carries no existence leak.
- A: `patient.read` with `care_relationship_id` and `purpose` — **including every denied read**.

**US-6** As a doctor, I want to correct a patient's demographics, so that the record stays accurate.
- Acceptance: `PATCH /api/v1/patients/{id}` returns `200`; only changed fields are written.
- S: `patient:update` plus the treating-relationship rule; `changed_fields` allow-list, no entity spread.
- A: `patient.updated` with `changed_fields` (names only) and `reason`.

**US-7** As a treating clinician, I want identifier lookups by exact value, so that I can confirm I have
the right person.
- Acceptance: an exact Medicare or IHI value returns the single matching patient in my tenant, or nothing.
- S: equality on the keyed blind index only; no prefix, fuzzy or sort on an encrypted column.
- A: `patient.read`; the search term itself is never written to the audit payload.

## Clinical Safety Officer
**US-8** As a Clinical Safety Officer, I want to see who viewed a patient's record, so that access can be
reviewed.
- Acceptance: per-patient access history lists actor, role, time, purpose and result for reads and
  refusals.
- S: `audit:read`, tenant-scoped; the history is read-only.
- A: `audit.read` is itself audited, including an empty result.

**US-9** As a Clinical Safety Officer, I want proof that no patient record was destroyed and that merge
lineage survives, so that medical history is intact.
- Acceptance: no `DELETE` grant exists on `patients`; merge and reversal events reconstruct the lineage.
- S: grant inspection in CI; no delete endpoint or code path exists.
- A: `patient.merged` and `patient.merge_reversed` provide the lineage; deletion certificates are the
  retention engine's evidence, not this module's.

**US-10** As a practice owner, I want to export patient-level data for a stated purpose, so that a
legitimate request can be met under control.
- Acceptance: export requires step-up and a typed reason; output is tenant-scoped and record-counted.
- S: `patient:export` plus step-up (5 minutes, single use) plus a mandatory purpose code.
- A: `patient.exported` with `record_count`, `purpose` and `step_up=true`.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| "Receptionist" is not a role in `06-authentication-rbac.md` §9; it is treated as `ADMINISTRATOR` for MVP | Head of Product | OPEN |
| Treatment of `US-5`/`US-6` depends on `care_relationships`, which has no ERD table or owner | Clinical Safety Officer | **OPEN — blocked** |
| Whether a patient may hold both a Medicare number and an IHI, and the collection basis for each | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
