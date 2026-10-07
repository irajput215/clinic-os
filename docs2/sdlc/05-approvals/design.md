# TGA approvals: design

## Screens

### Approvals register (`/approvals`)

Filter chips with counts; table of patient, mono reference, grain, letter window with a countdown pill when expiring, state pill, Verify/Revoke.

### Patient record → TGA approvals

The same table without the patient column, plus Record approval.

### Dialogs

Record (with the D-006 note), Verify (summary plus re-type the reference), Revoke (summary plus reason code).

## States

The register's list needs `GET /api/v1/tga-approvals`, which does not exist. Until it does, the register replaces its filters and table with a designed refusal that names the endpoint and links to Patients, where each patient's approvals are live. Record approval still works from the register.

Refusals are shown inline with the server's sentence: `VERIFIER_CANNOT_BE_CREATOR`, `TGA_APPLICATION_NUMBER_MISMATCH`, `TGA_OVERLAPPING_ACTIVE_APPROVAL`, `ILLEGAL_STATE_TRANSITION`.

## Data flow

`approvalsQuery` (register) and `patientApprovalsQuery(id)`. Mutations invalidate approvals, dashboard and scripts (the gate depends on approvals).

Tokens and components: [design-system.md](../../design-system.md).
