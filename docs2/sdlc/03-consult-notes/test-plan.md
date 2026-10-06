# Consult notes: test plan

| Level | Case | Where |
|---|---|---|
| manual (recorded) | Write, save, sign; Amend produces v2 with reason; the original stays | - |
| e2e | Write a note (only written sections are sent), sign it, amend it with a reason; after a reload the record shows Signed, Amended v2 and the reason, with no Preview banner | `tests/consult-notes.spec.ts` |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
