# Today: requirements

**For:** Everyone, first thing in the morning and between patients.

## User stories

- As the principal, one screen tells me today's schedule, what's waiting for me, and what will block scripts soon.

## Functional requirements

- R1 Four KPI tiles, each linking to its screen: appointments today (done / to come), scripts needing action (blocked count), approvals to verify, approvals expiring within 30 days.
- R2 Today's schedule: time, patient and type, practitioner, status. A row opens the patient.
- R3 Script staging queue: up to 8, with compact gate pills ("Blocked · No approval").
- R4 Needs attention: approvals expiring soon, approvals awaiting verification, blocked scripts, each linking to where it's fixed.
- R5 SAS-B / AP renewals table with a countdown to the last covered day.

## Non-functional

- One request in API mode (proposed endpoint).

## Out of scope (this phase)

- Pay runs, payment issues, consent re-collection (business features, later phases).
