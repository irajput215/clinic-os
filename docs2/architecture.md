# Architecture

## Shape

```
frontend/src
├── main.tsx              API client config, query client, router, 401 handling
├── routes/               TanStack file routes: thin; validate search params, prefetch, render a feature
├── features/<feature>/   screens and dialogs, one folder per SDLC feature
├── data/                 repositories: the only code that calls the API
│   └── types.ts          MIRROR vocabularies the generated client types only as `string`
├── design/               primitives: PageHeader, Card, StatCard, Pill, Mono, Field, states
├── shell/                AppShell, sidebar nav, top bar, global search, brand mark
├── components/ui/        shadcn/Radix primitives, restyled through tokens
├── client/               generated from backend OpenAPI (do not edit; `bun run generate-client`)
└── lib/                  http errors, session, formatting (Australia/Sydney), search-param parsers
```

Screens never call `fetch`/axios. They call a repository (`data/*.ts`) through TanStack Query, and
every repository calls the generated client. There is no second data source: the in-browser preview
store that stood in for unbuilt backends is deleted
([ADR-F006](adr/ADR-F006-preview-store-retired.md), superseding ADR-F004).

Where the generated client types a field more loosely than the backend enforces (a state or reason
code typed `string`), the repository narrows it with a **MIRROR** type in
[`data/types.ts`](../frontend/src/data/types.ts), each commented with the backend file it copies.

## Build and deployment

There is one frontend, and the backend serves it
([ADR-F005](adr/ADR-F005-one-app-served-by-the-backend.md), superseding ADR-F001).

- `bun run build` (root workspace script, or `bun run --filter frontend build`) typechecks
  and writes the production build to `backend/app/frontend/`, which is gitignored output.
- `backend/app/main.py` serves that directory at `/` with `app.frontend(...)`. API routes match
  first, so `/api/*`, `/docs` and `/redoc` are never shadowed. A path with no file falls back to
  `index.html` only for a request that accepts HTML, so deep links (`/reset-password?token=...`,
  `/patients/<id>`, `/book/<clinic-slug>`) load the app, and an unknown `/api/...` or `/assets/...`
  fetch still gets a `404`.
- `backend/Dockerfile` builds this app in its first stage and copies the output to the same path
  in the image. `deploy.yml` builds it on the runner before `fastapi deploy`
  (`.fastapicloudignore` keeps `backend/app/frontend/`).
- App and API share one origin, so `VITE_API_URL` is empty in production builds and the build's
  CSP `connect-src` is `'self'`. The dev server (`:5174`) proxies `/api` instead.
- Emailed links are built from the backend's `FRONTEND_HOST`, which must be the URL that serves
  this app (the backend's own public URL).

## Request path

1. A route's `beforeLoad` sends a session without a token to `/login?redirect=…`. `redirect` must be a
   same-origin path, so it can't be used as an open redirect.
2. The route `loader` warms the query cache (`ensureQueryData` / `prefetchQuery`). Links preload on
   hover (`defaultPreload: "intent"`), so most navigations render from cache.
3. The generated client sends `Authorization: Bearer <token>` with a 15 s timeout.
4. The server decides. A `401` anywhere signs the user out once and returns to sign-in. A `403` stays
   on the page and says "not available to your role". A `404` (also returned for another tenant's
   record, by design) renders "not available", not an error.
5. Error bodies are RFC 7807. The refusal sentence comes from `detail.message` (falling back to
   `title`), and every failure state shows the `request_id` as a "Reference" so a support conversation
   can find the server's log line ([`lib/http.ts`](../frontend/src/lib/http.ts)).

## The backend is the security boundary

The UI hides, disables and explains. It never decides. In particular:

- **Tenant** is never sent. Every body is built from form fields that don't include it, and the
  API's `extra="forbid"` schemas would refuse it anyway.
- **The safety gate** result shown on a script (the queue, the review dialog, the Today page) is the
  server's answer, evaluated now for display only. The UI disables signing when the answer is a
  refusal, and the server decides again inside the signing and dispatch transactions, with the
  approval rows locked ([sdlc/07](sdlc/07-script-queue/api.md)).
- **Four-eyes**, double-booking, state transitions: the server enforces them, and the UI shows its
  refusals (`detail.code`, worded in `lib/http.ts`).
- **Role boundaries.** A `403` shows "not available to your role". The Today page's sections are
  gated by the server: a section the role cannot read is withheld from the response, and its card
  shows the same lock ([sdlc/08](sdlc/08-today/api.md)).
- **Step-up for signing and dispatch.** The password is re-entered and checked by the server
  (`POST /api/v1/auth/step-up`), which returns a single-use grant bound to the user, the operation and
  the script. This is an interim measure until D-003 (identity, MFA) lands; see
  [ADR-F002](adr/ADR-F002-token-storage.md).

## Security measures in the app

| Concern | Measure | Where |
|---|---|---|
| XSS | No `dangerouslySetInnerHTML`. All text rendered as React text. | everywhere |
| Script injection | Strict CSP injected at build: `script-src 'self'` (no `unsafe-eval`; zod runs `jitless`), `connect-src` only self + API origin, `object-src 'none'`, `base-uri 'none'` | `vite.config.ts`, `lib/zod.ts` |
| Clickjacking | The host sends the headers (browsers ignore `frame-ancestors` in a meta policy): every backend response, including the app's HTML at `/` and `/docs`, carries `Content-Security-Policy: frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Strict-Transport-Security`. **Closed 2026-10-07** | `backend/app/core/security_headers.py`, `tests/security/test_security_headers.py` |
| Token exposure | Token in `sessionStorage` (one tab, cleared on close), never in URLs or logs. 15-minute lifetime is server-enforced | `lib/session.ts`, ADR-F002 |
| Open redirect | `redirect` accepted only as a same-origin path | `lib/search.ts` |
| PHI in URLs | No identifiers or names in query strings. Patient search sends the term in a `POST /patients/search` body and keeps it in component state, never the route | `shell/GlobalSearch.tsx`, `features/patients/PatientsPage.tsx` |
| PHI in error UI | Errors render the API's sentence or a fixed one, never request data | `lib/http.ts` |
| Referrer leakage | `<meta name="referrer" content="no-referrer">` | `index.html` |
| Session scope | Sign-out clears the token and the query cache | `shell/AppShell.tsx` |
| Input | Every form validates with zod before submit. The server re-validates | `features/**` |

## Speed measures

| Measure | Effect |
|---|---|
| Route-level code splitting (`autoCodeSplitting`), no page code in route definitions | Entry chunk is the shell and libraries only |
| No schema library in route search validation (`lib/search.ts`) | zod loads with forms, not on every page |
| Hover/intent preloading and loader prefetching | Navigation renders from cache |
| Per-query `staleTime`, `retry` only for network/5xx (`retryTransient`) | No refetch storms, no 7-second retries on a `403` |
| Self-hosted fonts (`@fontsource`), `unicode-range` subsets | No third-party font request; only the Latin subset downloads |
| One-round-trip Today page (`GET /dashboard/today`, every section read on one server transaction) | One request instead of four |

**Budget:** initial JS at most 200 KB gzipped. Measured at build: entry 115 KB plus shared 36 KB, so
about 151 KB. Every route chunk is under 7 KB gzipped.

## Accessibility

Every control has an accessible name. Fields use real `<label for>`. Tables use real `<th>`. Status
pills carry text, not colour alone. Focus is visible on everything (`:focus-visible`). Dialogs are
Radix (focus trap, Esc, return focus). `prefers-reduced-motion` turns animation off. Validation
messages are `role="alert"`.
