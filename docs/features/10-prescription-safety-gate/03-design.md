---
doc_id: OZ-FEAT-10-DESIGN
title: "Prescription safety gate — design"
owner: Clinical Safety Officer + CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-10
phase: 03-phase-3-eprescribing
gate: [4, 6]
source:
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/21-technical-design.md
repo_docs:
  - 01-requirements.md
  - 05-data-and-audit.md
---

# Design

## The enforcement boundary

```
 FRONTEND (untrusted)                    BACKEND (the only boundary)
 disables the Dispatch control           POST /api/v1/prescriptions/{id}/dispatch
 when no approval is cached,             -> evaluateDispatchGate(ctx)
 and shows                              -> the ONLY caller of the provider client
 "Active TGA Approval Required"
```

A hand-crafted request that never rendered a button reaches the same gate and is refused the same way.

## The gate pipeline — fixed order of eleven steps

| # | Step | Evaluates | Failure | HTTP | Audit event | User message |
|:---:|---|---|---|:---:|---|---|
| 1 | Authentication | Session valid, MFA satisfied, step-up fresh | not attempted | `401` | `auth.step_up_failed` | "Your session has expired. Sign in again." |
| 2 | Authorisation | `prescription:dispatch` held; actor is prescriber of record or authorised dispatcher | not attempted | `403` | `AUTHZ_DENIED` | "You do not have permission to dispatch this prescription." |
| 3 | Patient access | Active care relationship, same tenant | not attempted | `403` | `AUTHZ_CARE_RELATIONSHIP_DENIED` | "You are not recorded as treating this patient." |
| 4 | Medication validation | Medicine active, structured dose present, unit bounded, no hard-stop interaction | blocked | `422` | `prescription.dispatch_blocked` | "`<field>` is incomplete or invalid." |
| 5 | TGA category determination | Exactly one category resolves | blocked | `422` | `prescription.dispatch_blocked` | "No TGA category could be determined." |
| 6 | Dosage form determination | Exactly one form resolves from the controlled vocabulary | blocked | `422` | `prescription.dispatch_blocked` | "The dosage form could not be determined." |
| **7** | **Approval lookup** | A record exists at `patient_id + category + dosage_form` in the same tenant | blocked | `422` | `prescription.dispatch_blocked` | **"Active TGA Approval Required"** |
| **8** | **Approval validity** | State `ACTIVE` and the window covers `date_of_service` in `Australia/Sydney` | blocked | `422` | `prescription.dispatch_blocked` | **"Active TGA Approval Required"** |
| 9 | Clinical / business validation | `SIGNED`, not already dispatched, quantity in bounds, RPM satisfied where applicable | blocked | `409`/`422` | `prescription.dispatch_blocked` | Per reason code |
| 10 | Audit event | Writes `prescription.dispatch`, `result = SUCCESS` | **rolls the transaction back** | `500` | `prescription.dispatch_blocked`, reason `AUDIT_WRITE_FAILED` | "Could not dispatch safely. Try again." |
| 11 | Provider dispatch | Calls the adapter with an idempotency key and a deadline | `FAILED` or `REQUIRES_RECONCILIATION` | `502`/`202` | `prescription.dispatch_failed` | "Not confirmed. Queued for reconciliation." |

Steps 1–9 are pure and deterministic except the lookups. **Step 10 fails closed: an unauditable dispatch
is not permitted.** Step 11 is the only side effect and happens after the state and audit event commit.

### Reason codes

`block_reason` is a closed vocabulary. The gate never emits free text from a downstream system. The
source expresses the step 7 failures as a `NO_ACTIVE_TGA_APPROVAL_FOR_*` family, which is more precise
than a single code because it names the failing dimension.

`NO_ACTIVE_TGA_APPROVAL_FOR_CATEGORY_AND_DOSAGE_FORM` · `…_FOR_CATEGORY` · `…_FOR_DOSAGE_FORM` ·
`…_FOR_PATIENT` · `APPROVAL_EXPIRED` · `APPROVAL_REVOKED` · `APPROVAL_PENDING_VERIFICATION` ·
`APPROVAL_REJECTED` · `APPROVAL_SUPERSEDED` · `ALREADY_DISPATCHED` · `STATE_INVALID` ·
`AUDIT_WRITE_FAILED`. Steps 7–8 also return the stable machine code `approval_not_active`.

Adding or renaming a reason code is a **clinical safety parameter**: CSO approval plus a Gate 4 re-run.

## Prescription state machine

