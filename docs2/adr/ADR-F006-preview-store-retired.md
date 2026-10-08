# ADR-F006: The preview store is retired; every screen reads the API

- **Status:** Accepted
- **Date:** 2026-10-08
- **Supersedes:** [ADR-F004](ADR-F004-preview-store.md)
- **Decided by:** the owner (handoff decision D-B, 2026-10-06: "the preview store is a temporary
  scaffold whose end state is deletion, not a permanent fallback")

## Context

[ADR-F004](ADR-F004-preview-store.md) let the app ship screens for features with no backend module:
each feature had an `api` and a `preview` implementation behind one interface, chosen per feature in
`src/data/capabilities.ts` (or with `VITE_API_FEATURES` at build time), and every preview screen showed
a dashed **Preview data** banner. The preview kept sample appointments, scripts and approvals in the
tab's `sessionStorage`, seeded around the organisation's real patients, and mirrored the server's rules
(the safety gate's window and reason codes, four-eyes, overlap refusal, the state machines).

Milestone 2 built the missing backends, one feature at a time, and each phase deleted that feature's
preview code: the TGA register (2A), patient search and paging (2B), appointments and public booking
(2C), prescriptions with the safety gate and the outbox (2D). After 2D the only reader left was the
Today page, which needed `GET /api/v1/dashboard/today`. Phase 2E built it (`backend/app/modules/dashboard/`).

## Decision

Delete the preview store and everything that existed for it:

- `frontend/src/data/preview/` (the store, the seed, the gate mirror, the sample practitioners).
- `frontend/src/data/capabilities.ts` and the `VITE_API_FEATURES` build switch: with one source per
  feature there is nothing to switch.
- The `PreviewBanner` component, and the browser-side `Refusal` error class only the preview raised.
- The preview-only types (`Product`, `Script`, `ScriptState`, the proposed `TodaySummary`).
- `docs2/capabilities.md`, which described the switch.

Every feature reads the API. A screen that needs data the API does not serve shows an error or the
role boundary, never invented data. `grep -rn -i preview frontend/src` finds nothing but the generated
client and Vite's `preview` server command.

## Consequences

- No screen shows a **Preview data** banner, and no sample record can be mistaken for clinical data.
- The browser holds no second copy of a server rule. Refusals, the gate's answer and every state come
  from the backend only (INV-3), which removes a class of drift ADR-F004 accepted as a cost.
- A new feature cannot ship its screens ahead of its backend behind a banner any more. It ships with
  its module, as every Milestone 2 phase did. That is the intended trade.
- Sign-out no longer has a preview store to clear; it clears the token and the query cache. A tab that
  was open before this change may still hold the old preview entry in its `sessionStorage` until the
  tab closes (it is tab-scoped and never sent anywhere).
- Patient pickers search the server (`POST /patients/search`) everywhere, including the TGA approval
  dialog, which previously offered only the first 25 patients.
