---
doc_id: FEAT-USR-03
title: Users and roles, design
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 04-database-erd, 20-product-requirements
---

# Users and roles, design

## Data model
PostgreSQL 16 via SQLModel / psycopg3. Every `id` is `uuid DEFAULT gen_random_uuid()`. Sources:
`04-database-erd.md` §3.1–§3.3, §8; `21-technical-design.md`.

### `users`, `roles`, `permissions`, `role_permissions`, `user_roles`
| Table | Column(s) | Type | Constraints and notes |
| --- | --- | --- | --- |
| `users` | `id` | uuid | PK |
| | `tenant_id` | uuid | NOT NULL; FK `tenants(id)` ON DELETE RESTRICT; RLS key |
| | `subject_id` | text | NOT NULL; identity-provider subject identifier |
| | `email` | citext | NOT NULL; unique `(tenant_id, email)` |
| | `display_name` | text | NULL |
| | `status` | text | NOT NULL; `CHECK IN ('INVITED','ACTIVE','SUSPENDED','OFFBOARDED')` |
| | `mfa_enrolled_at` | timestamptz | NULL; null means enrolment required before a clinical action |
| | `last_login_at` | timestamptz | NULL |
| | `created_at`, `updated_at` | timestamptz | NOT NULL |
| `roles` | `id` | uuid | PK |
| | `tenant_id` | uuid | FK `tenants(id)` ON DELETE RESTRICT |
| | `code` | text | `CHECK IN` the seven system codes; unique `(tenant_id, code)` |
| | `name` | text | tenant may edit the display name only |
| | `is_system` | boolean | `DEFAULT false`; system roles are not deletable |
| | `created_at`, `updated_at` | timestamptz | NOT NULL |
| `permissions` | `id` | uuid | PK |
| | `code` | text | unique; global reference data |
| | `description` | text | NOT NULL |
| `role_permissions` | `role_id`, `permission_id` | uuid | PK `(role_id, permission_id)`; both FK |
| | `tenant_id` | uuid | RLS key; index `(tenant_id)` |
| `user_roles` | `user_id`, `role_id` | uuid | PK `(user_id, role_id)`; both FK |
| | `tenant_id` | uuid | RLS key; unique `(tenant_id, user_id, role_id)` |
| | `granted_by` | uuid | NOT NULL; FK `users(id)` |
| | `granted_at` | timestamptz | NOT NULL |
| | `last_reviewed_at` | timestamptz | NULL; access review (US-2, US-30) |

Indexes: unique `(tenant_id, email)`, unique `(tenant_id, subject_id)`, `(tenant_id, status)` on `users`;
`(tenant_id)` on `roles`; `(tenant_id, user_id)` on `user_roles`. Composite foreign keys include
`tenant_id` so a grant cannot cross a tenant boundary. `permissions` is global read-only reference data
seeded from a versioned migration; a tenant may rename a role but never invent a permission. A custom
tenant role code is **OPEN** (OPEN-2). No hard delete: `status = 'OFFBOARDED'` retains clinical
attribution. **The `users` credential columns depend on the open D-003 decision and are not fixed here**
(`../../reference/decisions/D-003-identity-model.md`).

## The central policy layer
One module owns every decision: `backend/app/modules/rbac/policy.py`, exposing
`can(actor, permission, resource)`. It **recomputes** the decision from the verified identity, the tenant
and the resource on every request. A route handler declares its permission and calls the facade; it never
evaluates a role name. Source: `06-authentication-rbac.md` §10–§11; `02-security-architecture.md` §1.

Decision order inside `can()`:
1. Missing actor or tenant → deny (`401 NO_IDENTITY`).
2. `resource.tenant_id != actor.tenant_id` → deny `404 CROSS_TENANT` (existence is not disclosed).
3. Permission not in the actor's resolved set → deny `403 PERMISSION_NOT_HELD`.
4. Resource rules (care relationship; prescriber of record; pharmacy routing) → deny `403` with a code.
5. Otherwise allow.

The actor is built from the verified session, and its permission set is resolved from `user_roles` →
`role_permissions` under the request's tenant context. Nothing in the set comes from the request.

## RLS
`ENABLE` and `FORCE ROW LEVEL SECURITY` on `users`, `roles`, `role_permissions`, `user_roles`.
`permissions` is global and carries no RLS. Policy shape (`04-database-erd.md` §8):