```
DRAFT ──sign──> SIGNED ──gate blocks──> BLOCKED ──approval obtained, retry──┐
                  │                                                        │
                  └──gate passes──> QUEUED ──> DISPATCHED   <──────────────┘
                                       │            │
                                       │            └──reversal──> REVERSED
                                       └──provider error──> FAILED
                  any unknown outcome ──> REQUIRES_RECONCILIATION
                  DRAFT ──discard──> CANCELLED
```

- `SIGNED` is immutable; a correction is an addendum, never an edit.
- The gate runs on the transition `SIGNED → QUEUED`.
- A `BLOCKED` prescription may be re-submitted **without re-signing** — obtaining the approval is the
  change.
- Transitions are server-managed; a client-supplied target state is rejected as an unknown field.

## `dispatch_attempts`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | server-generated |
| `tenant_id` | uuid NOT NULL | RLS key |
| `prescription_id` | uuid NOT NULL | FK |
| `idempotency_key` | text NOT NULL | `sha256(tenant_id \|\| prescription_id \|\| intent_seq)`, server-computed |
| `attempt_seq` | integer NOT NULL | increments only on a **new clinical intent**, never on a transport retry |
| `state` | text NOT NULL | `QUEUED` \| `DISPATCHED` \| `FAILED` \| `REQUIRES_RECONCILIATION` |
| `provider` | text NOT NULL | default `PARCHMENT` |
| `provider_reference` | text NULL | external rail reference |
| `provider_event_id` | text NULL | webhook deduplication key |
| `request_payload_hash` | text NOT NULL | proof of identity, **never the payload** |
| `error_class`, `outcome_class` | text NULL | `CONFIRMED` \| `REJECTED` \| `UNKNOWN` |
| `latency_ms` | integer NULL | |
| `requested_by`, `requested_at`, `resolved_at` | | |

`UNIQUE (tenant_id, idempotency_key)` · `UNIQUE (tenant_id, prescription_id, attempt_seq)`.
**Bounded retry:** at most 4 attempts, exponential backoff with jitter (1s, 4s, 16s, 64s) for transient
failures only. A validation failure is never retried.

## Reconciliation

Selects rows in `REQUIRES_RECONCILIATION` or `QUEUED` older than 60 seconds, plus prescriptions
non-terminal longer than the configured threshold (default 15 minutes). Queries the provider by
`provider_reference` **and** by idempotency key, resolving **both directions**. Every resolution writes
an event with `reason = RECONCILED` and the original `correlation_id`. Unresolved after 24 hours
escalates to the Clinical Safety Officer and appears on the non-terminal dashboard. **Runs with explicit
tenant context and fails loudly without it.**

## Database privileges

```sql
GRANT SELECT, INSERT ON dispatch_attempts TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON dispatch_attempts FROM clinos_app;
GRANT SELECT, INSERT ON prescription_events TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON prescription_events FROM clinos_app;
```

The app role is not the table owner and has no `BYPASSRLS`. Terminal outcome columns on
`dispatch_attempts` are written by the worker role, not the request role.

## No-bypass rule

1. `POST /api/v1/prescriptions/{id}/dispatch` is the only route that calls the provider client.
2. The provider client is imported only by the gate's dispatch module. A repository lint rule fails the
   build on any other import, **including from a test that means to bypass the gate**. Tests inject the
   adapter at the gate constructor.
3. The gate function takes no `skip`, `force` or `override` parameter; a token search for those names in
   the gate module runs in CI.
4. The gate writes its own audit event before returning any decision, including a refusal.
5. A pharmacist-initiated path, if built, calls the **same** gate. It is not a second implementation.
6. Any change to the gate requires Clinical Safety Officer approval and a **Gate 6 re-run**.

## Endpoints

| Method and path | Permission | Notes |
| --- | --- | --- |
| `POST /api/v1/prescriptions/{id}/dispatch` | `prescription:dispatch` | step-up; the only caller of the gate; rate 30/min per session |
| `GET /api/v1/prescriptions/{id}` | `prescription:read` | treating relationship; rate 300/min |
| `POST /api/v1/pharmacy/webhooks/{provider}` | signature-verified | tenant resolved from the verified payload, never a path or header |

## Failure behaviour

Any error resolving tenant, authorisation or the approval lookup is treated as **deny**. Errors return
generic messages with a request id and no stack trace. A missing `app.tenant_id` matches nothing, not
everything.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Provider broker hosting (queue) is unresolved under D-004 | Head of Platform | OPEN |
| `btree_gist` availability on the target PostgreSQL build, needed by FEAT-08 | Head of Platform | OPEN |
