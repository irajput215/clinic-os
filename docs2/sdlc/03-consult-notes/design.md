# Consult notes: design

## Screens

### Patient record → Consult notes

A New consult note card (2×2 SOAP textareas, Save note) above a Consult history card listing notes, each with Signed/Draft/Amended pills and Sign or Amend actions.

### Amend dialog

Prefilled SOAP sections plus a required reason.

## States

History skeleton, empty history, retry on failure. Sign and amend refusals are shown in a toast with the server's reason.

## Data flow

`patientRecordsQuery(id)`. Mutations invalidate `['records','patient',id]`.

Tokens and components: [design-system.md](../../design-system.md).
