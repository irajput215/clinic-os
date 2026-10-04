---
doc_id: FEAT-USR-02
title: Users and roles, user stories
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 04-database-erd, 20-product-requirements
---

# Users and roles, user stories

Each story carries a security criterion (S) and an audit criterion (A). Role names follow
`01-system-architecture.md` §2 and `22-user-stories.md` §1. Authentication mechanics (login, MFA,
step-up issuance) live in feature 02 and are not restated here.

## Practice Owner
**US-1** As a Practice Owner I want to see who currently holds privileged access, so that I can accept or
change the practice's risk position.
- Acceptance: a list of active accounts, their roles and each role's permissions, scoped to my tenant.
- S: `users:manage`; tenant resolved from the session; results restricted by RLS.
- A: `audit:read`-style read is logged; the review completion writes `ACCESS_REVIEW_COMPLETED`.

**US-2** As a Practice Owner I want to review access on a quarterly cadence, so that stale privileged
access is found before an auditor finds it.
- Acceptance: every active account, role and integration identity carries a last-review date; unreviewed
  accounts are flagged and their owners notified.
- S: review is read-only; changing access is a separate step-up operation.
- A: `ACCESS_REVIEW_COMPLETED` with the review window, the reviewer and the flagged count.

## Clinic Administrator
**US-3** As a Clinic Administrator I want to invite a staff member and assign a role, so that access
starts from least privilege.
- Acceptance: the invited user is created inside my tenant with only that role's permission bundle; the
  invitation expires if not accepted inside the configured window.
- S: `users:manage`; I cannot assign a role whose bundle contains a permission I do not hold.
- A: `USER_CREATED` with target user, roles and the inviter; `ROLE_ASSIGNED`.

**US-4** As a Clinic Administrator I want to change a user's role, so that access follows the person's
current duties.
- Acceptance: the previous and new permission sets are recorded; the change takes effect on the next
  request, not on the next token expiry alone.
- S: `users:manage` plus step-up; no self-grant beyond my own permission set.
- A: `ROLE_ASSIGNED` and `ROLE_REVOKED` with before and after bundles.

**US-5** As a Clinic Administrator I want to grant or revoke a single permission, so that access is
granular rather than all-or-nothing.
- Acceptance: adding or removing one permission requires step-up; removing the last Administrator
  permission is refused.
- S: step-up enforced server-side; the actor may not grant a permission the actor does not hold.
- A: `PERMISSION_GRANTED` / `PERMISSION_REVOKED` with added and removed codes.

**US-6** As a Clinic Administrator I want to deactivate an account on the day, so that a departing staff
member cannot reach patient data.
- Acceptance: all sessions and refresh tokens are revoked within 60 seconds; outstanding access tokens
  expire within 10 minutes; the account is retained as `OFFBOARDED`, never hard-deleted.
- S: `users:manage` plus step-up; revocation is server-side.
- A: `USER_DEACTIVATED` with the revocation timestamp and the acting administrator.

## Doctor
**US-7** As a Doctor I want to see the permissions my account currently holds, so that I can tell why an
action is refused.
- Acceptance: `GET /api/v1/auth/capabilities` returns my effective permission set; the response is
  advisory only and never substitutes for a server-side check.
- S: the capability list is computed from my roles, never from the request.
- A: none beyond session access logging.

**US-8** As a Doctor I want a refusal to name the missing permission, so that I can ask for the right
access rather than guess.
- Acceptance: a `403` body carries a machine-readable code (`PERMISSION_NOT_HELD`), never a role name or
  another user's data.
- S: `403` never clears the session; the message discloses no other tenant's data.
- A: the denial is audited with the attempted action and the reason code.

## Nurse
**US-9** As a Nurse I want access scoped to patients I have a care relationship with, so that I can do my
job without seeing the whole register.
- Acceptance: a patient outside my care relationship returns `403 AUTHZ_CARE_RELATIONSHIP_DENIED`.
- S: the relationship is resolved in the policy layer under the same RLS scope, never inferred from "works
  at this clinic".
- A: a denial event with the permission, the resource and the reason code.

## Pharmacy
**US-10** As a dispensing pharmacy user I want only the permissions needed to receive and confirm a
dispatch, so that my access is minimised.
- Acceptance: my bundle is `pharmacy:dispatch` and `tga_approval:read` only; clinical record reads are
  refused.
- S: scoped to prescriptions routed to my pharmacy in the same tenant.
- A: every read carries the `PHARMACY` role and the dispatch context.

## Compliance / Auditor
**US-11** As an auditor I want read-only evidence of who held which access and when, so that I can verify
the control operated.
- Acceptance: user, role and permission change events are retrievable; write endpoints return `403`.
- S: read-only; `audit:read` tenant-scoped; no grant capability.
- A: every auditor read is logged; the export path requires a reason and step-up.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Whether the Pharmacy story is in MVP scope | Head of Product | OPEN |
| Whether `permission:grant`/`permission:revoke` are distinct permissions or part of `users:manage` | Security Lead | OPEN |
| Confirm the access-review cadence (quarterly in `22-user-stories.md` US-30) and the unreviewed-account owner | Compliance Lead | OPEN |
| Confirm the treating-relationship rule per role, which governs US-9 | Clinical Safety Officer | OPEN |
