# ADR-F003: How the UI handles the approval validity boundary

- **Status:** Accepted. Follows D-006's interim position and must be revisited when D-006 is ruled
- **Date:** 2026-10-06

## Context

[D-006](../../docs/reference/decisions/D-006-approval-grain-and-validity-boundary.md) is open on
whether the end date printed on a TGA approval letter is inside the validity window. Until the
Clinical Safety Officer rules, the backend uses the narrow, fail-safe reading: half-open
`[valid_from, valid_to)` evaluated in Australia/Sydney. The printed end date is **not** covered.

A UI can quietly undo that. The first version of this app asked for the "last valid day" and sent
`valid_to = last day + 1`. That makes the printed end date covered, so the window fails **wide**.
That was caught during the documentation pass and removed before merge.

## Decision

- The approval form asks for **"Valid to (as on the letter)"** and sends that date to the API
  unchanged. The form never adjusts a date.
- The form says, next to the field, that the end date itself is not covered until the ruling.
- Registers show the dates **as printed**. Wherever the question is "can I prescribe?" (the gate
  pill, the review dialog, expiry countdowns), the UI shows **"covered through"** `valid_to − 1`
  (`lastCoveredDay()` in `lib/format.ts`).
- An end-to-end test pins that the date typed is the date stored
  (`tests/safety-gate.spec.ts`, "the letter's end date is sent unchanged").

## When D-006 is ruled

- **Ruled half-open:** only the form's explanatory note changes.
- **Ruled inclusive:** the backend changes the window, which is a Gate 4 re-run. Then
  `lastCoveredDay` becomes the identity, the note is removed, and the e2e test's name changes with
  its assertion. The UI still never adjusts the typed date.
