---
doc_id: OZ-RUNBOOK-CLINOS-APP
title: "Runbook: run production as clinos_app"
owner: Head of Platform
status: DRAFT — for review
last_reviewed: 2026-11-21
next_review: 2026-12-21
classification: RESTRICTED
---

# Runbook: run production as `clinos_app`

**Why.** Production connects as `neondb_owner`, which has `BYPASSRLS`. Every row-level security policy
in the schema is therefore ignored, and only the application's own `WHERE tenant_id = …` predicates
keep one clinic's data from another's. This is the first go-live blocker in
[`docs3/roadmap.md`](../../docs3/roadmap.md) (`docs/progress.md` P5). After this change the database
itself refuses a cross-tenant row, a hard delete or an approval written by the pipeline, even if the
code has a bug.

**What makes it safe to do now** (2026-11-21):

* The whole backend suite passes with every API request served as `clinos_app`
  (`cd backend && uv run pytest --as-app-role`; 1082 passed, 52 statement-counting tests skipped).
  The only `permission denied` errors in that run are tests that expect them.
* Migrations already use `MIGRATION_DATABASE_URL` when it is set (`backend/app/alembic/env.py`), so
  they can keep running as the owner while the application runs as `clinos_app`.
* `clinos_app` is already a member of `clinos_extractor`, so the TGA inbox keeps working.
* On start-up the app now logs `Database login bypasses row-level security…` when the login ignores
  RLS, so you can see which state production is in.

## Before you start

* Access to the Neon console (SQL editor) for the production project, as `neondb_owner`.
* Write access to the repository's Actions secrets.
* `fastapi` CLI logged in (`uv run fastapi login`) with access to the production app.
* About 15 minutes. The switch itself is one environment change and one redeploy.

Never paste a password into a chat, a ticket, a commit or a log. Each value below goes straight from
your terminal into the secret store it belongs to.

## Steps

### 1. Give `clinos_app` a login

Generate a password locally:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

In the Neon SQL editor, connected to the production database as `neondb_owner`:

```sql
ALTER ROLE clinos_app WITH LOGIN PASSWORD '<the generated password>';
```

Check it. Expect `t | f | f | t`:

```sql
SELECT rolcanlogin, rolbypassrls, rolsuper,
       pg_has_role('clinos_app', 'clinos_extractor', 'MEMBER') AS extractor_member
FROM pg_roles WHERE rolname = 'clinos_app';
```

If `extractor_member` is `f`, the database has not run migration `9c4e2b7d1a05`. Deploy `main` first.

Neon may refuse a password it considers too weak; the generated one is 256 bits. If Neon's console
lists roles, `clinos_app` appears there once it can log in. Manage its password from SQL, as above,
so that the migrations' role attributes stay as they are.

### 2. Build the new connection string

Copy the current production `DATABASE_URL` and change only the user and password:

```
postgresql://clinos_app:<password>@<same host>/<same database>?sslmode=require
```

Keep the same host. If the current URL uses Neon's pooled host (`-pooler`), keep that too:
`SET LOCAL ROLE`, which the TGA inbox uses, works in transaction pooling mode.

Confirm it points at the same database (this prints hostnames only):

```bash
cd backend
uv run fastapi cloud env get DATABASE_URL --json --app-id "$APP_ID" > /tmp/deployed.json
DATABASE_URL="<the new URL>" uv run python scripts/check_database_target.py /tmp/deployed.json
# exit 0: same database. Anything else: stop.
rm /tmp/deployed.json
```

### 3. Keep migrations on the owner

In GitHub, go to **Settings → Secrets and variables → Actions**:

1. Create **`MIGRATION_DATABASE_URL`** with the **current** owner URL, the value `DATABASE_URL` holds
   today. Do this first.
2. Then change **`DATABASE_URL`** to the new `clinos_app` URL.

The Deploy workflow's "Prepare database" step runs the migrations with `MIGRATION_DATABASE_URL` and
`initial_data.py` with `DATABASE_URL`. `clinos_app` may read and create the first superuser account,
which is all `initial_data.py` does unless `SEED_DEMO_TENANT` is on.

### 4. Switch the running application

```bash
uv run fastapi cloud env set DATABASE_URL "<the new URL>" --app-id "$APP_ID"
```

Check the exact argument form with `uv run fastapi cloud env set --help` first; the `get` form above is
the one this repository already documents. Leave `MIGRATION_DATABASE_URL` unset in FastAPI Cloud: the
running app never migrates.

### 5. Redeploy and verify

Run the **Deploy** workflow from the Actions tab (or push to `main`). Its readiness gate fails the job
if the app cannot serve.

Then check, in this order:

1. The deploy job is green, and the readiness probe answers.
2. In the app's logs, start-up **no longer** shows `Database login bypasses row-level security`.
3. In the Neon SQL editor, the app's sessions are `clinos_app`:

   ```sql
   SELECT usename, count(*) FROM pg_stat_activity
   WHERE datname = current_database() GROUP BY usename;
   ```

4. Sign in, open the patients list, a patient record, the approvals register, the script queue and
   the TGA inbox. Each should behave exactly as before.

### 6. Roll back if anything is wrong

The change is two values. To undo it:

```bash
uv run fastapi cloud env set DATABASE_URL "<the owner URL>" --app-id "$APP_ID"
```

Set the GitHub `DATABASE_URL` secret back to the owner URL, and redeploy. Optionally remove the login
again with `ALTER ROLE clinos_app NOLOGIN;`. No data changes in either direction.

## After the switch

* Record the date in `docs/progress.md` (P5) and in `docs3/roadmap.md` (go-live blockers).
* Rotate the `clinos_app` password with step 1's `ALTER ROLE`, then steps 3.2, 4 and 5. Record who owns
  the credential and how often it rotates (`docs/reference/control-matrix.md`, secrets management).
* CI runs `pytest --as-app-role` in the backend test job on `testing` and `prod` (owner-approved
  2026-11-22), so a query the app role cannot run fails CI rather than production.
