---
doc_id: FEAT-TEN-01
title: Tenancy and clinics, user stories
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 04-database-erd, 06-authentication-rbac
---

# Tenancy and clinics: user stories

Each story carries a security criterion (**S**) and an audit criterion (**A**). Roles are from
`22-user-stories.md` §1 and `20-product-requirements.md` §1.

## Practice Owner
**US-1** As a Practice Owner I want to see my organisation's tenant identity and status, so that I know
which entity my staff and data belong to.
- Acceptance: `GET /api/v1/tenants/current` returns the resolved tenant only; `status` and `data_region`
  shown; `retention_profile` is never returned to the application surface.
- **S**: tenant is taken from the session claim, never from the request; missing context is a denial.
- **A**: `tenant.viewed` with actor, tenant, request ID.

**US-2** As a Practice Owner I want to change a security setting with a fresh factor, so that the
clinic's risk position matches its obligations.
- Acceptance: without a recent step-up the change is refused `403`; after step-up the change is applied
  and versioned with actor and timestamp.
- **S**: step-up is recomputed server-side and bound to the operation; `tenant:configure` only.
- **A**: `tenant.config_changed` + `auth.step_up`; both carry the decision-time role.

## Clinic Administrator
**US-3** As a Clinic Administrator I want to manage the clinics belonging to my organisation, so that a
multi-site group shares one tenant without sharing data across organisations.
- Acceptance: create or rename is scoped to resolved tenant A; no clinic belonging to tenant B is
  visible in list, search or direct read; a rename collision returns `422`, not `500`.
- **S**: `clinic:manage`; clinic identifiers are not guessable substitutes for authorisation; RLS is the
  backstop and `404` is returned across a tenant boundary.
- **A**: `clinic.created`, `clinic.updated` with actor, tenant and clinic ID.

**US-4** As a Clinic Administrator I want to list the clinics I administer, so that I can keep site
details current.
- Acceptance: cursor-paginated list, bounded `limit`; only tenant A's clinics.
- **S**: `clinic:read`; results restricted by RLS as well as by the application predicate.
- **A**: read-only route — no per-row audit; administrative mutations are the audited actions.

## Doctor
**US-5** As a Doctor I want my session to resolve to exactly one clinic context, so that I cannot
accidentally read or write another site's or another organisation's records.
- Acceptance: a request carrying another tenant's `tenant_id`, or a clinic ID from another tenant,
  returns the caller's own data or `404`; it is never served across the boundary.
- **S**: resolved, never supplied; care-relationship and permission checks remain server-side.
- **A**: `TENANT_CROSS_ACCESS_ATTEMPT` with `result = DENIED` when a supplied value is dropped.

**US-6** As a Doctor I want a suspended organisation to stop working immediately, so that an
off-boarded or non-paying tenant cannot keep reading health information.
- Acceptance: a `SUSPENDED` tenant is refused at resolution on every request, not only at login.
- **S**: tenant status checked server-side before any query; no cached authorisation across requests.
- **A**: refusal audited; alert class for cross-tenant denials is **OPEN** (owner Security Lead).

## Compliance / Auditor
**US-7** As an auditor I want read-only visibility of tenant and clinic configuration, so that I can
evidence who changed what.
- Acceptance: can list clinics and view tenant metadata; write endpoints return `403` and are audited.
- **S**: `tenant:read` / `clinic:read`; read path is tenant-scoped by RLS, never platform-wide.
- **A**: `tenant.config_changed` and `clinic.updated` history is retrievable and immutable.

**US-8** As an auditor I want every cross-tenant attempt recorded, so that a probing attempt is visible
even when it returns no data.
- Acceptance: each attempt writes one event with the full envelope; denied attempts are recorded with
  the same fidelity as successes.
- **S**: the denial event is written in the same transaction as the refusal; a failed audit write fails
  the action closed.
- **A**: `TENANT_CROSS_ACCESS_ATTEMPT` with `result = DENIED`, `reason`, `source_ip`, `request_id`.

## Negative story (security)
**US-9** As a Security Lead I want isolation proven by absence, so that tenant isolation is evidenced
rather than asserted.
- Acceptance: clinic A cannot reach clinic B through list, filter, sort, search, direct id, nested
  resource, export or cache; a pool-reuse test proves context does not leak.
- **S**: RLS with `FORCE`; transaction-scoped tenant setting; no bypass role; `404` not `403`.
- **A**: denied-access events for each attempt.

## Open items
| Item | Owner | Status |
|---|---|---|
| Role display names above follow `22-user-stories.md` §1; align to the role codes in `04-database-erd.md` §3.3 before build | CTO | OPEN |
| Alert severity for a cross-tenant denial | Security Lead | OPEN |
| Is the Compliance/Auditor clinic-read in MVP scope? | Head of Product | OPEN |
