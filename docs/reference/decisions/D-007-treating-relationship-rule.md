# D-007: The treating-relationship rule - who it binds, where relationships come from, the read purpose

- **Status:** **Accepted** for the mechanism (the rule as the feature documents specify it) · 🔴 **OPEN -
  requires a decision** for the three interim choices below (source of truth, purpose vocabulary, roles
  bound), each implemented fail-safe
- **Date:** 2026-10-08
- **Owner:** Security Lead (source of truth, C13) · Clinical Safety Officer (roles bound, US-9; source,
  `05-patients` OPEN-4) · Privacy Officer (purpose vocabulary)
- **Task:** T1-34 (`docs/tasks/01-phase-1-foundations.md`)
- **Source references:** `05-patients/01-requirements.md` R7, R13 and the negative decision matrix;
  `05-patients/03-design.md` "Treating-relationship rule"; `06-clinical-records/01-requirements.md` R11,
  `03-design.md` "Treating-relationship check", `02-user-stories.md` US-5/US-7;
  `03-users-and-roles/01-requirements.md` permission catalogue (`cr` modifier), `04-threat-model.md`
  T-03.1; `10-prescription-safety-gate/03-design.md` (`GET /prescriptions/{id}`: treating relationship);
  `11-prescribing/02-user-stories.md` US-1; `open-questions.md` C13

## Context

The documents fix the rule completely: a read (and, for clinical records, a write) of a patient needs
the permission **and** an active care relationship in the same tenant; the refusal is
`403 AUTHZ_CARE_RELATIONSHIP_DENIED`, audited with equal fidelity; across a tenant boundary the answer
stays `404`; the relationship is read under the request's RLS policy and is never inferred from clinic
membership or widened to the tenant; an accepted read records `care_relationship_id` and `purpose`. The
`care_relationships` table exists (T1-04).

Three things the documents leave **open**, and the rule cannot run without an answer to each:

1. **Who maintains `care_relationships`** (open-questions C13, `05-patients` OPEN-4,
   `06-clinical-records` OPEN-3). No document says whether a relationship comes from a booking, a first
   consult, a referral, or an explicit act.
2. **The `purpose` vocabulary.** `patient.read` and `clinical_record.read` must carry a `purpose`; no
   document lists the values.
3. **Which roles the rule binds.** The matrix marks `cr` on exactly four cells per role for `DOCTOR` and
   `NURSE` (`patient:read`, `patient:update`, `clinical_record:read`, `clinical_record:write`) and on no
   cell of `PRACTICE_OWNER`, `AUTHORISED_PRESCRIBER` or `ADMINISTRATOR`; US-9's open item asks the
   Clinical Safety Officer to confirm the rule per role.

## Decision

### The mechanism (accepted: the documents' own rule)

- **Who is bound:** a grant the matrix marks `cr`
  (`app/modules/users_roles/catalog.py` `CARE_RELATIONSHIP_SCOPED_GRANTS`). Grants are additive: an
  account that also holds the permission through an unmarked role is not bound. A role code outside the
  seven system roles is bound for everything (fail closed). The policy layer never compares a role name:
  the actor carries `unscoped_permissions`, resolved from the same rows as its permissions, and `can()`
  refuses a `PatientResourceRef` without a relationship when the permission is outside that set.
- **Where it runs:** every route that reaches one patient's record - the patient read and update, every
  clinical-record route, and the patient-scoped reads of other modules (a patient's appointments,
  scripts and TGA approvals, which are decided as a `patient:read` of that patient), plus staging a
  script (`11-prescribing` US-1). The relationship is a scalar subquery **in the route's first
  statement**, under the same transaction, tenant context and forced RLS policy, so it costs no round
  trip and cannot see another tenant's row.
- **Order:** tenant (`404`, the row is never found) → permission (`403 PERMISSION_NOT_HELD`) →
  relationship (`403 AUTHZ_CARE_RELATIONSHIP_DENIED`). Every refusal is audited `DENIED` with its reason.
- **Lists:** `GET /patients` and `POST /patients/search` are "treating-relationship filtered"
  (`05-patients/03-design.md`) for a bound reader, total included.

### Interim 1 - the source of truth (OPEN, fail-safe)

A relationship exists only because a person recorded it, and nothing creates one implicitly: not a
booking, not a consult note, not clinic membership. The recorder must hold `patient:update`
**unconditionally** (practice owner, authorised prescriber, administrator), so nobody can record a
relationship that grants themselves access. Three routes (`docs2/sdlc/02-patients/api.md`, "Care
team"): list the active team, record (`source = STAFF_RECORDED`, `active_from = now()` on the database
clock), end (`active_to = now()`; the row is never deleted). Both writes are audited on the same
transaction (`care_relationship.create`, `care_relationship.end`, registered in the catalogue for this
decision) and rate limited as administration (20/min per session, T-03.11).

Fail-safe because it can only *grant less* than any automatic source would: until the Security Lead and
the Clinical Safety Officer choose a source, a doctor or nurse sees exactly the patients a responsible
person put them in the care team of. Candidates the decision should weigh, and why none was chosen
here: a booking (reception would grant clinical access by scheduling), a first consult note (a
clinician would grant themselves access by writing), a referral (no referral model exists). Whether
recording a relationship should need step-up is part of the same decision.

### Interim 2 - the purpose (OPEN, Privacy Officer)

Server-derived, never client-supplied: `TREATMENT` when an active care relationship authorised the
access, `PRACTICE_ADMINISTRATION` when an unconditional grant did. A client cannot widen or misstate it.
The `pl` (mandatory, typed purpose code) modifier on the auditor's cells is not built and stays with
the export feature.

### Interim 3 - the roles bound (OPEN, Clinical Safety Officer)

The matrix as written. In particular, an `AUTHORISED_PRESCRIBER`, a `PRACTICE_OWNER` and an
`ADMINISTRATOR` read every patient of their practice without a relationship (audited
`PRACTICE_ADMINISTRATION`). Practice-wide screens that list patient names (the calendar, the script
queue, the approvals register, the Today page) are audited but **not** filtered for a bound reader:
the documents name the filter only for the patient list. Whether they should be is part of the same
decision.

## Consequences

- A doctor-only or nurse-only account sees no patient until it is put on a care team. The patient list
  says so, and a refused record shows "You have no care relationship with this patient" with what to do
  next; it never says anything else about the record.
- Every patient-level read now writes an audit event (`patient.read`, `clinical_record.read`,
  `appointment.read`, `prescription.read`, `tga_approval.read`), which costs the two audit round trips on
  the reads that were not audited before; the pinned counts in
  `backend/tests/performance/test_round_trips.py` carry the reason.
- Closing C13 replaces Interim 1, not the mechanism: whatever the source, it writes the same rows.
