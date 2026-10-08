---
doc_id: OZ-REF-PERFORMANCE
title: Performance - method, measurements and findings
owner: CTO
status: DRAFT - for review
last_reviewed: 2026-10-08
next_review: 2026-11-08
classification: INTERNAL
---

# Performance

ClinicOS serves clinics and patients in Australia. The app runs on FastAPI Cloud and the database on
Neon in `aws-ap-southeast-2` (Sydney). This document records how speed is measured, what was
measured, and which explanations the numbers confirmed or refuted.

## 1. Method

**Judge speed at the origin, never by an observer's total time.** A request's total time is the
observer's distance to the app plus the app's own time. The owner tests from India, which adds about
0.4-0.8 s per request of travel to Australia; this repository's cloud sessions and GitHub runners are
elsewhere again. None of that is something the app can change, so none of it is a target. The
figures that count are:

| Figure | Where it comes from | Depends on the observer? |
|---|---|---|
| `upstream` | FastAPI Cloud's `x-envoy-upstream-service-time`: time inside the app process | No |
| `app` | `Server-Timing` sent by the app: edge middleware to response start | No |
| `db` | `Server-Timing`: time waiting on the database (statements, `BEGIN`, `COMMIT`, `ROLLBACK`) | No |
| `db-connect` | `Server-Timing`: time opening new database connections (TCP, TLS, authentication) | No |
| `db-rt` | `Server-Timing`: database round trips, a count | No |
| asset weight and caching | build output, `cache-control`, `content-encoding` | No |

An Australian user near a Sydney or Melbourne edge adds about 30 ms of round trip to the origin
figures; the frontend performance checks simulate exactly that (Fast 4G, ~30 ms RTT).

**Instrumentation** (`backend/app/core/server_timing.py`). Every psycopg operation goes through
`Connection.wait`; the app opens its connections as a subclass that times that call and counts a
round trip whenever the call had to wait on the socket, plus one for psycopg's implicit `BEGIN`.
Connection opens are timed through SQLAlchemy's `do_connect` hook, and pool checkouts are counted,
so each request knows whether it reused a pooled connection. The request log line carries the same
figures plus `instance_id`, `instance_uptime_s` and `instance_requests`, which show how long an
instance lives and whether its pool is reused.

What never leaves the process: SQL text, parameters, identifiers, rows, error messages. The header is
sent only on the readiness probe and on responses to a verified session; an anonymous route such as
password recovery never carries it, because a round-trip count there would reveal whether an email
address has an account. `SERVER_TIMING_ENABLED` turns the header off; it is on by default and in
production.

**Production runs** come from `.github/workflows/measure-production.yml`, which runs
`scripts/measure-production.py` after every deploy and on demand. It reads production only. With the
optional `PROBE_EMAIL` / `PROBE_PASSWORD` repository secrets it also signs in as one probe clinic
("Performance probe (synthetic, no patients)", registered through the public signup on first use) and
measures the authenticated reads; it never touches another tenant.

**Round trips are pinned by tests**, per hot endpoint, so a change that adds a round trip fails CI
rather than production. The count is deterministic and location independent; multiply it by the
measured per-round-trip latency to get the database share of a request anywhere.

## 2. Baseline (2026-10-08, before any change)

### Production, as reported by the owner

| Request | upstream |
|---|---|
| `GET /api/v1/utils/health-check/` (no database) | 2 ms |
| `GET /api/v1/health/ready/` (pooled connect + `SELECT 1`), warm | 790-870 ms, every time |
| `GET /api/v1/health/ready/` right after Neon resumed | 1.8 s |

Configuration at the time: `create_engine(DATABASE_URL, pool_pre_ping=True)` (default `QueuePool`);
Neon autoscaling 0.25-2 CU, `suspend_timeout_seconds` 0 (the plan default, about five minutes); the
Neon project is on the free plan; the endpoint offers a pooled (`-pooler`) host in transaction mode.

### Round trips per request (local, deterministic)

Measured against the local PostgreSQL with the instrumentation above, before any change:

