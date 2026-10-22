# D-010: Correcting a prescription - who edits and cancels, the cancel reason codes, what an addendum does

- **Status:** **Accepted** for the mechanism (FEAT-11 R3, R5, R8, R11, US-2/5/8/10 as written) · 🔴 **OPEN -
  requires a Clinical Safety Officer decision** for the three interim choices below, each implemented
  fail-safe
- **Date:** 2026-10-08
- **Owner:** Clinical Safety Officer (reason codes, who cancels, corrections after dispatch) · CTO (the
  `prescription:cancel` permission)
- **Source references:** `docs/features/11-prescribing/01-requirements.md` R3, R5, R8, R11, R13;
  `02-user-stories.md` US-2, US-5, US-8, US-10 and open items; `03-design.md` state machine and endpoints;
  `05-data-and-audit.md` audit catalogue; `docs2/sdlc/07-script-queue/api.md`

## Context

FEAT-11 names `PATCH`, `addendum`, `cancel`, `history` and the single read, the state machine they
obey, and their audit events (`prescription.modify`, `prescription.reject`, the `prescription.read`
class). It leaves three things open, and a route cannot be built without an answer to each:

1. **The cancel reason vocabulary.** "A reason code, not free text" - and no codes.
2. **Who may cancel or edit.** US-2: "only the prescriber of record or an authorised stager may
   modify". US-8 has a Practice Owner cancel, and its own open item asks whether that needs a
   permission separate from the prescriber's; `prescription:cancel` is a candidate code, not granted.
3. **What an addendum does to the original, and from which states.** "A new version referencing the
   original, whose bytes are unchanged" - but not whether the original stays live, nor whether a
   dispatched script can be amended.

## Decision

- **Edit (`PATCH`)**: `DRAFT` only (`409 INVALID_STATE_TRANSITION` otherwise); `prescription:modify`,
  narrowed to the script's **drafter or prescriber of record** (US-2 verbatim); the care relationship to
  the patient (T1-34, D-007). The event names the changed fields, never a value. The reviewing doctor may
  be changed, validated as on staging.
- **Cancel**: `DRAFT`, `SIGNED`, `BLOCKED` or `FAILED` -> `CANCELLED`, exactly the state machine's
  edges into `CANCELLED`; `QUEUED` (in the outbox), sent and terminal scripts are `409`. Same people as
  the edit. **Interim 1 (OPEN):** the reason is one of a closed list - `ENTERED_IN_ERROR`,
  `CLINICALLY_NOT_REQUIRED`, `PATIENT_DECLINED`, `DUPLICATE` - plus the server-only
  `SUPERSEDED_BY_ADDENDUM`; a database check holds the list and "cancelled exactly when a code is
  recorded". **Interim 2 (OPEN):** cancelling a colleague's script (US-8's owner) is not offered until
  `prescription:cancel` is decided; the owner can still cancel the scripts they drafted or prescribe.
- **Addendum**: `prescription:sign` and the original's **prescriber of record**; the original must be
  `SIGNED`, `BLOCKED` or `FAILED` (signed, never sent). **Interim 3 (OPEN):** in one transaction the
  original moves to `CANCELLED` with `SUPERSEDED_BY_ADDENDUM` - its payload, signature and hash
  untouched - and a new `DRAFT` copying the original's payload with the corrections is created with
  `supersedes_id`; it is signed through the unchanged gate like any script. So exactly one live version
  exists, and nothing signed is ever rewritten. One addendum per original (a further correction amends
  the addendum). A dispatched script is not amended: a correction after sending is a reversal, which is
  the pharmacy-side feature and the Clinical Safety Officer's call. The request carries an
  `Idempotency-Key`, hashed with the tenant and the original (as dispatch does): the same key answers
  the same addendum (`200`), another key `409 ALREADY_SUPERSEDED`.
- **History** (`GET .../history`) is `prescription_events` in order, with who and the reason code, and
  the versions either side of an addendum. **Single read** (`GET /prescriptions/{id}`). Both are audited
  `prescription.read` with the care relationship and the purpose.
- **Idempotency (R13).** The addendum is the only new write that creates a row, and it takes a key. An
  edit is idempotent by content and a cancel by state (a replay is `409`); neither stores a key, which
  is recorded as a gap against R13 alongside staging, which never did.
- The signing and dispatch gate (`gate.decide`) is unchanged.

## Consequences

- Schema: `prescriptions.cancel_reason_code`, `supersedes_id` (tenant-bound self reference) and
  `addendum_key`, their checks, a partial unique index, and a new `prescriptions_lock_signed()` that
  freezes the addendum link for the row's life and lets the reason change only on the transition into
  `CANCELLED` (migration `b8d4e2f61a90`).
- Audit: `prescription.modify` (`patient_id`, `changed_fields`, `supersedes_id`) and
  `prescription.reject` (`patient_id`, `from_state`; the code in `reason`) gain payload rows; the payload
  vocabulary gains `supersedes_id`.
- Closing any of the three interims changes a list or a rule, not the mechanism.
