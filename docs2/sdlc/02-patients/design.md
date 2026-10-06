# Patients: design

## Screens

### Patients (`/patients`)

Header with Add patient; filter pill; table of patient, mono `PT-` reference, DOB · age, mobile, suburb. The whole row is clickable and keyboard-activatable.

### Patient record (`/patients/$id`)

Back link, serif name, mono reference · DOB (age) · sex, Edit details, underlined tab strip. Overview has a details card plus active approvals and upcoming appointments.

### Add/edit dialog

Two-column form; errors inline under each field.

## States

List: skeleton rows, empty state with an Add action, `403` explanation, retry on failure. Record: `notFoundComponent` for `404`/`422`.

## Data flow

`patientsQuery` (`GET /patients?limit=25`) and `patientQuery(id)`. A create seeds the detail cache, then invalidates the list.

Tokens and components: [design-system.md](../../design-system.md).