| Request | db round trips | Where they go |
|---|---|---|
| `GET /health/ready/` | 4 | pre-ping, `BEGIN`, `SELECT 1`, `ROLLBACK` |
| `GET /users/me` | 4 | pre-ping, `BEGIN`, user, tenant status (+ `ROLLBACK` at return) |
| `GET /users/me/permissions` | 15 | |
| `GET /dashboard/today` | 35 | 3 connection checkouts, each with a pre-ping; 2 tenant transactions with an implicit `BEGIN` and three separate `set_config` statements each; 5 queries to resolve the permission set; 2 clock queries; the audit chain |
| `GET /patients` | 16 | |
| `GET /tga-approvals` | 29 | |
| `GET /prescriptions` | 21 | |
| `GET /appointments` (one week) | 21 | |
| `GET /users/staff` | 24 | |

Every round trip costs the full app-to-database latency. At 1 ms that is invisible; at the latency
the readiness probe implies in production it dominates every screen.

### Production, measured at the origin (Measure Production, 2026-10-08 11:36 UTC, 3A deployed)

`scripts/measure-production.py`, 20 samples each, median / p90 / max, from a GitHub runner. The
`upstream` and `Server-Timing` columns do not depend on where the runner is.

| Request | upstream ms | app ms | db ms | db-connect ms | db round trips |
|---|---|---|---|---|---|
| readiness, first call after idle | 3932 | 3930 | 2597 | 1330 | 12 |
| liveness (no database) | 2 / 3 / 3 | - | - | - | - |
| readiness, sequential | 867 / 871 / 873 | 865 / 866 / 870 | 864 / 865 / 869 | 0 / 0 / 0 | 4 / 4 / 4 |
| readiness, 5 concurrent | 878 / 2012 / 2054 | 875 / 2008 / 2052 | 867 / 888 / 892 | 0 / 1324 / 1348 | 4 / 4 / 4 |

Static files at the same time: hashed `/assets/*` answered `cache-control: public, max-age=14400`,
the app's HTML had no `cache-control`, and two small chunks were sent uncompressed.

**What these numbers say.** Warm readiness spends 864 ms on four round trips with **no** connection
opened: about **216 ms per round trip** between the app and the database. A `SELECT 1` on Neon
takes well under a millisecond, so this is network distance, not database work. A new connection
costs 1.33 s (about six round trips: TCP, TLS, startup and SCRAM). Liveness answers a GitHub-hosted
runner in North America in about 120 ms including a fresh TLS handshake, which puts the app's origin
in North America too. **The app and the database are not co-located**: the database is in Sydney
and the app is not.

## 3. Hypotheses

| # | Hypothesis | How it was tested | Verdict |
|---|---|---|---|
| H1 | Each request opens a new TLS + SCRAM connection, so pooled connections are never reused | `db-connect`, `db_connections_opened` / `db_connections_reused`, 20 sequential readiness calls | **Refuted.** `db-connect` is 0 on every warm call: the instance stays up and its pool is reused. New connections appear only under concurrency beyond the pool's idle connections (5 concurrent: p90 `db-connect` 1324 ms) and after idle |
| H2 | `pool_pre_ping` adds a round trip to every checkout | local statement log: one `;` ping per checkout; readiness 4 round trips = ping, `BEGIN`, `SELECT 1`, `ROLLBACK` | **Confirmed.** One round trip per checkout, three per Today request, each ~216 ms in production |
| H3 | Pooler vs direct endpoint, `sslmode` / channel binding add round trips to a connect | `db-connect` per new connection | **Partly confirmed, minor.** A connect is ~6 round trips (1.33 s) whatever the endpoint, because the cost is distance. The pooled (`-pooler`) host would not shorten it. Since warm requests reuse connections, the connect cost matters at start-up, after idle and under bursts; it is addressed by warming the pool and keeping connections alive, not by changing hosts |
| H4 | Neon autosuspend adds 1-2 s to the first request after about five idle minutes | first readiness call after idle | **Confirmed, and worse:** 2.6 s and 3.9 s observed (compute start plus a new connection at this distance). The Free plan cannot disable scale to zero (Neon API: HTTP 412 "modifying the suspend interval is not permitted on this account") |
| H5 | App and database are not co-located | `db` / `db-rt` on warm readiness | **Confirmed: ~216 ms per round trip.** This is the dominant cost of every screen, and only the owner can remove it (section 5) |

