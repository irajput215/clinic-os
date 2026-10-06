# Patient activity: requirements

**For:** Clinicians and auditors who need to see who did what to a record.

## User stories

- As the principal, I see a patient record's audit trail, newest first, with each event's hash.

## Functional requirements

- R1 The Activity tab lists audit events for the patient (`resource_id`), newest first, up to 50.
- R2 Each row shows when, action, actor role, result (and reason), and the first 12 characters of its chain hash.
- R3 Without `audit:read` the tab explains the role boundary instead of showing an error.

## Non-functional

- Reading the trail is itself audited, server-side.

## Out of scope (this phase)

- Chain verification UI and export (compliance screens).
