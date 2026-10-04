---
doc_id: FEAT-AUD-02
title: Audit log, user stories
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 07-audit-architecture, 21-technical-design, 26-security-gates
source:
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §3, §4, §8, §9, §10
  - clinic-os-secure-by-design/22-user-stories.md
  - clinic-os-secure-by-design/26-security-gates.md §3
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A).

## Security Lead

**US-1** As the Security Lead, I want to prove the application role cannot alter or erase the trail, so
that a compromised application server cannot rewrite history.
- Acceptance: the grant set is exactly `{SELECT, INSERT}`; direct `UPDATE`/`DELETE`/`TRUNCATE` fail with
  `42501 insufficient_privilege`; the app role is not the owner and has no `BYPASSRLS`.
- S: enforcement is by grant, not convention; a chain alone is detection, not prevention.
- A: the refused attempt is recorded, and an audit-write failure alerts SEV2.

**US-2** As the Security Lead, I want a hash chain over events, so that a modification or deletion of a
row is detectable rather than silent.
- Acceptance: `hash = SHA-256(canonical_json(event without hash) ‖ prev_hash)`; genesis is 64 zeroes; a
  modified row is reported as a break at its sequence number.
- S: the verification job runs continuously over the last 24 h every 15 min and in full per partition.
- A: a detected break raises a P1 incident and stops the export upload rather than shipping the break.

**US-3** As the Security Lead, I want a failed audit write to fail the operation, so that no clinical
change happens without its evidence.
- Acceptance: the domain transaction rolls back, the response is `500` with a request ID, and an alert
  fires; no orphan audit row survives a rollback.
- S: fail closed — a change that cannot be audited must not happen.
- A: the failure is surfaced with `result = FAILED` and a reason code; no new action name is invented
  for it (it must be registered in doc 07 §1 first if one is needed).

## Compliance / Auditor

**US-4** As a Compliance/Auditor, I want to prove which person accessed a patient record and when, and
for what purpose, so that I can answer an access-accounting request.
- Acceptance: `patient.read` and `clinical_record.read` carry actor, role at decision time, resource id,
  care-relationship id and purpose; results are scoped to my tenant by RLS.
- S: `audit:read` is granted to Practice Owner, Administrator and Compliance/Auditor, and to no other
  role.
- A: every read writes `audit.read` with the filters and the result count, including an empty result.

**US-5** As a Compliance/Auditor, I want to prove the trail was not edited after the fact, so that the
evidence I present is admissible.
- Acceptance: the exported JSONL sequence carries the same chain as the database; the signed full-chain
  verification report is retrievable from the Object Lock bucket.
- S: Object Lock in `COMPLIANCE` mode means neither the application role nor a platform administrator
  can shorten or remove the retention period.
- A: the export itself is audited as `audit.read` with `reason = EXPORT`.

**US-6** As a Compliance/Auditor, I want to receive no row belonging to another tenant, not even as a
count, so that a cross-tenant disclosure cannot occur through the audit surface.
- Acceptance: tenant B identifiers return `200` with an empty result and zero rows; an event id from
  tenant B returns `404` and is never a `403`.
- S: RLS plus the policy layer; `NULLIF(current_setting('app.tenant_id', true), '')` matches nothing
  when the tenant is unset.
- A: the attempted cross-tenant read is itself audited with the actor and the filters.

## Practice Owner

**US-7** As a Practice Owner, I want to export the evidence bundle for an audit or a regulator request.
- Acceptance: an export produces a CSV or JSONL bundle for a range of at most 90 days, written to a
  tenant-scoped prefix, delivered as a short-lived presigned URL, and audited with `reason = EXPORT`.
- S: export requires `audit:read`; a range wider than 90 days requires the export path, not the query
  path; the bundle is tenant-scoped.
- A: the export bundle content is audited and the read that produced it is audited.

**US-8** As a Practice Owner, I want a hold placed on records under investigation, so that a scheduled
job does not destroy evidence.
- Acceptance: a legal hold blocks the partition drop for the held scope; release resumes the next run.
- S: hold placement and release are restricted to named roles with a written reason.
- A: the hold, the review and the release are all audit events.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Role names above are the source's; reconcile with the central policy layer of feature 03 before build | Security Lead | OPEN |
| Whether an export purpose code is required for every query filter, not only exports | Privacy Officer | OPEN |
| Whether the Practice Owner or the Administrator holds the export permission in the pilot | Head of Product | OPEN |
