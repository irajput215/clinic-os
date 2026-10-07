# ADR-F005: One app, built from `frontend-features/`, served by the backend at `/`

- **Status:** Accepted
- **Date:** 2026-10-06
- **Supersedes:** [ADR-F001](ADR-F001-separate-spa.md)
- **Decided by:** the owner (handoff decision D-A, 2026-10-06)
- **Amended:** 2026-10-07. The app directory is now `frontend/` (see the addendum below). The body
  keeps the name the app had when this decision was taken, `frontend-features/`.

## Context

[ADR-F001](ADR-F001-separate-spa.md) built `frontend-features/` as a second SPA beside the template
admin UI in `frontend/`, built to its own `dist/` and outside the backend image, and left the
deployment choice to D-004. The result was two apps, two sets of tooling, and a deployed site that
still served the old UI: nothing in `deploy.yml` or `backend/Dockerfile` built the new one.

The old UI was the only home of four surfaces: organisation signup (the only way to create a
tenant), password recovery and reset, administration, and settings. All four now exist in
`frontend-features/` in its own design system (`/signup`, `/recover-password`, `/reset-password`,
`/admin`, `/settings`), so nothing is lost by removing `frontend/`.

## Decision

There is one frontend: `frontend-features/`. `frontend/` is deleted.

- `frontend-features/vite.config.ts` builds to `../backend/app/frontend`, the directory
  `backend/app/main.py` already serves at `/` (`FRONTEND_DIR`). No backend change was needed.
- The backend serves the build with FastAPI's `app.frontend("/", ...)`. API routes are matched first,
  so `/api/*`, `/docs` and `/redoc` are never shadowed. A missing path falls back to `index.html`
  only for a request that accepts HTML (a browser navigation), so deep links such as
  `/reset-password?token=...`, `/patients/<id>` and `/book/<clinic-slug>` load the app, while an
  unknown `/api/...` or `/assets/...` fetch still gets a `404` problem response.
- The app and the API share one origin. `VITE_API_URL` is empty in every production build, so the
  client calls `/api` on its own origin and the build's CSP `connect-src` is `'self'` alone.
- Everything that built, tested or linted `frontend/` points at `frontend-features/`: `deploy.yml`,
  `backend/Dockerfile`, `playwright.yml`, `test-docker-compose.yml`, `compose.override.yml`,
  `scripts/generate-client.sh` (one SDK), `.pre-commit-config.yaml` (one biome hook), the root
  `package.json` (one workspace, one script set), `.dockerignore`, `dependabot.yml` and
  `latest-changes.yml`.
- CI's Playwright shards run `frontend-features/tests` from `frontend-features/Dockerfile.playwright`
  against the backend container, which serves the production build. There is no Vite dev server in
  CI: the suite tests the app that ships.

## Consequences

- One app, one build, one URL. What the Playwright suite exercises is what is deployed.
- The served HTML proves which app is live: its title is `Clinic OS` (the old one was `ClinicOS`),
  and `test-docker-compose.yml` checks for it.
- **D-004 is narrowed, not closed.** One frontend served by the backend image rules out D-004's
  "second static origin plus CORS" option. The platform choice itself (FastAPI Cloud + Neon is
  running, and matches none of D-004's options) stays open.
- Local development still uses the Vite dev server on `:5174`, which proxies `/api` to the backend,
  so the CSP is injected at build only and HMR is unaffected.
- The ADR-F001 concern about keeping two SPAs in step is gone. So is the old app's `localStorage`
  token: [ADR-F002](ADR-F002-token-storage.md) (`sessionStorage`) is now the only token rule.

## Addendum (2026-10-07): the app directory is `frontend/`

With the template UI gone, the `-features` suffix distinguished the app from nothing. The owner
decided to give the one app the conventional name: `frontend-features/` was renamed to `frontend/`
(`git mv`, history kept), and the bun workspace package is now `frontend`
(`bun run --filter frontend <script>`).

Nothing else in this decision changes: the build still lands in `backend/app/frontend`, the backend
still serves it at `/`, and CI still runs the Playwright suite against the served build. Every path
that named `frontend-features/` now names `frontend/`: the root `package.json` workspaces and
scripts, `bun.lock`, `backend/Dockerfile`, `frontend/Dockerfile.playwright`, `.dockerignore`,
`compose.override.yml`, `scripts/generate-client.sh`, `.pre-commit-config.yaml`, the workflows,
`dependabot.yml`, `latest-changes.yml`, `.vscode/launch.json` and the docs. Mentions of
`frontend-features/` that remain describe what happened before the rename.
