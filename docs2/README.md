# docs2: the ClinicOS web app

`docs2/` documents the ClinicOS web app in [`frontend/`](../frontend/), the only
frontend in this repository. The app follows the Banksia ClinicOS reference design; the backend image
builds it and serves it at `/`, beside the API under `/api`
([ADR-F005](adr/ADR-F005-one-app-served-by-the-backend.md)).

`docs/` remains the normative contract for the platform. It covers requirements, invariants, gates
and the backend modules. `docs2/` covers only what the new app adds on top of it: the UI, how the UI
uses the API, and the API contracts the UI needs but that no backend module serves yet. When the two
disagree, `docs/` wins and the disagreement is a defect to raise.

## Start here

| Document | What it answers |
|---|---|
| [architecture.md](architecture.md) | How the app is built, how it talks to the backend, the speed and security measures |
| [design-system.md](design-system.md) | Tokens, type, components, and how they map to the reference design |
| [capabilities.md](capabilities.md) | Which screens read the real API and which run on the preview store, and how to switch |
| [sdlc/](sdlc/) | One folder per feature: requirements, design, API contract, test plan, Definition of Done |
| [adr/](adr/) | Decisions specific to this app |

## Run it

```bash
# 1. Backend (any of the repo's usual ways), listening on 127.0.0.1:8000
docker compose watch            # or: cd backend && uv run fastapi dev app/main.py

# 2. The app, with hot reload (from the repository root; workspace scripts)
cp frontend/.env.example frontend/.env.local   # optional; the proxy defaults to :8000
bun install
bun run dev                     # http://127.0.0.1:5174, proxies /api to the backend

# Checks
bun run lint && bun run typecheck
bun run build                   # writes backend/app/frontend; the backend then serves it at /
bun run test                    # Playwright, starting the dev server

# The app as it ships: the backend serving the production build
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8000 bun run test
```

`docker compose watch` builds the backend image, which builds this app, so <http://localhost:8000> is
the production build. CI runs the Playwright suite the same way (`.github/workflows/playwright.yml`).

Sign in with any account that belongs to an organisation. To create one, use `POST /api/v1/users/signup`
with a `clinic_name` (open registration is on in development). The public booking page needs no account:
`/book/<clinic-slug>`.

## Feature map

| # | Feature | Screens | Data source today |
|---|---|---|---|
| 01 | [Auth and app shell](sdlc/01-auth-and-shell/) | Sign in, sidebar, top bar, patient quick-find | API |
| 01 | [Auth and app shell](sdlc/01-auth-and-shell/) | Organisation signup, password recovery and reset | API |
| 01 | [Auth and app shell](sdlc/01-auth-and-shell/) | Administration: roles and permissions, user access, accounts (superuser) | API |
| 01 | [Auth and app shell](sdlc/01-auth-and-shell/) | Settings: profile, password, deactivate own account | API |
| 02 | [Patients](sdlc/02-patients/) | Patients list, add/edit, patient record | API |
| 03 | [Consult notes](sdlc/03-consult-notes/) | Patient record → Consult notes | API (clinical records, #47) |
| 04 | [Calendar and booking](sdlc/04-calendar-and-booking/) | Calendar day/week, public booking page | Preview (contract proposed) |
| 05 | [TGA approvals](sdlc/05-approvals/) | Approvals register, patient approvals tab | Patient tab: API (#46). Register: refusal until `GET /tga-approvals` exists |
| 06 | [Patient activity](sdlc/06-patient-activity/) | Patient record → Activity | API (audit log, #42) |
| 07 | [Script queue](sdlc/07-script-queue/) | Script queue, review and sign, patient scripts tab | Preview (contract proposed) |
| 08 | [Today](sdlc/08-today/) | Today's clinic dashboard | Preview (contract proposed) |
