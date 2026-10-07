# Patients: requirements

**For:** Clinicians and reception who register patients and open their records.

## User stories

- As reception, I add a new patient with identity and contact details and land on their record.
- As a clinician, I find a patient by name and open their record.
- As a clinician, I correct a patient's contact details.

## Functional requirements

- R1 The list pages through every patient (25 at a time, "Load more") and searches the server by name prefix, date of birth or PT- reference. The search term stays out of every URL.
- R2 Add and edit validate before submit: names required, DOB not in the future, AU mobile shape, 4-digit postcode, valid email. The server re-validates.
- R3 Sex at birth uses the backend's closed vocabulary (FEMALE, MALE, INTERSEX, UNKNOWN).
- R4 After create the app navigates to the new record. After edit the record and list refresh.
- R5 An unknown id, or another organisation's, shows "not available" (the API answers `404` for both).
- R6 The record has tabs: Overview, Consult notes, TGA approvals, Scripts, Appointments, Activity. The tab is in the URL (`?tab=`).
- R7 There is no delete (R11 in docs/features/05-patients).

## Non-functional

- The list renders from cache on revisit; new data is fetched in the background (30 s stale time).

## Out of scope (this phase)

- Medicare/IHI capture (needs field-level encryption, feature 05 design).
