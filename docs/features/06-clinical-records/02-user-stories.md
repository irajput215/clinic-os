---
doc_id: FEAT-CLIN-02
title: Clinical records, user stories
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A). Sources: `22-user-stories.md`
US-11, US-12, US-13; `06-authentication-rbac.md` §9–§10; `20-product-requirements.md` §4. Role labels
must be aligned to `06-authentication-rbac.md` §9 before build (OPEN-6).

## Treating Doctor / Nurse Practitioner

**US-1** As a treating doctor, I want to author a draft clinical note for a patient in my care, so that
the visit is recorded. (`22` US-12)
- Acceptance: `POST /api/v1/clinical-records` returns `201`, `version = 1`, `signed_at` null.
- S: requires `clinical_record:write` and an active treating relationship; `tenant_id` and `author_id`
  come from the session, never the request body.
- A: `CLINICAL_NOTE_CREATED` → `clinical_record.write` with actor, tenant, record id, patient id, version.

**US-2** As a treating doctor, I want to sign my note, so that it is attributable to me and immutable
afterwards. (`22` US-12)
- Acceptance: `POST /api/v1/clinical-records/{id}/sign` sets `signed_at`; the row is then read-only.
- S: identity-bound — only the version's `author_id` may sign it; a different clinician gets `403`.
- A: `CLINICAL_NOTE_SIGNED` → `clinical_record.write` with actor, record id, version.

**US-3** As a treating doctor, I want to amend a signed note without erasing the original, so that the
correction is visible. (`22` US-13)
- Acceptance: `PATCH` on a signed record returns `403 NOTE_ALREADY_SIGNED`; an amendment through
  `POST /api/v1/clinical-records/{id}/amendments` creates `version + 1` with `supersedes_version` and a
  reason, and version 1 stays byte-for-byte readable.
- S: `clinical_record:write`; append only; the amendment path never issues an `UPDATE` against
  `clinical_record_versions`.
- A: `CLINICAL_NOTE_AMENDED` → `clinical_record.write` with actor, record id, new version and
  `supersedes_version` (the reason **code**, never the free text).

**US-4** As a treating doctor, I want the full version timeline in a deterministic order, so that I can
reconstruct what was recorded and when.
- Acceptance: versions returned `ORDER BY version ASC`, oldest first, each with author and `signed_at`.
- S: tenant-scoped by RLS and `clinical_record:read`; the treating relationship is re-checked server-side.
- A: one `CLINICAL_RECORD_VIEWED` per record access, not one per version.

## Consulting Doctor

**US-5** As a consulting doctor, I want to read the chart of a patient I am treating, so that I can
continue care. (`22` US-11)
- Acceptance: `GET /api/v1/clinical-records/{id}` returns the record and its versions; a patient not in
  my care is refused.
- S: permission + tenant + treating relationship, all server-side; RLS is the backstop; `404` across a
  tenant boundary, `403` inside the tenant with no relationship.
- A: `CLINICAL_RECORD_VIEWED` → `clinical_record.read` with `patient_id`, `care_relationship_id` and
  `purpose`; denials audited with equal fidelity.

**US-6** As a consulting doctor, I want the patient's prior records as a timeline, so that I can review
the last 50 entries before I document. (`20` §4 performance target)
- Acceptance: `GET /api/v1/patients/{patient_id}/clinical-records` cursor-paginated, under `200 ms` p95
  with 50 prior entries.
- S: same authorisation path as US-5; no cross-tenant rows.
- A: one `CLINICAL_RECORD_VIEWED` per timeline access.

**US-7** As a consulting doctor, I want explicit refusal when I have no treating relationship, so that I
know to request access rather than assume the record is missing.
- Acceptance: in-tenant request without an active care relationship returns `403`; a cross-tenant ID
  returns `404`.
- S: the relationship is never inferred from clinic membership and never widened to the tenant
  (`06` §10).
- A: denial recorded as `clinical_record.read` with `result = DENIED` and reason
  `AUTHZ_CARE_RELATIONSHIP_DENIED`.

## Clinical Safety Officer

**US-8** As a Clinical Safety Officer, I want read-only access to the version history for a safety
review, so that I can examine whether a correction was made and why, without altering the record.
- Acceptance: read returns every version; create, amend and sign routes return `403` for this role.
- S: read-only; write endpoints refused server-side and audited.
- A: `CLINICAL_RECORD_VIEWED` with `purpose`; each refused write emits a denied event.

**US-9** As a Clinical Safety Officer, I want proof that a signed version cannot be altered, so that the
record is defensible in a complaint or coronial process.
- Acceptance: an attempted in-place update or delete fails as the app role (`42501`) and as the owner or
  migration role (trigger `CLINICAL_RECORD_VERSION_IMMUTABLE`).
- S: the immutability mechanism is asserted in CI (`06-test-plan.md` S7–S11).
- A: the failed attempt is audited; no event carries the narrative.

## Compliance / Auditor

**US-10** As a compliance auditor, I want read-only access within scope, so that I can review clinical
documentation without changing it. (`06` §9 `clinical_record:read`, read-only, purpose logged)
- Acceptance: can read within the tenant, cannot write, cannot delete.
- S: `clinical_record:read` only; every write route returns `403` and is audited.
- A: every auditor read logged with actor, role, patient reference and purpose.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Role labels ("Nurse Practitioner", "Consulting Doctor") are not the role names in `06` §9 | CTO | OPEN |
| `06` §9 grants Nurse `clinical_record:write` *"Granted, care relationship"*, but `27` §5 gives Nurse `403` on `POST /clinical-records/{id}/notes`; US-1 does not settle it | Clinical Safety Officer + CTO | OPEN |
| Clinical Safety Officer has no row in the `06` §9 role-to-permission matrix; US-8/US-9 need a role definition | CTO | OPEN |
| Same-role horizontal escalation (another clinician's draft) is not addressed by a source story | Security Lead | OPEN |
