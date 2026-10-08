# Today: design

## Screens

### Today (`/`)

Header (the clinic's date from the server, the appointment count, who is signed in), KPI row, then two
columns: schedule and staging queue on the left (wider), needs attention and renewals on the right.
Stacks on narrow screens.

- **KPI tiles** link to the screen that fixes each thing: the calendar, the script queue, the register
  filtered to pending (`/approvals?filter=pending`) and to "Needs action" (`?filter=attention`).
- **Schedule** rows open the patient (click, or Enter on the focused row).
- **Staging queue** shows the server's gate on each card: a compact refusal pill ("Blocked · Wrong
  category") when the gate refuses now, otherwise the script's state. When signed scripts are queued
  and no pharmacy transport is configured, the card says so ("queued, not sent").
- **Needs attention** is written by the page from the data: the three soonest renewals, the two
  longest-waiting verifications, and up to two scripts whose gate refuses now.
- **Renewals** lists active approvals whose last covered day is within 30 days, with a days-left pill.

## States

Route pending skeleton and route error component. Each card has its own empty state. A section the
server withheld (the role cannot read it) shows "Not available to your role" in its card and `-` in its
tile, the same lock state a `403` shows elsewhere. There is no preview banner: the page reads the API
([ADR-F006](../../adr/ADR-F006-preview-store-retired.md)).

## Data flow

`todayQuery` (`GET /api/v1/dashboard/today`), one request. Writes elsewhere (booking, staging, signing,
recording or verifying an approval) invalidate `["dashboard"]`.

Tokens and components: [design-system.md](../../design-system.md).
