# Auth and app shell: test plan

| Level | Case | Where |
|---|---|---|
| e2e | Anonymous visitor goes to `/scripts`, is sent to sign-in, then back to `/scripts` | `tests/auth.spec.ts` |
| e2e | Wrong password: generic message, stays on `/login` | `tests/auth.spec.ts` |
| e2e | `redirect=//evil.example` is ignored | `tests/auth.spec.ts` |
| e2e | Sign-out, then a staff URL goes back to `/login` | `tests/auth.spec.ts` |
| e2e | Signup from the sign-in page creates a clinic and lands its owner signed in on Today | `tests/account.spec.ts` |
| e2e | Signup validates every field before calling the API; a taken email is refused at the field; a `5xx` shows its reference | `tests/account.spec.ts` |
| e2e | Recovery email (Mailpit) link sets a new password that then signs in | `tests/account.spec.ts` |
| e2e | Unknown email gets the same confirmation; missing or invalid token offers a new link | `tests/account.spec.ts` |
| manual | Drawer at under 1024 px; no horizontal scroll at 390 px | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
