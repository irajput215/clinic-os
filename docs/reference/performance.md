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

## 3. Hypotheses

| # | Hypothesis | How it is tested | Verdict |
|---|---|---|---|
| H1 | Each request opens a new TLS + SCRAM connection (short-lived instances, or several workers with empty pools), so pooled connections are never reused | `db-connect` and `db_connections_opened` / `db_connections_reused` per request; `instance_uptime_s` in the log | pending production numbers |
| H2 | `pool_pre_ping` adds a round trip to every checkout | local statement log: one `;` ping per checkout | **confirmed** (one round trip per checkout, three per Today request) |
| H3 | Pooler vs direct endpoint, `sslmode` / channel binding add round trips to a connect | `db-connect` per new connection, compared across hosts | pending production numbers |
| H4 | Neon autosuspend adds 1-2 s to the first request after about five idle minutes | first readiness call after idle vs warm | pending production numbers |
| H5 | App and database are not co-located, so each round trip is long | `db` / `db-rt` on warm readiness (no connect) gives the per-round-trip latency | pending production numbers |
