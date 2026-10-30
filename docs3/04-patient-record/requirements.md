# Patient record: requirements

**For:** reception and clinicians; it is what intake (03) writes into.
**Manual:** §3.2 (statuses), §3.4 (field reference, eScript-ready rule), §3.5 (register by phone,
change pharmacy).
**Builds on:** `backend/app/modules/patients/` and `docs/features/05-patients` (R8 encryption, R9
masking, which this feature finally switches on).

## User stories

- As reception, I register a patient over the phone with everything an eScript will later need.
- As anyone on the record, I see at a glance the patient's status, alerts and whether they are eScript-ready.
- As a patient who opted out of marketing, I still get my booking and script messages, and nothing else.

## Requirements

### Lifecycle status

| # | Requirement | Manual |
|---|---|---|
| R1 | Every patient has exactly one status: `CURRENT`, `REVIEW`, `WAITING_LIST`, `CLAIMANT`, `ARCHIVED`, `DISCHARGED`, `BLOCKED`, `DECEASED`. New records from staff start `CURRENT`; from the public application, `CURRENT` only on accept (03 R14) | §3.2 |
| R2 | Changing status needs `patient:update`, records a reason (required for `BLOCKED`, `ARCHIVED`, `DISCHARGED`), and is audited | §3.2 |
| R3 | `BLOCKED` refuses new bookings (staff and public) and new script drafts, naming the block — fail closed | §3.2 |
| R4 | `DECEASED` is the existing `deceased_at` made visible; setting it needs a date. Nothing is ever hard-deleted | §3.2, App. C |
| R5 | The patient list gains a status filter; `ARCHIVED`, `DISCHARGED`, `DECEASED` are hidden by default | §3.1 |

### Fields

| # | Requirement | Manual |
|---|---|---|
| R6 | **Sex** becomes required on create (eScripts need it). Existing records without it show "needed for eScripts" | §3.4 |
| R7 | **Address** stays structured (line, suburb, state, postcode); entered as one line and split, validated as an AU address. Autocomplete only with D7c | §3.4 |
| R8 | **Medicare** 10 digits + IRN 1–9: format-checked on entry (D12), stored encrypted with a blind index (`docs/features/05-patients` R8), shown masked `•••• ••• 123` (R9). "Verified" means format-checked until D7d | §3.4 |
| R9 | **IHI** 16 digits starting `800360`, direct entry, encrypted with a blind index, masked. Exact-match search by Medicare or IHI uses the blind index (body only, never the URL) | §3.4 |
| R10 | **Alerts**: short text with a tone (info / warn / danger); shown on the record header and in patient pickers. Add / remove audited | §3.4 |
| R11 | **Emergency contacts**: name, relationship, phone; any number | §3.4 |
| R12 | **Receives communications** (default on). Off silences reminders and any future campaigns; transactional messages (booking confirmation, script and pharmacy notices) still send | §3.4, §11 |
| R13 | **Timezone** defaults to the clinic's; reminders use it | §3.4 |
| R14 | **Preferred pharmacy** from the directory (03); *Change pharmacy* on the record, audited | §3.5 |

### eScript-ready

| # | Requirement | Manual |
|---|---|---|
| R15 | A patient is **eScript-ready** when IHI, sex, and a complete street address are all present. The record header shows ⚡ eScript-ready, or what's missing | §3.4 |
| R16 | Computed by one server function; the frontend never decides it (INV-3). Prescribing does not yet enforce it (no eRx rail, D7e) — the chip is information until Phase 7 | §3.4, §6.5 |
