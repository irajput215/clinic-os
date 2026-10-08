# Auth and app shell: test plan

| Level | Case | Where |
|---|---|---|
| e2e | Anonymous visitor goes to `/scripts`, is sent to sign-in, then back to `/scripts` | `tests/auth.spec.ts` |
| e2e | Wrong password: generic message, stays on `/login` | `tests/auth.spec.ts` |
| e2e | `redirect=//evil.example` is ignored | `tests/auth.spec.ts` |
| e2e | Sign-out, then a staff URL goes back to `/login` | `tests/auth.spec.ts` |
| e2e | Signup from the sign-in page says "Check your email"; the emailed link (Mailpit) confirms and lands the owner signed in on Today; the used link is refused | `tests/account.spec.ts` |
| e2e | Signup validates every field before calling the API; a taken email gets the same "Check your email" page and its owner a notice email, never a link; resend sends the message again; a `5xx` shows its reference | `tests/account.spec.ts` |
| api | Signup verification, deny path first: no open registration `403`, no mail `503` with nothing written, unknown keys `422`; a taken address answered exactly like a new one (status, body, statements executed) with a notice and no link; a notice request never verifies; tampered, expired, wrong-purpose, replaced and used links one `400`; a second signup never changes the first, and the first verified wins; rate limits on all three routes. Then: verification creates the organisation, owner and grant, audits `user.create`, signs in; expired requests are purged | `backend/tests/users/test_signup.py` |
| e2e | Recovery email (Mailpit) link sets a new password that then signs in | `tests/account.spec.ts` |
| e2e | Unknown email gets the same confirmation; missing or invalid token offers a new link | `tests/account.spec.ts` |
| e2e | Administration: a practice owner sees every role against the 21-permission catalogue; no Accounts tab | `tests/admin.spec.ts` |
| e2e | Administration: grant and revoke a role; the last administrator cannot be removed | `tests/admin.spec.ts` |
| e2e | An account without `users:manage` has no Administration entry and is refused at `/admin` | `tests/admin.spec.ts` |
| e2e | The platform superuser lists, adds, edits and deactivates accounts | `tests/admin.spec.ts` |
| e2e | An owner invites a doctor from Staff (validation first; a taken address refused at the field); the emailed link (Mailpit) sets the password once, signs the person in to the owner's organisation without Administration; the replayed link is refused; Manage access opens User access on the account | `tests/staff.spec.ts` |
| e2e | An invited person shows "Invited" with the expiry until they accept; "Resend invite" emails a new link (Mailpit), the earlier link is then refused, the new one signs the person in and the row turns "Active" with no resend offered | `tests/staff.spec.ts` |
| e2e | An administrator can pick only roles whose permissions they hold (Administrator yes; Doctor, Nurse, Practice Owner disabled) | `tests/staff.spec.ts` |
| e2e | Staff, the invite dialog and `/accept-invite` fit 390 px with no sideways scroll | `tests/staff.spec.ts` |
| api | Staff list and invitation, deny path first: `401`, `403 PERMISSION_NOT_HELD` (audited), `NO_ORGANISATION`, cross-tenant invisibility and `404` for another tenant's role, a client `tenant_id` ignored and audited, `GRANT_EXCEEDS_ACTOR`, one `409` for a taken address in any tenant, `503` without mail, atomic rollback when the audit write or the email fails; invitation token single use, expiry, tampering, wrong purpose, not a session; paging; rate limit | `backend/tests/users/test_staff.py` |
| api | Invitation status and resend, deny path first: `401`; `403 PERMISSION_NOT_HELD` (audited); another organisation's or an unknown account `404` with nothing changed; `403 GRANT_EXCEEDS_ACTOR` for an invitee holding a role beyond the caller's (audited); `409 INVITATION_NOT_PENDING` for an accepted invitation, the founder and a password set through recovery (audited); `503` without mail; administrative rate limit. Then: the list shows `INVITED` with the expiry, `expired` after the window; a resend issues a new link, retires the old one, resets the expiry, audits `user.create` `INVITATION_RESENT` in the same transaction (a refused audit write or email changes nothing); accepting turns the row `ACTIVE` | `backend/tests/users/test_staff_invitations.py` |
| e2e | Settings: update own name (sidebar agrees), change password then sign in with it, deactivate own account | `tests/settings.spec.ts` |
| e2e | Settings and Administration have no horizontal scroll at phone width | `tests/settings.spec.ts` |
| e2e | The owner renames the clinic in Settings > Clinic (blank refused first); the sidebar and the public booking page show the new name; a Doctor has no Clinic tab, sees the role boundary at `?tab=clinic` and is refused `403` by the API | `tests/clinic-settings.spec.ts` |
| api | Clinic display name, deny path first: `401`, `NO_ORGANISATION`, `403 PERMISSION_NOT_HELD` for every role but the owner (audited, nothing changed), an unauditable refusal fails closed, a body/query/header `tenant_id` ignored and audited and the other tenant untouched, the public route returns only `display_name` and one `404` for unknown, malformed and suspended clinics; validation (blank, too long, control and format characters, malformed body); trimming; success read by every member; no-op writes nothing; rename and event are one transaction; the database check; signup's normalisation and word cut | `backend/tests/tenancy/test_display_name.py` |
| api | `clinos_app` may update only `display_name` and `updated_at` on `tenants` | `backend/tests/security/test_tenant_grants.py` |
| manual | Drawer at under 1024 px; no horizontal scroll at 390 px | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)). CI runs the same
suite against the backend container serving the production build ([ADR-F005](../../adr/ADR-F005-one-app-served-by-the-backend.md)).
Recovery and reset share a 5/min window per client address, and sign-in is 20/min: `account.spec.ts`
spends 4 recovery calls and never retries them, and signed-in specs reuse the setup project's one
sign-in.
