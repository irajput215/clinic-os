# Calendar and booking: design

## Screens

### Calendar (`/calendar?date=&view=`)

Prev/Today/Next, a serif date, a Day/Week segmented control, then the grid. Clicking an empty slot opens New appointment prefilled with that practitioner and time. Clicking a block opens its details and status actions.

### Public booking (`/book/$slug`)

A stepped card (Visit, About you, Time) on the tiled backdrop, then a confirmation with a mono reference.

## States

Overlap and illegal transitions are shown inline in the dialog (`role=alert`). Slots show a spinner while loading. Public form errors appear per field.

## Data flow

`appointmentsForDatesQuery(dates)`. Mutations invalidate `['appointments']` and `['dashboard']`.

Tokens and components: [design-system.md](../../design-system.md).
