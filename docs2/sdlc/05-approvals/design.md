# TGA approvals: design

## Screens

### Approvals register (`/approvals`)

Filter chips with counts (Needs action, Active, Pending, Expired & revoked, All); table of patient, mono reference, grain, letter window with a countdown pill when expiring, state pill, Verify/Revoke.

- Each chip is a link to `/approvals?filter=<key>`, so the filter survives Back from a patient and the current chip is `aria-current="page"`. The filter is a code, never PHI.
- Each chip's count is the practice's total from the response's `counts`, never a count of the loaded rows.
- Rows are newest first, 50 per page. Under the table: "Showing N of M, newest first" and **Show more**, which fetches the next keyset page and appends it.
- The patient cell links to the patient's TGA approvals tab by the name the API returned; a patient whose record is no longer readable shows "Record removed", unlinked.

### Patient record → TGA approvals

The same table without the patient column, plus Record approval.

### Dialogs

Record (with the D-006 note), Verify (summary plus re-type the reference), Revoke (summary plus reason code).

## States

| State | Register |
|---|---|
| Loading | Skeleton rows in the card; chips render without counts |
| Empty | A sentence per filter (for Needs action: nothing pending or expiring within 30 days) |
| Error | Inline error with the request reference and Try again; a failed "Show more" keeps the loaded rows and offers a retry under them |
| `403` | No chips; "Not available to your role." |

Refusals are shown inline with the server's sentence: `VERIFIER_CANNOT_BE_CREATOR`, `TGA_APPLICATION_NUMBER_MISMATCH`, `TGA_OVERLAPPING_ACTIVE_APPROVAL`, `ILLEGAL_STATE_TRANSITION`.

At phone width the table scrolls inside its card; the page never scrolls sideways.

## Data flow

`registerQuery(filter)` (an infinite query over `GET /tga-approvals`), `approvalCountsQuery` (the sidebar's pending count, one row asked for) and `patientApprovalsQuery(id)`. Mutations invalidate approvals, dashboard and scripts (the gate depends on approvals).

Tokens and components: [design-system.md](../../design-system.md).
