# Capabilities: API or preview

Each feature reads either from the backend (`api`) or from the in-browser preview store (`preview`).
The switch lives in [`src/data/capabilities.ts`](../frontend-features/src/data/capabilities.ts).
The reasoning is in [ADR-F004](adr/ADR-F004-preview-store.md).

| Capability | Today | Backend status | To switch to `api` |
|---|---|---|---|
| `patients` | api | merged | already |
| `audit` | api | merged (#42) | already |
| `clinicalRecords` | preview | `feat/clinical-records`, in progress | Merge it, regenerate the client, set `clinicalRecords: "api"`. The adapter in `data/records.ts` already targets its routes |
| `tgaApprovals` | preview | `feat/tga-approvals-engine`, in progress | As above, plus the tenant-wide register needs `GET /tga-approvals` ([sdlc/05 api](sdlc/05-approvals/api.md)). Until then the register is preview-only and the patient tab can be `api` |
| `appointments` | preview | none | Build to [sdlc/04 api](sdlc/04-calendar-and-booking/api.md) |
| `publicBooking` | preview | none | Build to [sdlc/04 api](sdlc/04-calendar-and-booking/api.md) |
| `prescriptions` | preview | none | Build to [sdlc/07 api](sdlc/07-script-queue/api.md) |
| `dashboard` | preview | none | Build to [sdlc/08 api](sdlc/08-today/api.md) |

You can also switch at build time without editing code: `VITE_API_FEATURES=clinicalRecords,tgaApprovals`.

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

[`src/data/types.ts`](../frontend-features/src/data/types.ts) marks every type as one of two kinds:

- **MIRROR** types are copied field for field from a backend branch's `schemas.py`. When the
  branch merges, the generated type replaces the mirror, and the compiler flags any drift.
- **PROPOSED** types have no backend yet. Each one is this app's contract, written up in the
  feature's `api.md` for the backend owner to accept or amend.
