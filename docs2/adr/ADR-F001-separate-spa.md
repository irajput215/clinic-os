# ADR-F001: A separate SPA beside `frontend/`

- **Status:** Superseded by [ADR-F005](ADR-F005-one-app-served-by-the-backend.md)
- **Date:** 2026-10-06

> Superseded on 2026-10-06. `frontend-features/` is now the only app; it builds into the backend
> image and is served at `/`, and `frontend/` has been deleted. Kept for the record of why the two
> apps once ran side by side.

## Context

The existing `frontend/` is the template-derived admin UI. It has a dark-theme shadcn look, and its
build output is served by the backend image. The clinic needs a different product surface that
follows the Banksia reference design, and work on `frontend/` (admin screen, auth fixes) is
in flight in other branches.

## Decision

Build `frontend-features/` as its own Vite + React 19 + TanStack Router/Query + Tailwind v4 app.
It shares the stack, the shadcn primitives (copied and restyled through tokens), the generated
OpenAPI client, the error helpers and the 401-only sign-out rule with `frontend/`. It runs on port
5174 and builds to its own `dist/`. It does not touch `frontend/` or the backend image.

## Consequences

- No merge conflicts with in-flight `frontend/` work, and the two can run side by side.
- Two SPAs to keep in step on shared conventions. The shared pieces are small (`lib/http.ts`, `ui/*`)
  and documented. Once this app covers the admin screens, `frontend/` can be retired in a single,
  deliberate change.
- Deployment needs either a second static origin (and `VITE_API_URL` plus a CORS entry), or for
  the backend to serve this build instead of `frontend/`. That choice belongs with D-004.
