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
("Performance probe (synthetic, no patients)", registered through the public signup on first use;
since D-008 the owner of `PROBE_EMAIL` opens the emailed link once, and until then the report says
so and skips the authenticated reads) and
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

### The database itself (Neon, read-only inspection, 2026-10-08)

- **Size**: every user table together is 1.8 MB; the largest index is 16 kB. Query execution is not
  where the time goes: a statement runs in well under a millisecond, the round trip around it costs
  ~216 ms.
- **Buffer cache hit ratio** (`pg_statio_user_tables`): 95.9% for tables, 90.0% for indexes, on a
  compute that suspends after five idle minutes and restarts cold.
- **Sequential scans** dominate (`user` 377, `permissions` 169, `role_permissions` 157): at this size
  the planner prefers them and is right to. The indexes reported "unused" (patient name keys, audit
  partitions) are unused because there is almost no data yet, not because they are wrong; none is
  dropped.
- **Slow-query statistics are not available**: `pg_stat_statements` and the `neon` extension are not
  installed on `neondb`. Installing them writes to the production database, so it is listed as an
  owner action (section 5) rather than done here.
- Query plans for the hot reads were checked against the local seeded database instead: each hot
  read is now one or two statements per flight, all on indexed tenant keys
  (`tests/performance/test_round_trips.py` pins the counts).

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
| TCP keepalives; the whole pool (five connections) opened together at start-up; `pool_recycle` one hour, as a backstop only (the socket check catches closed connections at any age) | `app/core/db.py`, `app/main.py` | the connect (~6, 1.2 s) on the first requests after a deploy, on the first burst of concurrent requests, and every few minutes per connection that a short recycle would have cost |
| The session prelude (account, organisation status, tenant context resolved by the database from the account row, grants, `COMMIT`) is one pipelined flight | `app/api/deps.py` `get_session_account` | from 3 (auth) + 11 (actor) to 1 |
| `tenant_transaction` sends `BEGIN` and one `set_config` statement for tenant, actor and request in the same flight as the transaction's first statement | `app/core/db.py` `_DeferredContext` | from 4 to 0 per tenant transaction |
| The audit chain's lock and head read travel in one flight (still two statements, so the head is read after the lock is held) | `app/modules/audit/service.py` `record` | 2 per audited event |
| Permissions and role codes in one query | `app/modules/users_roles/service.py` | 4 per actor |
| Readiness outside a transaction | `app/core/health.py` | 2 |

Module work on the same branch then removed per-row lookups and redundant reads:

- `app/core/reads.py` `ReadBatch` queues several SQLAlchemy selects and sends them in one flight,
  decoded with each column's own result processor. `Lockstep` runs the Today page's three sections
  through their own modules' facades, with the n-th step of every section sharing one flight.
- The script queue's gate column was one read per prescription; it is one batched read with the
  same decision matrix. The locked `gate.decide` used when signing and dispatching is unchanged.
- Display names are read on the caller's transaction instead of a transaction of their own.
- Today reads its date and day bounds in one statement.
- Lists read their page and total in one statement or one flight.

Round trips per request, local and measured with the instrumentation above. "Seeded" is a clinic
with 3 staff, 25 patients, 15 appointments today, 10 approvals and 10 scripts; the final counts are
pinned in `tests/performance/test_round_trips.py`, each with its breakdown. "Core only" is this
branch after the core changes and before the module work.

| Request | `main` before M3 (empty clinic) | Core only (seeded) | After (seeded) | After (empty) |
|---|---|---|---|---|
| `GET /health/ready/` | 4 | 1 | **1** | **1** |
| `GET /users/me` | 4 | 1 | **1** | **1** |
| `GET /users/me/permissions` | 15 | 1 | **1** | **1** |
| `GET /dashboard/today` | 35 | 32 | **7** | **6** |
| `GET /patients` | 16 | 6 | **5** | **5** |
| `POST /patients/search` | not measured | 6 | **5** | **5** |
| `GET /tga-approvals` | 29 | 9 | **7** | **6** |
| `GET /prescriptions` | 21 | 17 | **4** | **3** |
| `GET /appointments` (one week) | 21 | 4 | **4** | **3** |
| `GET /users/staff` | 24 | 6 | **3** | **3** |
| `GET /roles` | not measured | 11 | **3** | **3** |
| `GET /practitioners` | 22 | 5 | **3** | **3** |

