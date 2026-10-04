---
doc_id: FEAT-USR-01
title: Users and roles, requirements
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 04-database-erd, 20-product-requirements
---

# Users and roles, requirements

## Purpose
Own the user lifecycle, the tenant-scoped role bundles and the granular permission grants, and expose one
authorisation facade that every module calls. Source: `01-system-architecture.md` §5 ("Users and Roles"
module); `20-product-requirements.md` §2.

## Roles are thin bundles over granular permissions
A role is a named bundle of permission codes and nothing else. A route handler never branches on a role
name; it asks the central policy layer for a permission. Source: `06-authentication-rbac.md` §9–§10;
`02-security-architecture.md` §1 control 2.

- The permission list is **global, fixed reference data**, seeded from a versioned migration. A tenant may
  rename a role's display name; it may not invent a permission. Source: `04-database-erd.md` §3.3.
- The seven system role codes are `PRACTICE_OWNER`, `AUTHORISED_PRESCRIBER`, `DOCTOR`, `NURSE`,
  `ADMINISTRATOR`, `PHARMACY`, `COMPLIANCE_AUDITOR`. Source: `04-database-erd.md` §3.3.

## Permission catalogue (role × permission)
The catalogue is the **19 permissions** defined in `06-authentication-rbac.md` §9, which is the same list
as `04-database-erd.md` §3.3. `04-database-erd.md` §3.3 says "20 permissions" but lists 19; §9 and §10 of
doc 06 define the same 19. This document uses 19 and records the reconciliation in Open items.

**Legend.** `G` granted · `–` never granted (`403`) · `cr` care relationship required · `su` step-up
required · `pr` prescriber of record only · `draft` draft records only · `own` own drafts and addenda ·
`ro` read-only · `pl` mandatory purpose code, logged · `ts` tenant-scoped · `agg` aggregate only ·
`dc` pharmacy dispatch context only.

| Permission | Practice Owner | Auth. Prescriber | Doctor | Nurse | Administrator | Pharmacy | Compliance / Auditor |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `patient:read` | G | G | G `cr` | G `cr` | G | G `dc` | G `ro` `pl` |
| `patient:create` | G | G | G | G | G | – | – |
| `patient:update` | G | G | G `cr` | G `cr` | G | – | – |
| `patient:export` | G `su` | G `su` | – | – | G `su` | – | G `su` `pl` |
| `clinical_record:read` | G | G | G `cr` | G `cr` | G | – | G `ro` `pl` |
| `clinical_record:write` | G | G | G `cr` | G `cr` | – | – | – |
| `prescription:create` | G | G | G | G `draft` | – | – | – |
| `prescription:modify` | G | G | G `own` | G `draft` | – | – | – |
| `prescription:sign` | G `pr` | G `pr` | G `pr` | – | – | – | – |
| `prescription:dispatch` | G | G | G | – | – | – | – |
| `tga_approval:read` | G | G | G | G | G | – | G |
| `tga_approval:create` | G | G | G | – | – | – | – |
| `tga_approval:verify` | G | G | G | – | – | – | G |
| `tga_inbox:process` | G | – | – | – | G | – | G |
| `audit:read` | G | – | – | – | G `ts` | – | G `ts` |
| `reports:export` | G | – | G `agg` | – | G | – | G |
| `users:manage` | G `su` | – | – | – | G `su` | – | – |
| `tenant:configure` | G `su` | – | – | – | – | – | – |
| `pharmacy:dispatch` | G | – | – | – | – | G | – |

`users:manage` **never** includes granting a permission the actor does not hold, and never includes
`tenant:configure`. Source: `06-authentication-rbac.md` §9.

## Candidate additions named elsewhere (not in the catalogue)
`20-product-requirements.md` §1–§12 and `22-user-stories.md` (US-14, US-28) name further codes that are
not in the 19. They are recorded here as **candidates, not granted**:

| Area | Candidate codes | Source |
| --- | --- | --- |
| Tenancy / clinics | `tenant:read`, `clinic:manage`, `clinic:read` | `20-product-requirements.md` §1 |
| Identity / admin | `user:read`, `user:manage`, `role:read`, `role:manage`, `session:revoke`, `permission:grant`, `permission:revoke`, `mfa:enrol`, `mfa:reset` | `20-product-requirements.md` §2 |
| Patients | `patient:merge` | `20-product-requirements.md` §3; `22-user-stories.md` US-14 |
| Clinical records | `clinical_record:create`, `clinical_record:amend` | `20-product-requirements.md` §4 |
| TGA | `tga_approval:update`, `tga_approval:revoke` | `20-product-requirements.md` §5 |
| TGA inbox | `tga_inbox:read`, `tga_inbox:verify`, `tga_inbox:reassign`, `tga_inbox:reject` | `20-product-requirements.md` §6 |
| Prescribing | `prescription:read`, `prescription:stage`, `prescription:cancel` | `20-product-requirements.md` §7 |
| Pharmacy | `pharmacy:read`, `pharmacy:confirm` | `20-product-requirements.md` §8 |
| Reports / exports | `report:run`, `report:schedule`, `export:aggregate`, `export:bulk` | `20-product-requirements.md` §9; `22-user-stories.md` US-28 |
| Audit | `audit:export`, `audit:configure_retention` | `20-product-requirements.md` §10 |
| Notifications | `notification:read`, `notification:configure` | `20-product-requirements.md` §11 |
| Platform admin | `admin:read`, `admin:configure`, `admin:feature_flag` | `20-product-requirements.md` §12 |

