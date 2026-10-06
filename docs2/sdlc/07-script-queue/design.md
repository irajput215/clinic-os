# Script queue and safety gate: design

## Screens

### Script queue (`/scripts`)

Awaiting action cards with a left accent (warn for awaiting, danger for blocked): patient, mono ref, state and gate pills, product line, drafted-by line, triage box, Review & sign. Then the Recent activity table.

### Review & sign dialog

Script summary, gate panel (green clear or red blocked with code), password, Sign & send to pharmacy.

### Stage a script dialog

Waits for the product and practitioner lists before mounting, so a select never shows a different value from the one held.

## States

Toasts: success on send; **warning** when staged without a covering approval. Inline refusals in the dialog.

## Data flow

`scriptsQuery` for the queue and badges, `approvalsRepo.match` for the gate panel. Mutations invalidate scripts and dashboard.

Tokens and components: [design-system.md](../../design-system.md).
