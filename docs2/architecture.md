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

Every row was checked against the code on 2026-10-08 (branch `m3/frontend-speed`).

| Measure | Effect | Where |
|---|---|---|
| Route-level code splitting (`autoCodeSplitting`); a route file holds only its loader and search validation | Each screen's code, dialogs, zod and react-hook-form load with the screen that needs them | `vite.config.ts`, `routes/` |
| React in its own chunk | A deploy that changes only app code leaves React's ~55 KB cached | `vite.config.ts` (`codeSplitting.groups`) |
| Toast library fetched when the browser is idle after the first paint | Not on the first load's critical path | `main.tsx` (`DeferredToaster`) |
| No schema library in route search validation | zod loads with forms, not on every page | `lib/search.ts` |
| Intent preloading (`defaultPreload: "intent"`) and loader prefetching | A hovered or focused link has its code and data before the click | `main.tsx`, `routes/` |
| No first-load waterfall: the `_app` loader starts `/users/me`, the permission set and the two sidebar counts together with the screen's own loader | One round trip before the shell and the page can render. Only the clinic slug waits (for the permission set, so it is never asked when the server is certain to refuse) | `routes/_app.tsx`, proved by `tests/first-load.spec.ts` |
| Per-query `staleTime`: session, permissions 5 min, tenant for the session; clinical lists and Today 15 s, sidebar approval count 30 s; `retry` only for network/5xx (`retryTransient`) | No refetch storms, no 7-second retries on a `403` | `data/*.ts`, `lib/session.ts` |
| One-round-trip Today page (`GET /dashboard/today`, every section read on one server transaction) | One request instead of four | `data/dashboard.ts` |
| Self-hosted fonts, latin and latin-ext only, woff2 only, `font-display: swap`; the serif's italic from the smaller `wght` file | 16 font files in the build (was 44); sign-in downloads 238 KB of fonts (was 315 KB) | `styles/fonts.css` |
| The serif and body latin files preloaded from `index.html`, hashed URLs written at build | Text is drawn in its own face sooner | `vite.config.ts` (`preloadFonts`) |
| Hashed `/assets/*` sent `Cache-Control: public, max-age=31536000, immutable`; HTML (`index.html`, the SPA fallback) sent `no-cache` | A returning browser asks for nothing but the HTML (answered `304`), and never runs a stale `index.html` | `backend/app/core/static_cache.py`, `tests/core/test_static_cache.py` |
| Brotli and gzip copies written at build with Node's zlib; the backend sends the one the browser accepts (`Content-Encoding`, `Vary: Accept-Encoding`) | JS and CSS travel compressed from the origin; no per-request compression, no new dependency | `vite.config.ts` (`precompress`), `static_cache.py` |
| Skeletons, not spinners, while a screen or section loads; `PagePending` has `PageHeader`'s exact height | Nothing jumps when data arrives | `design/primitives.tsx` |

Optimistic updates: none. Every mutation in the app is either a clinical or audited action (signing,
dispatch, approvals, appointments, consult notes, patients, role grants, invitations) or a change to
one's own account that the server validates; each waits for the server's answer.

**Budgets** (CI, `.github/workflows/playwright.yml`, `bun run check:budget` after `bun run build`;
gzip):

| | Budget | Measured | Before this branch |
|---|---|---|---|
| Initial JS (entry + every `modulepreload`): what any first load fetches before rendering | 142 KB | 137.1 KB | 145.2 KB |
| Entry chunk (`index-*.js`) | 90 KB | 35.8 KB (React is its own chunk) | 98.3 KB |
| Largest lazy chunk (zod with react-hook-form) | 35 KB | 28.6 KB | 28.6 KB |
| CSS | 15 KB | 10.8 KB | 11.3 KB |

**Largest Contentful Paint** under 2 s on sign-in and Today, cold, measured against the
backend-served build (`tests/performance.spec.ts`) with Chrome DevTools throttling: 9 Mbit/s down,
1.5 Mbit/s up, 30 ms added round trip (a clinic near a Sydney edge on fast 4G or ordinary office
broadband), CPU slowed 2x. Measured locally (median of five): about 0.70 s on both.

## Accessibility

Every control has an accessible name. Fields use real `<label for>`. Tables use real `<th>`. Status
pills carry text, not colour alone. Focus is visible on everything (`:focus-visible`). Dialogs are
Radix (focus trap, Esc, return focus). `prefers-reduced-motion` turns animation off. Validation
messages are `role="alert"`.
