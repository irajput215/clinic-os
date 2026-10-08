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

`FRONTEND_HOST` (default `http://localhost:8000`) is the URL that serves the app: the only CORS
origin and the base of emailed links. Leave it for local work against `:8000`; see step 6 for the
dev server.

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
`FRONTEND_HOST=http://127.0.0.1:5174` to `.env` if you work on the dev server. A reset link works
once: after it has set a password it is refused like an expired one.

### Add staff to your clinic

1. Signed in as the clinic's owner (or an administrator), open **Administration**. It starts on
   **Staff**, the people in your organisation.
2. **Invite staff member**: enter their full name and email and tick one or more roles. You can only
   offer roles whose permissions you hold yourself. **Send invitation** adds them to the list.
3. Open Mailpit at <http://localhost:8025>: the invitation email is there. Its link
   (`{FRONTEND_HOST}/accept-invite?token=...`) is valid for 72 hours (`STAFF_INVITATION_EXPIRE_HOURS`)
   and works once.
4. Open the link (a private window keeps your own session): **Join your clinic** asks the invitee
   to choose a password. **Set password and sign in** signs them straight into your clinic with the
   invited roles.
5. From then on they sign in at `/login` with that email and password.

With no outgoing mail configured, **Send invitation** is refused (`503 EMAIL_NOT_CONFIGURED`) and
nothing is created.

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
`FASTAPI_CLOUD_APP_ID`) and the FastAPI Cloud application environment, which is what the running app
reads (`fastapi deploy` ships code, never configuration). Set `FRONTEND_HOST` there to the app's
public URL, or CORS and every emailed link point at `http://localhost:8000`. Two more settings there
decide whether the deployment is safe and complete:

- **Outgoing mail (`SMTP_*`).** Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (a
  secret), `SMTP_TLS`/`SMTP_SSL` and `EMAILS_FROM_EMAIL` from your mail provider. Without them, staff
  invitations are refused with `503 EMAIL_NOT_CONFIGURED` and password-recovery emails are never
  sent (the page still says one was). Production has none of these set today.
- **Never set `FASTAPI_ENV`.** `FASTAPI_ENV=development` turns the refusal to start with a
  `changethis` secret into a warning, labels logs as `development` and turns Sentry off. It is for local work only;
  production currently has `FASTAPI_ENV=development` and it must be removed.

A local `.env.cloud` is for
your own use, is gitignored and must never be committed. Details: [deployment.md](deployment.md).

## 10. Troubleshooting

- **500s or "relation does not exist" after pulling** - your database is behind the code:
  `cd backend && uv run alembic upgrade head`.
- **Port already in use** (`5432`, `8000`, `5174`, `8025`) - find the owner with
  `lsof -nP -iTCP:8000 -sTCP:LISTEN` and stop it. The dev server uses a fixed port (`strictPort`)
  and fails rather than moving.
- **429 Too Many Requests in e2e runs** - login and signup are limited to 20/min and password
  recovery to 5/min per client address, per backend process. One full run spends 18 sign-ins and 4
  recovery calls, and a run started within a minute of the previous one against the same backend
  first waits out that minute (it prints `Waiting ...s for the previous run's rate-limit window`).
  A `429` therefore means something else is spending the budget, such as a dev session signing in
  repeatedly against the same backend.
- **`{"detail":"Not Found"}` on `http://127.0.0.1:8000/`** - the app is not built: `bun run build`,
  then restart the backend if it started before the first build.
- **`ValidationError` for `SECRET_KEY`, `PROJECT_NAME` or `DATABASE_URL` on start** - `.env` is missing:
  repeat step 2.

## 11. Claude Code cloud (and other fresh cloud containers)

A cloud session starts from a fresh clone with nothing running. One command does what CI does:

```bash
bash scripts/cloud-setup.sh
```

It is idempotent and:

- copies `.env.example` to `.env` if there is none, and replaces each `REPLACE_ME` it still finds
  with a strong generated value (never printed); an existing value is never overwritten;
- starts `dockerd` if Docker is installed but not running, pulls the PostgreSQL and Mailpit images
  (retrying, since registries rate-limit) and starts them;
- runs `uv sync` and `scripts/prestart.sh` (migrations and the first superuser);
- runs `bun install`, falling back to `npm install` for the install only if bun's fetch fails behind
  the proxy;
- when the image ships one Chromium under `PLAYWRIGHT_BROWSERS_PATH` and the pinned Playwright
  expects a newer headless-shell revision, points that revision at the installed build (local only;
  never run `playwright install` there).

If Docker Hub answers `429 Too Many Requests`, configure a registry mirror before starting Docker:
`echo '{"registry-mirrors":["https://mirror.gcr.io"]}' | sudo tee /etc/docker/daemon.json`.

**Parallel work.** Give every concurrent worker its own database in the compose PostgreSQL and its
own backend port (`CREATE DATABASE app_e2e_<name>`, `--port 81xx`), and drop them afterwards:
`pytest` deletes every user on teardown and the login rate limit is per backend process.

**Production is not reachable from the container** in every environment, and its secrets never are.
Measure production from GitHub Actions instead: the **Measure Production** workflow runs after each
deploy and on demand (`docs/reference/performance.md`).

### GitHub from a cloud session: REST only

The cloud proxy blocks GitHub's GraphQL endpoint, so `gh pr ...` and `gh issue ...` fail. Use the
REST API through `gh api`:

```bash
REPO=irajput215/clinic-os

# Open a pull request (body from a file)
gh api repos/$REPO/pulls -f title="..." -f head=<branch> -f base=main -F body=@pr.md --jq .html_url

# Checks on a commit
gh api repos/$REPO/commits/<sha>/check-runs --jq '.check_runs[]|[.name,.status,.conclusion]|@tsv'

# Workflow runs on a branch, and the jobs of one run
gh api "repos/$REPO/actions/runs?branch=<branch>" --jq '.workflow_runs[]|[.id,.name,.conclusion]|@tsv'
gh api repos/$REPO/actions/runs/<run-id>/jobs --jq '.jobs[]|[.id,.name,.conclusion]|@tsv'

# Merge a pull request once every check is green
gh api -X PUT repos/$REPO/pulls/<number>/merge -f merge_method=merge

# After the merge: the Deploy run for main
gh api "repos/$REPO/actions/workflows/deploy.yml/runs?branch=main&per_page=1" \
  --jq '.workflow_runs[0]|[.head_sha,.status,.conclusion]|@tsv'

# Start Measure Production by hand
gh api -X POST repos/$REPO/actions/workflows/measure-production.yml/dispatches -f ref=main
```

`gh run view <id> --log-failed` needs the job-log host, which some proxies also block; read job logs
through the GitHub connector instead when it does. Repository secrets cannot be listed or set from
the container: that is the owner's job in the repository settings.
