# Architecture

## Shape

```
frontend/src
├── main.tsx              API client config, query client, router, 401 handling
├── routes/               TanStack file routes: thin; validate search params, prefetch, render a feature
├── features/<feature>/   screens and dialogs, one folder per SDLC feature
├── data/                 repositories: the only code that knows where data comes from
│   ├── capabilities.ts   per-feature switch: `api` or `preview`
│   ├── types.ts          MIRROR types (copied from backend branches) and PROPOSED contracts
│   ├── api.ts            typed call for routes not yet in the generated client
│   └── preview/          the in-browser stand-in backend (seed, gate mirror, store)
├── design/               primitives: PageHeader, Card, StatCard, Pill, Mono, Field, banners, states
├── shell/                AppShell, sidebar nav, top bar, global search, brand mark
├── components/ui/        shadcn/Radix primitives, restyled through tokens
├── client/               generated from backend OpenAPI (do not edit; `bun run generate-client`)
└── lib/                  http errors, session, formatting (Australia/Sydney), search-param parsers
```

Screens never call `fetch`/axios. They call a repository (`data/*.ts`) through TanStack Query. A
repository has an `api` implementation and/or a `preview` one behind the same interface, chosen by
[`capabilities.ts`](../frontend/src/data/capabilities.ts). When a backend module merges, one
line changes and the screens do not. See [capabilities.md](capabilities.md).

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
- **The safety gate** result shown on a script will be the server's answer once `prescriptions` is
  `api` (the gate runs inside the signing transaction). While scripts are preview it comes from a
  stand-in that mirrors the server's rules over the preview's sample approvals
  ([`data/preview/gate.ts`](../frontend/src/data/preview/gate.ts)), never over the
  patient's real approvals, so one screen can't say "covered" while signing says "blocked".
  Either way, the UI disables signing when the answer is a refusal, and the server must refuse again
  at sign and at dispatch (proposed contract in [sdlc/07](sdlc/07-script-queue/api.md)).
- **Four-eyes**, double-booking, state transitions: the preview enforces them the way the backend
  does, so the UI is built around the refusals. In API mode the server enforces them.
- **Step-up for signing.** Signing re-enters the password and re-authenticates against
  `POST /login/access-token` before the sign call. This is an interim measure until D-003 (identity,
  MFA) lands; see [ADR-F002](adr/ADR-F002-token-storage.md).

## Security measures in the app

| Concern | Measure | Where |
|---|---|---|
| XSS | No `dangerouslySetInnerHTML`. All text rendered as React text. | everywhere |
| Script injection | Strict CSP injected at build: `script-src 'self'` (no `unsafe-eval`; zod runs `jitless`), `connect-src` only self + API origin, `object-src 'none'`, `base-uri 'none'` | `vite.config.ts`, `lib/zod.ts` |
| Clickjacking | The host sends the headers (browsers ignore `frame-ancestors` in a meta policy): every backend response, including the app's HTML at `/` and `/docs`, carries `Content-Security-Policy: frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Strict-Transport-Security`. **Closed 2026-10-07** | `backend/app/core/security_headers.py`, `tests/security/test_security_headers.py` |
| Token exposure | Token in `sessionStorage` (one tab, cleared on close), never in URLs or logs. 15-minute lifetime is server-enforced | `lib/session.ts`, ADR-F002 |
| Open redirect | `redirect` accepted only as a same-origin path | `lib/search.ts` |
| PHI in URLs | No identifiers or names in query strings. Patient search filters in memory | `shell/GlobalSearch.tsx` |
| PHI in error UI | Errors render the API's sentence or a fixed one, never request data | `lib/http.ts` |
| Referrer leakage | `<meta name="referrer" content="no-referrer">` | `index.html` |
| Session scope | Sign-out clears the token, the query cache and the preview store | `shell/AppShell.tsx` |
| Input | Every form validates with zod before submit. The server re-validates | `features/**` |

## Speed measures

| Measure | Effect |
|---|---|
| Route-level code splitting (`autoCodeSplitting`), no page code in route definitions | Entry chunk is the shell and libraries only |
| No schema library in route search validation (`lib/search.ts`) | zod loads with forms, not on every page |
| Hover/intent preloading and loader prefetching | Navigation renders from cache |
| Per-query `staleTime`, `retry` only for network/5xx (`retryTransient`) | No refetch storms, no 7-second retries on a `403` |
| Self-hosted fonts (`@fontsource`), `unicode-range` subsets | No third-party font request; only the Latin subset downloads |
| One-round-trip Today page (proposed `GET /dashboard/today`) | One request instead of four |

**Budget:** initial JS at most 200 KB gzipped. Measured at build: entry 115 KB plus shared 36 KB, so
about 151 KB. Every route chunk is under 7 KB gzipped.

## Accessibility

Every control has an accessible name. Fields use real `<label for>`. Tables use real `<th>`. Status
pills carry text, not colour alone. Focus is visible on everything (`:focus-visible`). Dialogs are
Radix (focus trap, Esc, return focus). `prefers-reduced-motion` turns animation off. Validation
messages are `role="alert"`.
