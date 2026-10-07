# Capabilities: API or preview

Each feature reads either from the backend (`api`) or from the in-browser preview store (`preview`).
The switch lives in [`src/data/capabilities.ts`](../frontend/src/data/capabilities.ts).
The reasoning is in [ADR-F004](adr/ADR-F004-preview-store.md).

| Capability | Today | Backend status | To switch to `api` |
|---|---|---|---|
| `patients` | api | merged | already |
| `audit` | api | merged (#42) | already |
| `clinicalRecords` | api | merged (#47) | already. Preview implementation deleted |
| `tgaApprovals` | api, register refused | merged (#46); `GET /tga-approvals` missing | Patient tab, Overview card and every write are `api`; preview implementation deleted. The practice-wide register shows a designed refusal naming `GET /api/v1/tga-approvals` until that endpoint lands ([sdlc/05 api](sdlc/05-approvals/api.md)). The preview store still seeds sample approvals, used **only** by the `prescriptions` safety-gate stand-in and the `dashboard`; they go with those previews |
| `appointments` | api | merged (appointments module) | already. Preview implementation deleted. The preview store keeps its sample practitioners and appointments **only** for the `dashboard` (Today) and `prescriptions` (prescriber picker) previews, through `data/preview/practitioners.ts`; they go with those previews |
| `publicBooking` | api | merged (appointments module) | already. Preview implementation (session-storage hand-off) deleted |
| `prescriptions` | preview | none | Build to [sdlc/07 api](sdlc/07-script-queue/api.md) |
| `dashboard` | preview | none | Build to [sdlc/08 api](sdlc/08-today/api.md) |

You can also switch at build time without editing code: `VITE_API_FEATURES=appointments,dashboard`.

## Switching a feature to `api`

1. Set it to `"api"` in `capabilities.ts`.
2. Prove the adapter against the real module, not against its `api.md`: request and response shapes,
   every keyset page (`{count, data, next_cursor}`), and each RFC 7807 `detail.code` the screen
   can meet (worded in `lib/http.ts`).
3. Delete the feature's preview implementation and anything only it used (D-B). Keep only what a
   feature still on preview needs, and say so in the table above.
4. Remove the screen's **Preview data** banner, and add an e2e test in `tests/` against the real
   backend.
5. Update this table, the feature map in [README.md](README.md) and the feature's `dod.md`.

## What "preview" means and does not mean

- Preview data is **seeded around the organisation's real patients**, so every link (script → patient
  → record) resolves to a record the API really returned.
- It lives in the tab's `sessionStorage`, is keyed to the signed-in user, re-seeds each clinic day,
  and is cleared on sign-out. Nothing is shared between users or tabs, and nothing reaches the server.
- Every preview screen shows a dashed **Preview data** banner, so sample data can't be mistaken
  for clinical data.
- The preview **enforces the same refusals the backend specifies**: the safety gate's half-open
  window and reason codes, four-eyes verification, overlap refusal for active approvals and for
  appointments, and the state machines. Screens are therefore built and tested against refusals,
  not just the happy path.
- The preview **is not a security control**. In `api` mode every one of those decisions is the
  server's.

## MIRROR and PROPOSED types

[`src/data/types.ts`](../frontend/src/data/types.ts) marks every type as one of two kinds:

- **MIRROR** types are copied field for field from a backend branch's `schemas.py`. When the
  branch merges, the generated type replaces the mirror, and the compiler flags any drift.
- **PROPOSED** types have no backend yet. Each one is this app's contract, written up in the
  feature's `api.md` for the backend owner to accept or amend.
