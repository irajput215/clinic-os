# Today: design

## Screens

### Today (`/`)

Header, preview banner, KPI row, then two columns: schedule and staging queue on the left (wider), needs attention and renewals on the right. Stacks on narrow screens.

## States

Route pending skeleton and route error component. Each card has its own empty state.

## Data flow

`todayQuery`, plus `practitionersQuery` for names.

Tokens and components: [design-system.md](../../design-system.md).
