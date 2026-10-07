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
| e2e | Administration: a practice owner sees every role against the 21-permission catalogue; no Accounts tab | `tests/admin.spec.ts` |
| e2e | Administration: grant and revoke a role; the last administrator cannot be removed | `tests/admin.spec.ts` |
| e2e | An account without `users:manage` has no Administration entry and is refused at `/admin` | `tests/admin.spec.ts` |
| e2e | The platform superuser lists, adds, edits and deactivates accounts | `tests/admin.spec.ts` |
| e2e | Settings: update own name (sidebar agrees), change password then sign in with it, deactivate own account | `tests/settings.spec.ts` |
| e2e | Settings and Administration have no horizontal scroll at phone width | `tests/settings.spec.ts` |
| manual | Drawer at under 1024 px; no horizontal scroll at 390 px | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)). CI runs the same
suite against the backend container serving the production build ([ADR-F005](../../adr/ADR-F005-one-app-served-by-the-backend.md)).
Recovery and reset share a 5/min window per client address, and sign-in is 20/min: `account.spec.ts`
spends 4 recovery calls and never retries them, and signed-in specs reuse the setup project's one
sign-in.