## 4. What was changed (3B)

Every round trip costs ~216 ms until the app and the database share a region, so the request path
was rebuilt around round trips:

| Change | Where | Round trips saved |
|---|---|---|
| No `pool_pre_ping`; a checkout discards a connection the server closed by checking its socket (no network) | `app/core/db.py` `_refuse_dead_connection` | 1 per checkout |
| `pool_recycle` 240 s (inside Neon's 5-minute suspend), TCP keepalives, two connections warmed at start-up | `app/core/db.py`, `app/main.py` | the connect (~6) on the first requests after a deploy |
| The session prelude (account, organisation status, tenant context resolved by the database from the account row, grants, `COMMIT`) is one pipelined flight | `app/api/deps.py` `get_session_account` | from 3 (auth) + 11 (actor) to 1 |
| `tenant_transaction` sends `BEGIN` and one `set_config` statement for tenant, actor and request in the same flight as the transaction's first statement | `app/core/db.py` `_DeferredContext` | from 4 to 0 per tenant transaction |
| The audit chain's lock and head read travel in one flight (still two statements, so the head is read after the lock is held) | `app/modules/audit/service.py` `record` | 2 per audited event |
| Permissions and role codes in one query | `app/modules/users_roles/service.py` | 4 per actor |
| Readiness outside a transaction | `app/core/health.py` | 2 |

Recovery from a dropped connection is proven by `tests/core/test_pool_and_pipeline.py`, which kills
pooled connections with `pg_terminate_backend` and requires the next request to succeed (it fails
with `OperationalError` when the checkout check is removed). Tenant isolation over a shared pooled
connection, including a failed first statement and an empty transaction, is proven in the same file;
`SET LOCAL` semantics are unchanged and no session-level `SET` exists. Round trips are pinned per
hot endpoint in `tests/performance/test_round_trips.py`.

## 5. Owner actions

1. **Co-locate the app and the database (the decisive fix).** Run the FastAPI Cloud app in an
   Australian region next to Neon `aws-ap-southeast-2` (Sydney). This removes ~216 ms from every
   round trip; nothing in code can. If FastAPI Cloud cannot run the app in Australia, the
   alternatives are hosting the app elsewhere in Sydney, or moving the database next to the app,
   which would move health information offshore and needs a privacy decision first (APP 8,
   **REQUIRES LEGAL/REGULATORY VALIDATION**). Note that today the app already processes health
   information in North America on every request, which is itself an APP 8 question for the owner.
2. **Neon scale to zero.** The Free plan suspends after 5 minutes and cannot be changed. On the
   Launch plan scale to zero can be disabled; an always-on 0.25 CU compute is
   0.25 CU x ~730 h = ~182.5 CU-hours a month, at $0.106 per CU-hour about **US$19.35 a month**
   (plus storage at $0.35/GB-month), more when autoscaling above 0.25 CU. Neon console: Project
   `clinic-os` > Branches > main > Compute > Edit > Scale to zero: off.
3. **Probe account for authenticated production timing** (optional). Add repository secrets
   `PROBE_EMAIL` and `PROBE_PASSWORD` (a new address and a strong password); Measure Production then
   registers one clinic named "Performance probe (synthetic, no patients)" on first use and times the
   authenticated reads after every deploy.
4. **`DATABASE_URL` host**: no change needed. The direct (non-pooler) host is fine: warm requests reuse
   pooled connections, and transaction-scoped context works on either host. If the owner switches to
   the pooled host for connection limits, the value shape is
   `postgresql://<role>:<password>@ep-blue-truth-a7e0s0il-pooler.ap-southeast-2.aws.neon.tech/<db>?sslmode=require`;
   the app is compatible (every tenant setting is `set_config(..., true)` inside the transaction).
