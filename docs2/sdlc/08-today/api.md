# Today: API

**Status: Built 2026-10-08 (Milestone 2, phase 2E)** in `backend/app/modules/dashboard/`, to the shape
below, for the owner's review. The proposal this replaces was one line ("`TodaySummary`, see
`src/data/types.ts`"); the reconciliations with `docs/` and with that proposal are listed at the end.

The route follows the repo's non-negotiables: tenant from the session only, RLS (enabled and forced) on
every table it reads, audit in the same transaction, RFC 7807 errors with `detail.code`.

## Endpoint

| Method | Path | Permission | Contract |
|---|---|---|---|
| `GET` | `/api/v1/dashboard/today` | per section (below); an inactive account is `403` | `TodaySummary`, one read, rate limit 300/min per session |

```text
TodaySummary {
  date: "YYYY-MM-DD"            today in the clinic, from the database clock
  timezone: "Australia/Sydney"
  appointments: DaySchedule | null
  scripts: PrescriptionQueueSummary | null
  approvals: TgaApprovalDigest | null
  withheld: ("appointments" | "scripts" | "approvals")[]
}
```

| Section | Permission | Read through | Shape |
|---|---|---|---|
| `appointments` | `patient:read` (as `GET /appointments`) | `appointments.service.day_schedule` | `{by_status: {BOOKED..NO_SHOW: n}, data: AppointmentRead + practitioner_name}`: every booking **starting** in today's `[00:00, 24:00)` in Sydney (23 or 25 hours on a DST change), earliest first, cancelled and no-show included |
| `scripts` | `prescription:read` (as `GET /prescriptions`) | `prescriptions.service.queue_summary` | `{by_state: {every state: n}, transport_configured, actionable: PrescriptionRead[], gate_refused, gate_checked}`: the 8 newest `DRAFT`/`SIGNED`/`BLOCKED`/`FAILED` scripts, each with the gate's answer **now** (`gate.advise`, display only), and how many of the (at most 100) newest actionable scripts the gate refuses now |
| `approvals` | `tga_approval:read` (as `GET /tga-approvals`) | `tga_approvals.service.needs_action_digest` | `{pending_verification, expiring, expiring_within_days: 30, pending: RegisterRow[], expiring_soon: RegisterRow[]}`: the register's "Needs action" set split in two, at most 10 each, pending oldest first, expiring soonest first; the counts are the practice's totals |

**A section the caller cannot read is withheld, not refused.** It is `null` and named in `withheld`, and
its data is never queried, so nothing can leak through the response shaping. The page is everyone's
landing screen: reception (`ADMINISTRATOR`) reads the schedule and approvals but not scripts, a
`PHARMACY` account reads the schedule only, and an account with no role gets `200` with every section
withheld. A refused identity (inactive account) is refused outright, like every route.

**One transaction, one "today".** The three sections are read in one `tenant_transaction` opened with the
resolved tenant and the actor. `now()` is the transaction's start time, so every section agrees on the
date. The transaction is `READ COMMITTED` (the helper's default), so the sections are not a single
snapshot; a write landing between two section reads can show in one and not the other until the next
read (`staleTime` 10 s).

**Never another module's table.** The dashboard owns no table. Each section is the owning module's own
read model, built by that module's facade on the dashboard's session (`AGENTS.md`, build contract §7).

## Audited

Each section is audited exactly as its owning module audits its own list route, on the same transaction:

| Section | Event | Payload |
|---|---|---|
| `approvals` | `tga_approval.read` `SUCCESS` (the register's event) | `query_filters: {state: ["PENDING"], expiring_within_days: 30}`, `result_count` (rows returned) |
| `appointments` | none, like `GET /appointments` (deferred with `patient.read`, T1-34) | - |
| `scripts` | none, like `GET /prescriptions` (the closed catalogue has no prescription read action) | - |

**No catalogue action was added.** Auditing the whole page would need a new action (for example a
`dashboard.read`), which is a change to the closed catalogue (`docs/features/04-audit-log/05-data-and-audit.md`)
and the owner's decision, not this phase's. The gaps above are the same ones the appointments and
prescriptions modules already record.

A `tenant_id` query parameter is ignored. When the approvals section is read it is written down on that
section's event as `CLIENT_TENANT_ID_IGNORED` (INV-1); when it is withheld there is no event to carry it
(the same gap as above).

## Reconciliations

- The proposal's `TodaySummary` (`appointments`, `scripts_awaiting`, `scripts_blocked`,
  `approvals_expiring` with `days_left`, and server-written `attention` sentences) is replaced by the three
  sections above. The server returns data, not prose: the page writes the "needs attention" sentences
  and computes days left from `date` with the same D-006 helper the register uses (`lastCoveredDay`).
- "Scripts blocked" (R1) is `gate_refused`: how many actionable scripts the gate refuses **now**
  (a draft with no covering approval as well as a script in `BLOCKED`; a `BLOCKED` script whose
  approval has since been verified is no longer counted). The server asks the gate about at most the
  100 newest actionable scripts per read (`gate_checked` says how many); when there are more, the
  page marks the count as a lower bound with a `+`.
- "Expiring" uses `tga_approvals.service.last_expiring_valid_to` (D-006 half-open `[)`): an approval's
  last covered day is `valid_to - 1`. Already-lapsed `ACTIVE` approvals the expiry job has not reached
  count as expiring, as on the register.
- The schedule names each booking's practitioner (`practitioner_name`), so the page needs no second
  request for the roster (R1's "one request").
- Not built: pay runs, payment issues, consent re-collection (out of scope, [requirements](requirements.md)).
