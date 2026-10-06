# D-005: Route path convention — `/api/v1` prefix, with provider webhooks as the one exception

- **Status:** Accepted
- **Date:** 2026-10-04
- **Owner:** CTO
- **Source contract reference:** `01-system-architecture.md` §5 (module → owned endpoints); `21-technical-design.md` §7 (API design standard); `02-security-architecture.md` §11 (rate limits by endpoint class). None of these mandates URL versioning; all of them name unversioned paths such as `/patients`, `/tga-approvals`, `/prescriptions/{id}/dispatch`.

## Context

The source contract names routes without a version segment: `/auth/*`, `/patients/*`,
`/clinical-records/*`, `/tga-approvals/*`, `/tga-inbox/*`, `/prescriptions/*`, `/pharmacy/*`,
`/audit/*`, `/reports/*`, `/admin/*`, and provider callbacks at `/webhooks/:provider`.

This repository already versions its API, and it is wired into the application root:

```python
# backend/app/core/config.py
API_V1_STR: str = "/api/v1"

# backend/app/main.py
app.include_router(api_router, prefix=settings.API_V1_STR)
openapi_url=f"{settings.API_V1_STR}/openapi.json"
```

The template's existing routes are therefore `/api/v1/login/access-token`, `/api/v1/users/`,
`/api/v1/items/`, `/api/v1/utils/` and `/api/v1/private/`. The OpenAPI document — and the
`openapi-ts`-generated frontend client (`bun run generate-client`) — are published under `/api/v1`.

During authoring of this document set the two conventions were used inconsistently: the four original
feature documents and the Phase 2 phase set used `/api/v1`, while Phase 1, Phase 3 and FEAT-05 used the
source contract's unversioned paths. A reader could not tell which was canonical.

## Decision

**Client-facing API routes carry the `/api/v1` prefix**, taken from `settings.API_V1_STR`. A route that
omits it is a defect.

**The single exception is provider webhook ingress.** An inbound provider callback is an external
contract the platform does not control and cannot version unilaterally; a provider will not change its
callback URL because we cut a v2. Webhook ingress is therefore mounted **without** the version prefix:

| Route | Convention |
|---|---|
| `/api/v1/auth/*`, `/api/v1/tenants/*`, `/api/v1/users/*`, `/api/v1/roles/*`, `/api/v1/permissions/*` | Prefixed |
| `/api/v1/patients/*`, `/api/v1/clinical-records/*`, `/api/v1/documents/*` | Prefixed |
| `/api/v1/tga-approvals/*`, `/api/v1/tga-inbox/*` | Prefixed |
| `/api/v1/prescriptions/*` | Prefixed |
| `/api/v1/audit/*`, `/api/v1/reports/*`, `/api/v1/admin/*` | Prefixed |
| `/api/v1/pharmacy/dispatch*` | Prefixed |
| **`/pharmacy/webhooks/{provider}`** | **NOT prefixed** — inbound provider contract |

Nested resources take the prefix once, at the root: `/api/v1/patients/{id}/documents`,
`/api/v1/prescriptions/{id}/dispatch`, never `/api/v1/patients/{id}/api/v1/documents`.

**Still OPEN beneath this decision:** whether webhook ingress is `/pharmacy/webhooks/{provider}` (source
doc 02 §11) or `/webhooks/{provider}` provider-scoped (source doc 10 §7). That conflict is carried as
**O5** in [`../../features/12-pharmacy-dispatch/01-requirements.md`](../../features/12-pharmacy-dispatch/01-requirements.md) and
is owned by the Security Lead. This decision fixes only the *prefix* question, not the *mount point*.

## Consequences

**Easier:** one prefix rule; the OpenAPI document, the generated frontend client and the existing
template routes stay coherent. A reader of any document can predict a route.

**Harder:** every endpoint path quoted from the source contract now needs the prefix added when it is
implemented. The source's paths remain correct *as citations* — the divergence is between the contract's
naming and this repo's convention, exactly like D-001 and D-002.

**Normalised under this decision:** `docs/features/10-prescription-safety-gate/01-requirements.md`,
all feature folders were normalised to the prefixed form, with
`/pharmacy/webhooks/{provider}` deliberately left unprefixed.

## Effect on the gates

- **Gate 4 (APIs)** checks "every endpoint declares authentication, permission, tenant scope, ownership
  rule, input schema, output schema, audit event, rate limit and error behaviour". Those declarations are
  unaffected in substance; only the path prefix changes. Gate 4 evidence must be taken from the routes as
  registered, so the prefixed form is the one that can be checked against `app.routes`.
- **Gate 6:** the OpenAPI snapshot used for environment verification must be fetched from
  `/api/v1/openapi.json`.
- No gate is blocked by this decision.

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | Close O5 — the webhook mount point (`/pharmacy/webhooks/{provider}` vs `/webhooks/{provider}`) | Security Lead |
| 2 | Confirm whether an unversioned alias is required for any existing integration before the prefix becomes final | CTO |
| 3 | Confirm that a future `v2` would be a new prefix rather than a breaking change to `v1`, and record it as its own decision if so | CTO |