**T1-34 (2026-10-08) audits the reads that were not audited before**, as the patients, clinical-records
and booking documents require (decision D-007): `GET /prescriptions` is now **6** seeded / **5** empty,
`GET /appointments` **6** / **5**, a patient's record `GET /patients/{id}` **5** / **5**, a patient's
bookings and scripts **5** and **6** / **5**: each is the two trips of the audit write, and the care
relationship itself costs none (it is a subquery of the route's first statement). Today stays at 7 / 6
while auditing two more sections, because its three events are one `audit.record_many` (one lock and
head, one multi-row insert). The same change found that `db-rt` did not count psycopg's
`executemany` (it enters pipeline mode through a private method); `TimedConnection` now counts it, and
a test pins it.

**The audit insert travels with `COMMIT` (2026-10-22).** An audited read paid two trips for its
event: the chain lock with its head, then the insert. The insert is now queued with
`app.core.db.send_with_commit` and sent in the same flight as the transaction's `COMMIT`, after every
other change the transaction made, so it costs no trip of its own. It is still inside the
transaction: a failing insert fails the `COMMIT` and the whole operation (INV-4, proven in
`tests/core/test_pool_and_pipeline.py`), and a transaction that raises sends nothing. The chain lock
is held from the head's read to that `COMMIT`, exactly as before, so concurrent writers still cannot
fork a tenant's chain. Every audited request is one trip cheaper, writes included:

| Request (seeded / empty) | With T1-34 | Audit insert with `COMMIT` |
|---|---|---|
| `GET /dashboard/today` | 7 / 6 | **6 / 5** |
| `GET /patients`, `POST /patients/search` | 5 / 5 | **4 / 4** |
| `GET /patients/{id}` | 5 / 5 | **4 / 4** |
| a patient's consult notes, bookings, approvals | 5 / 5 | **4 / 4** |
| a patient's scripts | 6 / 5 | **5 / 4** |
| `GET /tga-approvals` | 7 / 6 | **6 / 5** |
| `GET /prescriptions` | 6 / 5 | **5 / 4** |
| `GET /appointments` (one week) | 6 / 5 | **5 / 4** |

**The audit costs no round trip (2026-10-27).** The remaining trip, the chain lock with the read of
the chain's head, now travels with `COMMIT` too. One flight carries the lock, then one chained
`INSERT ... SELECT` per event, then `COMMIT` (`app.modules.audit.service.record_many`). Each insert
reads the tenant's head itself and derives from it, under the lock:

- `prev_hash`, the head's hash (or the genesis value);
- `timestamp`, the database clock, but at least one microsecond after the head's, so the new row is
  always the newest by the chain's order. A timestamp taken in the application when the event was
  recorded would not be: a writer that records first but commits last would chain after a row that
  is newer than its own, and the next writer would fork the chain. The concurrent-writer test caught
  exactly that in a first version, and a deterministic test now pins it;
- `hash`, computed exactly as `compute_hash` does: the application supplies the event's canonical
  JSON cut at those two values, and the database fills them in and hashes the result with
  `sha256()`. Every chain test recomputes the stored rows in Python, byte for byte.

The statements run in order on the server, so each insert takes its snapshot only once the lock is
held: concurrent writers still cannot fork a chain, and the lock is now held only for that one
flight. A failing insert still fails the `COMMIT` and the operation (INV-4).

| Request (seeded / empty) | Insert with `COMMIT` | Whole audit with `COMMIT` |
|---|---|---|
| `GET /dashboard/today` | 6 / 5 | **5 / 4** |
| `GET /patients`, `POST /patients/search` | 4 / 4 | **3 / 3** |
| `GET /patients/{id}` | 4 / 4 | **3 / 3** |
| a patient's consult notes, bookings, approvals, activity | 4 / 4 | **3 / 3** |
| a patient's scripts | 5 / 4 | **4 / 3** |
| `GET /tga-approvals` | 6 / 5 | **5 / 4** |
| `GET /prescriptions` | 5 / 4 | **4 / 3** |
| `GET /appointments` (one week) | 5 / 4 | **4 / 3** |

Every single-resource read now meets the Milestone 3 budget of three round trips, audited or not.
What remains above three is a list whose second step depends on its first (the names for the
page's ids, on a seeded clinic) and Today, which reads three sections and their lookups.

"Core only" on a seeded clinic shows what the per-row lookups cost once there is data (Today 32,
scripts 17): the empty-clinic counts hid them. A read above three round trips is a read whose second step depends on the first (names for the
page's ids); the audit event costs none.

At ~216 ms per round trip, Today goes from about 7.6 s of database waiting (35 round trips) to about
1.5 s (7); at a co-located ~1 ms it would be single-digit milliseconds either way.

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
   `PROBE_EMAIL` and `PROBE_PASSWORD` (a new address you can read and a strong password); Measure
   Production then registers one clinic named "Performance probe (synthetic, no patients)" on first
   use. Signup is verified by email (D-008) and the script cannot read that mailbox, so open the
   emailed link once ("Confirm and sign in"); from the next run on it times the authenticated reads
   after every deploy.
4. **Query statistics** (optional): enable `pg_stat_statements` on `neondb` from the Neon console SQL
   editor (`CREATE EXTENSION IF NOT EXISTS pg_stat_statements;`) so slow-query statistics exist when
   real traffic arrives. It writes to the production database, so it was not done from here.
5. **`DATABASE_URL` host**: no change needed. The direct (non-pooler) host is fine: warm requests reuse
   pooled connections, and transaction-scoped context works on either host. If the owner switches to
   the pooled host for connection limits, the value shape is
   `postgresql://<role>:<password>@ep-blue-truth-a7e0s0il-pooler.ap-southeast-2.aws.neon.tech/<db>?sslmode=require`;
   the app is compatible (every tenant setting is `set_config(..., true)` inside the transaction).

## 6. Before and after (Milestone 3)

### Production, at the origin

Measure Production after each deploy; `upstream` is FastAPI Cloud's own figure, the others are the
app's `Server-Timing`. Before: 2026-10-08 11:36 UTC (3A deployed, nothing else). After: 14:18 UTC
(#64, #65, #66, #67 and #71 deployed).

| Readiness probe | Before | After |
|---|---|---|
| Warm, sequential: upstream median / p90 | 867 / 871 ms | **212 / 214 ms** |
| Warm: database round trips | 4 | **1** |
| First call after the deploy | 3932 ms (12 round trips, 1330 ms connect) | **202 ms** (1 round trip, pool already warm) |
| Five concurrent: upstream p90 | 2012 ms (new connections, 1324 ms connect) | **420 ms** (no connection opened) |
| Liveness (no database) | 2 ms | 2 ms |

One round trip is now the whole cost of the probe: ~210 ms of network between the app and the
database. The authenticated reads were not measured in production (no probe account, section 5);
their database share follows from the pinned round trips times ~210 ms:

| Request | Round trips before (empty clinic) | Round trips after (seeded clinic) | Database wait before | Database wait after |
|---|---|---|---|---|
| Session (`/users/me`, permissions) | 4 / 15 | 1 / 1 | ~0.8 / 3.2 s | ~0.2 / 0.2 s |
| Today | 35 | 7 | ~7.4 s | ~1.5 s |
| Patients list | 16 | 5 | ~3.4 s | ~1.1 s |
| Approvals register | 29 | 7 | ~6.1 s | ~1.5 s |
| Script queue | 21 | 4 | ~4.4 s | ~0.8 s |
| Calendar week | 21 | 4 | ~4.4 s | ~0.8 s |
| Staff list | 24 | 3 | ~5.0 s | ~0.6 s |

The 150 ms per-call target cannot be met while each round trip costs ~210 ms; with the app next to
the database (owner action 1) these become single-digit to low tens of milliseconds, which the
Server-Timing e2e budgets (readiness < 50 ms, every screen's API calls < 150 ms) already assert
locally on every pull request.

### What the browser downloads

| | Before | After |
|---|---|---|
| Hashed assets `cache-control` | `public, max-age=14400` | `public, max-age=31536000` (the origin also sends `immutable`; the platform edge drops that directive) |
| App HTML `cache-control` | none | `no-cache` |
| JS and CSS encoding | gzip (two chunks uncompressed) | Brotli, precompressed at build |
| Entry chunk (gzip) | 98.3 KB | 44.5 KB (React in its own long-cached chunk) |
| Initial JS (gzip) | 145.2 KB | 145.8 KB (the toaster stays on the first load: deferring it lost toasts) |
| Font files in the build | 44 (1.25 MB) | 16 (latin and latin-ext woff2 only, two preloaded) |
| LCP, sign-in / Today (Fast 4G, ~30 ms RTT, CPU 2x, local served build) | 1104 / 1100 ms | ~700 / ~705 ms |
| First-load requests on Today | sidebar reads ~200 ms after `/users/me` | all start within ~6 ms |
| Layout | horizontal scroll and clipped controls on phones | every screen at 360-1440 px without sideways scroll; 44 px targets below 1024 px; drawer navigation |
