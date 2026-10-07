---
doc_id: FEAT-USR-05
title: Users and roles, data and audit
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 04-database-erd, 20-product-requirements
---

# Users and roles, data and audit

## Field classification
Levels are from `12-data-classification.md` §1, which defines **seven**: `PUBLIC`, `INTERNAL`,
`CONFIDENTIAL`, `SENSITIVE`, `HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`. `Log` is the application
log; `Analytics` is any aggregate or reporting pipeline. `pseud` means a pseudonymous actor identifier
only.

| Field | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- |
| `users.id`, `users.tenant_id` | INTERNAL | yes | yes | identifiers only |
| `users.subject_id` | CONFIDENTIAL | never | never | identity-provider `sub` (`04 §3.2`) |
| `users.email` | SENSITIVE | never | never | workforce personal information (`12 §3`) |
| `users.display_name` | SENSITIVE | pseud | never | workforce personal information (`12 §3`) |
| `users.status` | INTERNAL | yes | aggregate only | `INVITED`/`ACTIVE`/`SUSPENDED`/`OFFBOARDED` |
| `users.mfa_enrolled_at`, `last_login_at` | SENSITIVE | yes | never | security posture, no content |
| Credential columns | **SECRET** | never | never | shape depends on D-003; held by the identity provider under Option A |
| `roles.code`, `roles.name` | SENSITIVE | yes | aggregate only | `role` is SENSITIVE in `12 §3`; `name` not separately classified (OPEN-5) |
| `roles.is_system` | INTERNAL | yes | aggregate only | configuration flag |
| `permissions.code`, `permissions.description` | CONFIDENTIAL | yes | no | `04 §3.3` classifies each permission code CONFIDENTIAL |
| `role_permissions.*` | CONFIDENTIAL | aggregate only | aggregate only | grant metadata, no personal information |
| `user_roles.granted_by`, `granted_at` | SENSITIVE | pseud | never | actor and timeline evidence |
| `user_roles.last_reviewed_at` | SENSITIVE | yes | never | access-review evidence (`22` US-30) |
| Audit `reason` (free text) | SENSITIVE | never | never | may contain clinical detail; captured but never logged (`12 §3`) |

`HEALTH_INFORMATION` and above never reaches an analytics pipeline as row-level data; `SENSITIVE` appears
only as the aggregate the source permits. `SECRET` never reaches a log line, an analytics pipeline, an
error trace or a repository.

## Residency
All fields are stored in the Australian production region (`ap-southeast-2`). No third party receives
identity data in the MVP. If the identity provider is external (D-003 Option A), its hosting region and
sub-processor list must be entered in the vendor register before it receives workforce identity data.
Source: `13-data-residency.md`; `16-vendor-register.md`.

## Audit events emitted
Append-only, written in the same transaction as the change, with denied and failed attempts audited at
the same fidelity as successes. Source: `07-audit-architecture.md` §1, §5; `20 §2`; `22` US-05, US-07,
US-30.

| Event | Trigger | Key fields beyond the envelope (no secrets, no clinical content) |
| --- | --- | --- |
| `USER_CREATED` | successful invite or create | target user id, roles, inviter, invitation expiry |
| `USER_DEACTIVATED` | successful deactivation / offboarding | target user id, revocation timestamp, sessions revoked count |
| `ROLE_ASSIGNED` | role added to a user | target user id, role code, before and after bundle |
| `ROLE_REVOKED` | role removed from a user | target user id, role code, before and after bundle |
| `PERMISSION_GRANTED` | permission added to a role or user | target id, permission code, actor, step-up flag |
| `PERMISSION_REVOKED` | permission removed | target id, permission code, actor, step-up flag |
| `ACCESS_REVIEW_COMPLETED` | periodic access review closes | review window, reviewer, accounts listed, accounts flagged |

**As built.** The staff invitation emits doc 07 §1's `user.create` (the closed catalogue's name for
`USER_CREATED`, as `user.permission_change` stands for `ROLE_ASSIGNED`/`ROLE_REVOKED`; OPEN-1). Its
payload allow-list is `target_user_id`, `added` (the role codes) and `step_up`; the inviter is the
envelope's `actor_id`, and the invitation expiry is the event's timestamp plus
`STAFF_INVITATION_EXPIRE_HOURS`, so no key was invented for it. Each granted role also emits
`user.permission_change` `GRANT`. Refusals write `user.create` `DENIED` with `PERMISSION_NOT_HELD`,
`GRANT_EXCEEDS_ACTOR`, `EMAIL_UNAVAILABLE` or `CLIENT_TENANT_ID_IGNORED` (the last alongside the
successful create). Accepting the invitation writes nothing: the catalogue has no credential event.

A refused create, grant or assignment writes a denial event with `result = DENIED` and a reason code
(`PERMISSION_NOT_HELD`, `GRANT_EXCEEDS_ACTOR`, `CROSS_TENANT`, `STEP_UP_REQUIRED`). The audit store is
append-only by grant: the app role holds `SELECT, INSERT` on `audit_log` and never `UPDATE`, `DELETE` or
`TRUNCATE`.

## Standard envelope
Every event carries the envelope from `07-audit-architecture.md` §2:
`event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result,
reason, source_ip, request_id, correlation_id, prev_hash, hash`.

- `actor_role` is the role that held the permission **at decision time**, not the role held later.
- `resource_type` is `USER` (or `TENANT`) for this feature.
- `tenant_id` comes from the request context, never from the request body.
- The envelope carries no permission payload beyond codes and no credential material.

## Retention and deletion
A user is never hard-deleted: clinical attribution must survive (`04 §3.2`). Offboarding sets
`status = 'OFFBOARDED'`, and session revocation evidence is retained. Audit events about user, role and
permission changes are retained for the period the retention schedule names. The exact period per
jurisdiction is **REQUIRES LEGAL/REGULATORY VALIDATION**. Deletion is not a feature; expiry operates on
whole audit partitions, never individual rows (`07 §9`; `14-retention-and-deletion.md`).

## Open items
| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | **Event-name conflict.** `07-audit-architecture.md` §1 names the actions `user.create`, `user.deactivate` and `user.permission_change` (lowercase dot form), while `20 §2` and `22` US-05/US-07 use uppercase names (`USER_CREATED`, `USER_DEACTIVATED`, `USER_INVITED`, `PERMISSION_GRANTED`, `PERMISSION_REVOKED`). The catalogue above uses the uppercase names this feature was specified with; one naming authority must be chosen before the writer is built | CTO + Compliance Lead | OPEN |
| OPEN-2 | **Classification conflict.** `04-database-erd.md` §3.2 classes `email`, `display_name` and `subject_id` CONFIDENTIAL; `12-data-classification.md` §3 classes `email` and `display_name` SENSITIVE. This document applies the stricter level | Privacy Officer | OPEN |
| OPEN-3 | Whether `USER_INVITED` and `ROLE_REVOKED` are distinct events or `USER_CREATED`/`ROLE_ASSIGNED` cover them (`22` US-05 names `USER_INVITED`) | Compliance Lead | OPEN |
| OPEN-4 | Retention period for user, role and permission-change audit events, per jurisdiction | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 | Per-field classification of `roles.name`, `roles.is_system` and `permissions.description` is not given in `12 §3`; interim SENSITIVE/CONFIDENTIAL by analogy to the `role` field and the permission code | Privacy Officer | OPEN |
| OPEN-6 | If D-003 Option A is chosen, the identity provider's residency and sub-processor position | CTO + Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
