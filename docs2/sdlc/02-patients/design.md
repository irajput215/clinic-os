# Patients: design

## Screens

### Patients (`/patients`)

Header with Add patient; a server-side search field (name, date of birth or PT- reference) with a live count; table of patient, mono `PT-` reference, DOB · age, mobile, suburb. The whole row is clickable and keyboard-activatable.

### Patient record (`/patients/$id`)

Back link, serif name, mono reference · DOB (age) · sex, Edit details, underlined tab strip. Overview has a details card plus active approvals and upcoming appointments.

### Add/edit dialog

Two-column form; errors inline under each field.

## States

List: skeleton rows, empty state with an Add action, a no-match state for a search, `403` explanation, retry on failure, and a "Showing N of M" footer with Load more when there is more than one page. Record: `notFoundComponent` for `404`/`422`.

## Data flow

`patientPagesQuery(q)` (an infinite query: `GET /patients?cursor=` with no term, `POST /patients/search` with one; the term is debounced and held in component state, never the URL), `patientQuickFindQuery(q)` for the top-bar quick-find, and `patientQuery(id)`. `patientsQuery` (first page) remains for other features' patient pickers. A create seeds the detail cache, then invalidates the list.

Tokens and components: [design-system.md](../../design-system.md).
