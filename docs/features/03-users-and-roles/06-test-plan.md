---
doc_id: FEAT-USR-06
title: Users and roles, test plan
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 04-database-erd, 20-product-requirements
---

# Users and roles, test plan

All tests run in CI on synthetic data against a seeded two-tenant environment with a canary tenant. A
failing authorisation or isolation test blocks merge; any cross-tenant assertion failure is a release
blocker. Every command is run from the repository root.

```bash
# Whole feature
cd backend && uv run pytest tests/rbac tests/users tests/security/test_users_rbac.py tests/isolation/test_users_isolation.py -v
```

## Functional tests (F)

| ID | Case | Expected result | Command |
| --- | --- | --- | --- |
| **F1** | A user holds one or two roles | Effective permissions are the union of the bundles; a Doctor without `tga_approval:create` is refused `403` | `cd backend && uv run pytest tests/rbac/test_role_bundles.py::test_role_bundle_resolves_to_permission_set -v` |
| **F2** | Invite a staff member with a role | `201`; user created in the caller's tenant with only that bundle (no `INVITED` status column yet: the account cannot sign in until the invitee sets a password) | `cd backend && uv run pytest tests/users/test_staff.py::test_an_invited_person_sets_a_password_once_and_lands_in_the_right_tenant -v` |
| **F3** | Accept an invitation after the window | Refused; the invitation cannot be accepted | `cd backend && uv run pytest tests/users/test_staff.py::test_a_tampered_expired_or_foreign_token_is_refused -v` |
| **F4** | Change a permission without a recent step-up | `403 STEP_UP_REQUIRED`; with step-up the change applies and both sets are recorded | `cd backend && uv run pytest tests/users/test_permissions.py::test_permission_change_requires_step_up -v` |
| **F5** | Remove the last Administrator grant | `409`; the change is refused | `cd backend && uv run pytest tests/users/test_lifecycle.py::test_removing_last_administrator_refused -v` |
| **F6** | Delete a system role | Refused; system roles are not deletable | `cd backend && uv run pytest tests/rbac/test_roles.py::test_system_role_not_deletable -v` |
| **F7** | Deactivate an active user | `status = OFFBOARDED`; no row is hard-deleted | `cd backend && uv run pytest tests/users/test_lifecycle.py::test_deactivation_sets_offboarded_status -v` |
| **F8** | Close an access-review window | Accounts without a current review date are flagged and their owners notified | `cd backend && uv run pytest tests/users/test_access_review.py::test_access_review_flags_unreviewed_accounts -v` |

## Security tests (S)