```sql
CREATE POLICY pol_users_tenant_isolation ON users
  AS RESTRICTIVE FOR ALL TO clinos_app
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

The `NULLIF` guard fails closed: an unset tenant matches no row rather than raising a cast error.
`FORCE` closes the table-owner bypass. Context is set with `SET LOCAL app.tenant_id` inside the
transaction, never with plain `SET`.

## Database privileges
The application connects as non-owner role `clinos_app`. Source: `04-database-erd.md` §8–§9.

```sql
GRANT SELECT, INSERT, UPDATE ON users, roles TO clinos_app;
REVOKE DELETE, TRUNCATE ON users, roles FROM clinos_app;    -- soft delete only; system roles fixed
GRANT SELECT ON permissions TO clinos_app;                  -- global read-only reference data
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON permissions FROM clinos_app;
GRANT SELECT, INSERT, DELETE ON role_permissions, user_roles TO clinos_app;  -- grant/revoke is real
REVOKE TRUNCATE ON role_permissions, user_roles FROM clinos_app;             -- history in audit_log
GRANT SELECT, INSERT ON audit_log TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app;
```

`clinos_app` does not own any table and has no `BYPASSRLS`.

## The grantability rule (R3)
Before writing a `role_permissions` or `user_roles` row, the policy layer asserts that **every permission
in the incoming bundle is held by the actor**. A request that would grant a permission the actor lacks is
refused `403 GRANT_EXCEEDS_ACTOR` and audited. `users:manage` never implies `tenant:configure`, and an
actor cannot promote themselves or another user above their own permission set. Source:
`06-authentication-rbac.md` §9 note on `users:manage`.

## Endpoints
All client-facing paths carry the `/api/v1` prefix (D-005).

| Method and path | Permission | Step-up | Notes |
| --- | --- | --- | --- |
| `GET /api/v1/users` | `users:manage` | no | tenant-scoped list, cursor-paginated |
| `POST /api/v1/users` | `users:manage` | yes, 5 min | invite; `409` duplicate email; `422` role not grantable |
| `GET /api/v1/users/{id}` | `users:manage` | no | `404` on cross-tenant |
| `POST /api/v1/users/{id}/deactivate` | `users:manage` | yes | revokes sessions; `USER_DEACTIVATED` |
| `POST /api/v1/users/{id}/roles` | `users:manage` | yes, 5 min | `ROLE_ASSIGNED`; `200` when the account already holds the role, `201` when the grant is created |
| `DELETE /api/v1/users/{id}/roles/{role_id}` | `users:manage` | yes, 5 min | `ROLE_REVOKED`; `409 LAST_ADMINISTRATOR` when it would remove the last role granting `users:manage` (R8) |
| `GET /api/v1/users/{id}/roles` | `users:manage` | no | the roles one account holds; `404` on cross-tenant |
| `GET /api/v1/users/{id}/permissions` | `users:manage` | no | effective set, computed server-side |
| `GET /api/v1/roles` | `users:manage` | no | roles with their permission bundles |
| `GET /api/v1/permissions` | `users:manage` | no | the global catalogue (R7); read-only reference data with no tenant key |
| `PUT /api/v1/roles/{id}/permissions` | `users:manage` | yes, 5 min | passkey/hardware key only; `PERMISSION_GRANTED`/`PERMISSION_REVOKED` |
| `GET /api/v1/users/me/permissions` | valid session | no | the caller's own effective set, `{permissions: string[]}`; advisory UI data only; never a control |

**Decision (owner, 2026-10-07):** the self-permissions capability is served as
`GET /api/v1/users/me/permissions`, the path the frontend contract names
([`docs2/sdlc/01-auth-and-shell/api.md`](../../../docs2/sdlc/01-auth-and-shell/api.md)), not as the
`GET /api/v1/auth/capabilities` this table first named. It is built and tested
(`backend/tests/users/test_own_permissions.py`); every other property of the row is unchanged.

There is no `DELETE /users/{id}` endpoint. Access reviews are read-only over the above; their completion
event is emitted by the review job. Source: `06-authentication-rbac.md` §8, §12;
`20-product-requirements.md` §2.

## Deny-by-default request path
1. Authenticate the session; deny `401` if missing or expired.
2. Resolve the tenant from the session; `SET LOCAL app.tenant_id` in the transaction.
3. Call `can(actor, permission, resource)`; any error verdict denies.
4. For a mutating request, verify a fresh, resource-bound step-up where the table above requires one.
5. Validate the body against a strict Pydantic v2 model — extra fields forbidden, so a `tenant_id`,
   `role_ids` or `granted_by` in the body is rejected `422`.
6. Apply the grantability rule (R3) for any grant or role assignment.
7. Write the audit event in the same transaction as the change; execute under RLS.

## Failure behaviour
Any error resolving the tenant, the identity or the permission **denies**. Errors return the standard
envelope with a `request_id` and no internal detail. A failure to write an audit event fails the
operation. A deactivated, suspended or locked actor is refused by the policy layer even while a
still-valid access token exists.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 permission catalogue size (19 vs "20" vs the doc 20 candidates) | CTO + Security Lead | OPEN — blocks the seed migration |
| OPEN-2 whether a tenant may create custom roles, or only rename the seven system roles | CTO | OPEN |
| OPEN-3 the `users` credential column shape (D-003) | CTO + Security Lead | OPEN |
| OPEN-4 whether `last_reviewed_at` lives on `user_roles` or a separate review table | Engineering Lead | OPEN |