## Requirements

| ID | Requirement | Testable acceptance | Evidence |
| --- | --- | --- | --- |
| **R1** | A role resolves to a permission set at login; effective permissions are the union of the actor's roles | No route reads a role name; a user with two roles holds the union; a Doctor without `tga_approval:create` is refused `403` | F1, S2 |
| **R2** | Authorisation is recomputed server-side from the verified identity, the tenant and the resource on every request | Replaying an earlier request with a tightened permission set returns `403`; no decision is served from a previous request's cache | S1, S2 |
| **R3** | An actor may not grant a permission the actor does not hold | An Administrator holding `users:manage` but not `tenant:configure` receives `403` when granting `tenant:configure` | S6 |
| **R4** | Role assignment and permission change require step-up (passkey or hardware key, 5 minutes, single use) | Without fresh step-up the change is refused `403`; a TOTP-only step-up is refused for this operation | F4, S5 |
| **R5** | Deactivating a user revokes every session and refresh family within 60 seconds; outstanding access tokens expire within 10 minutes | The deactivated user's next request returns `401`; the residual window is bounded and stated | S7 |
| **R6** | Cross-tenant user, role and grant access returns `404`, never `403` | Tenant B requesting a tenant A user id receives `404` and an audited denial | S3, S4 |
| **R7** | `permissions` is global read-only reference data; a tenant may rename a role but may not create a permission | An insert into `permissions` through the app role is refused; a role code change is refused | S8 |
| **R8** | System roles are not deletable and the last Administrator permission cannot be removed | Deleting a system role is refused; removing the final granting role is refused `409` | F5 |
| **R9** | A role or permission change refuses refresh and requires a new login; the old token survives at most 10 minutes | After a change, refresh returns `401`; the new login yields the new permission set | S9 |
| **R10** | Invitations expire if not accepted inside the configured window | An expired invitation cannot be accepted | F2 |
| **R11** | Every tenant-scoped table is protected by RLS with `FORCE ROW LEVEL SECURITY` and the `NULLIF` guard | A missing tenant setting returns zero rows; a forged `tenant_id` write is refused by `WITH CHECK` | S10, S11 |
| **R12** | User, role and permission changes are audited append-only in the same transaction; denials are audited with equal fidelity | A refused grant writes a denial event; an `UPDATE`/`DELETE` on `audit_log` through the app role is refused | A1–A4, S12 |
| **R13** | A periodic access review lists every active account and role with its last review date and flags unreviewed accounts | The review emits `ACCESS_REVIEW_COMPLETED`; an account with no review date is flagged to its owner | F6, A5 |
| **R14** | A user is deactivated, not hard-deleted; clinical attribution survives | No `DELETE` grant on `users`; offboarding sets `status = OFFBOARDED` | S13 |

## Out of scope
- Authentication mechanics — login, MFA, sessions, step-up tokens, lockout (feature 02).
- Break-glass elevation and retrospective review (feature 15).
- Expanding the permission catalogue: candidates above are not granted until reconciled (OPEN-1).
- OIDC provider selection and the `users` credential columns (D-003).
- Notification content for access changes.

## Open items
| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | **Permission catalogue reconciliation.** `04-database-erd.md` §3.3 says "20 permissions" but lists 19; `06-authentication-rbac.md` §9–§10 defines the same 19; `20-product-requirements.md` and `22-user-stories.md` name ~37 further codes (table above). Which codes become the catalogue for the MVP is undecided | CTO + Security Lead | OPEN — blocks R1–R14 sign-off |
| OPEN-2 | The `users` credential columns depend on the open **D-003** identity decision; the shape is not fixed here | CTO + Security Lead | OPEN — see `../../reference/decisions/D-003-identity-model.md` |
| OPEN-3 | Whether a practitioner across two clinics is two user rows or one identity with two tenant memberships | Engineering Lead + Clinical Safety Officer | OPEN |
| OPEN-4 | Whether a tenant contract mandates a specific authenticator class for Compliance/Auditor | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 | The access-review cadence and the owner of an unreviewed account | Compliance Lead | OPEN |
| OPEN-6 | Whether `permission:grant` / `permission:revoke` are distinct codes or the existing `users:manage` boundary | Security Lead | OPEN |