| ID | Case | Expected result | Command |
| --- | --- | --- | --- |
| **S1** | Authorisation is not cached from a previous request: request, tighten the actor's permission set, replay | The replayed request returns `403`, proving the decision is recomputed server-side | `cd backend && uv run pytest tests/security/test_authz_recomputes_server_side.py::test_authz_recomputes_server_side -v` |
| **S2** | **Role × endpoint matrix.** Every protected route is called by every role | A role without the route's permission receives `403` on every protected route; an authorised role succeeds; each denial is audited | `cd backend && uv run pytest tests/security/test_users_rbac.py::test_role_endpoint_matrix_403_without_permission -v` |
| **S3** | Tenant B requests a tenant A user id | `404`, never `403`; denial audited | `cd backend && uv run pytest tests/isolation/test_users_isolation.py::test_cross_tenant_user_returns_404 -v` |
| **S4** | Tenant B requests a tenant A role or grant | `404`; zero foreign rows returned | `cd backend && uv run pytest tests/isolation/test_users_isolation.py::test_cross_tenant_role_and_grant_returns_404 -v` |
| **S5** | **Vertical escalation.** An Administrator assigns a role containing `tenant:configure` or `prescription:sign` | `403 GRANT_EXCEEDS_ACTOR`; no grant row written | `cd backend && uv run pytest tests/security/test_users_rbac.py::test_vertical_escalation_by_role_assignment_denied -v` |
| **S6** | **Actor cannot grant what they lack.** An actor holding `users:manage` but not `tenant:configure` grants `tenant:configure` | `403`; refusal audited with `result = DENIED` | `cd backend && uv run pytest tests/security/test_users_rbac.py::test_actor_cannot_grant_permission_not_held -v` |
| **S7** | **Self-grant.** An actor adds a missing permission to their own role or account | `403`; no widening occurs | `cd backend && uv run pytest tests/security/test_users_rbac.py::test_self_grant_permission_refused -v` |
| **S8** | **Deactivation takes effect immediately.** A deactivated user replays a still-valid access token | Refused within 60 seconds; every session and refresh family revoked | `cd backend && uv run pytest tests/users/test_lifecycle.py::test_deactivation_revokes_sessions_immediately -v` |
| **S9** | Role change then refresh | Refresh refused; a new login yields the new permission set | `cd backend && uv run pytest tests/users/test_lifecycle.py::test_role_change_invalidates_refresh -v` |
| **S10** | Missing tenant setting on the connection | Zero rows returned (fail-closed, `NULLIF`) | `cd backend && uv run pytest tests/isolation/test_users_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` |
| **S11** | Forged `tenant_id` in a write body | `422` (unknown field) or `WITH CHECK` refusal; no row written | `cd backend && uv run pytest tests/isolation/test_users_isolation.py::test_forged_tenant_id_write_refused -v` |
| **S12** | App role attempts `UPDATE`/`DELETE` on `audit_log` | `42501 insufficient_privilege`; `role_table_grants` shows `{SELECT, INSERT}` only | `cd backend && uv run pytest tests/security/test_users_grants.py::test_audit_append_only_grants -v` |
| **S13** | Grant inspection: `users` has no `DELETE`; `permissions` is `SELECT` only | Exactly the grants in `03-design.md`; no `TRUNCATE` | `cd backend && uv run pytest tests/security/test_users_grants.py::test_users_and_permissions_grants -v` |
| **S14** | Body carries `tenant_id`, `granted_by` or an unknown role | `422`; mass assignment blocked | `cd backend && uv run pytest tests/security/test_users_validation.py::test_body_mass_assignment_rejected -v` |
| **S15** | Administrative endpoint flood | `429 Too Many Requests` after 20 requests/minute per session | `cd backend && uv run pytest tests/security/test_users_rate_limits.py::test_admin_endpoint_rate_limit -v` |

## Audit tests (A)

| ID | Case | Expected | Command |
| --- | --- | --- | --- |
| **A1** | Each successful user, role and permission change | One matching event with the full envelope, written in the same transaction | `cd backend && uv run pytest tests/users/test_audit.py::test_change_events_carry_full_envelope -v` |
| **A2** | Each refusal (create, grant, assignment, cross-tenant) | An event with `result = DENIED` and a reason code, at success fidelity | `cd backend && uv run pytest tests/users/test_audit.py::test_denied_attempts_are_audited -v` |
| **A3** | Audit write fails | The operation does not complete (fail closed) and an alert fires | `cd backend && uv run pytest tests/users/test_audit.py::test_audit_failure_fails_closed -v` |
| **A4** | Role change | `actor_role` reflects the role held at decision time, not the role held after | `cd backend && uv run pytest tests/users/test_audit.py::test_actor_role_at_decision_time -v` |
| **A5** | Access review closes | `ACCESS_REVIEW_COMPLETED` with the window, reviewer and flagged count | `cd backend && uv run pytest tests/users/test_access_review.py::test_access_review_completed_event -v` |

## Traceability
F1–F8 cover R1, R4, R7, R8, R10, R13 and R14 in [01-requirements.md](01-requirements.md), with S13
reinforcing R7. S1–S12 and S14–S15 cover R2, R3, R5, R6, R9, R11 and R12, plus the security criteria in
[02-user-stories.md](02-user-stories.md) and the controls T-03.1–T-03.11 in
[04-threat-model.md](04-threat-model.md). A1–A5 cover R12 and the event catalogue in
[05-data-and-audit.md](05-data-and-audit.md). The `test_authz_recomputes_server_side` command maps to the
source artefact named in [`../../reference/gates.md`](../../reference/gates.md) §"Artefact naming".
