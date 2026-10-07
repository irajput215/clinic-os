# How to run ClinicOS

A copy-paste guide for a new developer. Every block runs from the **repository root** unless it
starts with a `cd`. The backend is FastAPI on `:8000`; the app in `frontend/` is React + Vite, built
into `backend/app/frontend` and served by the backend at `/`.

## 1. Prerequisites

| Tool | Version | Where it is pinned |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | recent (CI installs the latest) | `.github/workflows/test-backend.yml` |
| Python | 3.14 (uv installs it for you) | `.python-version`, `backend/pyproject.toml` |
| [bun](https://bun.sh) | 1.3.12 or newer | `.github/workflows/*.yml` (`bun-version`) |
| Docker with Compose v2 | recent | runs PostgreSQL 18 and Mailpit (`compose.yml`) |

## 2. Configure

```bash
cp .env.example .env
```

Replace every `REPLACE_ME` in `.env`. Generate each value with
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`:

- `SECRET_KEY` - signs tokens.
- `FIRST_SUPERUSER_PASSWORD` - password of the platform superuser `FIRST_SUPERUSER` (`admin@example.com`).
- `POSTGRES_PASSWORD` - the database password. Postgres reads it only when its volume is first
  created, so set it before step 3.
- `DOMAIN` - only used by `compose.deploy.yml`; leave it for local work.

Keep `USERS_OPEN_REGISTRATION=true` locally: it is what lets you create a clinic from the signup
page. Never commit `.env`.

## 3. Start the database and Mailpit

```bash
docker compose up -d db mailpit
```

PostgreSQL listens on `localhost:5432`; Mailpit catches all outgoing mail (SMTP `:1025`, web UI
<http://localhost:8025>).

## 4. Backend

```bash
cd backend
uv sync
uv run bash scripts/prestart.sh      # alembic upgrade head + app/initial_data.py (first superuser)
uv run fastapi dev app/main.py       # http://127.0.0.1:8000, reloads on change
```

API docs: <http://127.0.0.1:8000/docs>. Health: `curl http://127.0.0.1:8000/api/v1/utils/health-check/`.

## 5. Frontend - pick one

**a) Dev server with hot reload** (second terminal):

```bash
bun install
bun run dev                          # http://127.0.0.1:5174, proxies /api to :8000
```

Optional: `cp frontend/.env.example frontend/.env.local` to point the proxy elsewhere
(`VITE_API_PROXY_TARGET`).

**b) The app as it ships**, served by the backend:

```bash
bun install
bun run build                        # writes backend/app/frontend
```

Open <http://127.0.0.1:8000> (page title `Clinic OS`). Rebuild after frontend changes.

## 6. First clinic and sign in

Open `/signup` (on `:5174` or `:8000`), enter a clinic name, your name, email and password. That
creates the organisation and makes you its administrator. The public booking page is
`/book/<clinic-slug>`. `FIRST_SUPERUSER` is the platform superuser (account administration), not a
clinic member.

Password reset: "Forgot password" on the sign-in page sends the email to Mailpit
(<http://localhost:8025>). Its link uses `FRONTEND_HOST` (default `http://localhost:8000`); add
`FRONTEND_HOST=http://127.0.0.1:5174` to `.env` if you work on the dev server.

## 7. Checks

```bash
# Frontend (from the repo root; same scripts exist inside frontend/)
bun run lint                         # biome, writes fixes
bun run lint:ci                      # biome, read-only (what CI runs)
bun run typecheck

# Backend
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run alembic check                 # must report no operations
cd ..

# Every pre-commit hook, as CI runs them
uv run prek run --all-files
```

**Regenerate the SDK** after any API change (the `Generate Frontend SDK` hook does this too):

```bash
bash ./scripts/generate-client.sh    # writes frontend/openapi.json and frontend/src/client
```

### Backend tests: use a scratch database

`pytest` deletes every user on teardown, so point it at a throwaway database, not the one you
develop in (it refuses any host other than localhost/`db`):

```bash
PW=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
docker compose exec db psql -U postgres -c 'CREATE DATABASE app_test'
cd backend
export DATABASE_URL="postgresql://postgres:${PW}@localhost:5432/app_test"
uv run bash scripts/prestart.sh
uv run pytest                        # or: uv run pytest tests/path::test_name
```

If `.env` sets `MIGRATION_DATABASE_URL`, export it pointing at `app_test` too.

### End-to-end tests (Playwright)

Install the browser once: `cd frontend && bun x playwright install chromium`.

```bash
# Against the dev server (started for you, or reused if :5174 is up); backend on :8000
bun run test

# Against the backend serving the build (what CI and production run)
bun run build
cd frontend && PLAYWRIGHT_BASE_URL=http://127.0.0.1:8000 bun x playwright test
```

Each run signs up a fresh clinic, so runs do not share data. To keep your dev database clean, run
the suite against a second backend on a scratch database:

```bash
PW=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
docker compose exec db psql -U postgres -c 'CREATE DATABASE app_e2e'
cd backend
export DATABASE_URL="postgresql://postgres:${PW}@localhost:5432/app_e2e"
uv run bash scripts/prestart.sh
FRONTEND_HOST=http://127.0.0.1:8108 uv run fastapi run app/main.py --host 127.0.0.1 --port 8108
# in another terminal, from the repo root:
cd frontend && PLAYWRIGHT_BASE_URL=http://127.0.0.1:8108 bun x playwright test
```

Afterwards: `docker compose exec db psql -U postgres -c 'DROP DATABASE app_e2e WITH (FORCE)'`.

## 8. Whole stack in Docker

```bash
docker compose run --rm backend bash scripts/prestart.sh
docker compose watch                 # or: docker compose up -d
```

The backend image builds the app, so <http://localhost:8000> is the production build; Adminer is
on <http://localhost:8080>, Mailpit on <http://localhost:8025>. Stop any local `fastapi dev` first:
both want `:8000`. CI's Playwright job runs the same way:
`docker compose run --rm playwright bunx playwright test` (see `.github/workflows/playwright.yml`).

## 9. Deployment

Pushing to `main` (or running it from the Actions tab) runs `.github/workflows/deploy.yml`: it builds
the app, runs `prestart.sh` against the production database and deploys to FastAPI Cloud, then
waits for the readiness probe. Secrets live in two places only: GitHub repository secrets
(`DATABASE_URL`, `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, `FASTAPI_CLOUD_TOKEN`,
`FASTAPI_CLOUD_APP_ID`) and the FastAPI Cloud application environment. A local `.env.cloud` is for
your own use, is gitignored and must never be committed. Details: [deployment.md](deployment.md).

## 10. Troubleshooting

- **500s or "relation does not exist" after pulling** - your database is behind the code:
  `cd backend && uv run alembic upgrade head`.
- **Port already in use** (`5432`, `8000`, `5174`, `8025`) - find the owner with
  `lsof -nP -iTCP:8000 -sTCP:LISTEN` and stop it. The dev server uses a fixed port (`strictPort`)
  and fails rather than moving.
- **429 Too Many Requests in e2e runs** - login is limited to 20/min and password recovery to
  5/min per client, per backend process. Restart the backend to clear the window, or start the
  test backend with `RATE_LIMIT_ENABLED=false`.
- **`{"detail":"Not Found"}` on `http://127.0.0.1:8000/`** - the app is not built: `bun run build`,
  then restart the backend if it started before the first build.
- **`ValidationError` for `SECRET_KEY`, `PROJECT_NAME` or `DATABASE_URL` on start** - `.env` is missing:
  repeat step 2.
