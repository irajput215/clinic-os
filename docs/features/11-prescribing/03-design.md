---
doc_id: OZ-FEAT-11-DESIGN
title: "Prescribing — design"
owner: Clinical Safety Officer + CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-11
phase: 03-phase-3-eprescribing
gate: [4, 5]
source:
  - clinic-os-secure-by-design/09-prescription-safety-gate.md §2, §6, §9
  - clinic-os-secure-by-design/21-technical-design.md §7, §9
  - clinic-os-secure-by-design/04-database-erd.md §3.8, §8, §9
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

Python 3.14 · FastAPI · Pydantic v2 · SQLModel · psycopg3 · Alembic. The workflow owns its tables and does not import another module's internals (`21-technical-design.md` §8).

## Table: `prescriptions`

| Column | Type | Constraints / notes |
| --- | --- | --- |
| `id` | uuid | PK, server-generated |
| `tenant_id` | uuid | NOT NULL; RLS key; never from the request body |
| `patient_id` | uuid | NOT NULL; composite FK `(tenant_id, patient_id)` → `patients` |
| `prescriber_id` | uuid | NOT NULL; FK `users(id)`; the prescriber of record |
| `approval_id` | uuid | NULL; composite FK `(tenant_id, approval_id)`; **required on dispatch** |
| `medicine_name`, `dosage_form` | text | NOT NULL; form must match the approval grain |
| `dose_instruction` | text | NOT NULL |
| `quantity` | numeric(10,2) | NOT NULL; `CHECK (quantity > 0)` |
| `repeats` | smallint | NOT NULL DEFAULT 0; `CHECK (repeats BETWEEN 0 AND 12)` |
| `schedule8_flag` | boolean | NOT NULL DEFAULT false |
| `tga_category`, `service_date` | text, date | NOT NULL; category must match the grain; date validity is evaluated against |
| `state` | text | NOT NULL; `CHECK` in the closed set below |
| `supersedes_id` | uuid | NULL; self-FK for an addendum |
| `signed_at`, `signed_by` | timestamptz, uuid | NULL until signed; identity-bound |
| `cancel_reason_code` | text | NULL; code, not free text |
| `created_at`, `updated_at` | timestamptz | NOT NULL |

Indexes: `(tenant_id, patient_id, created_at DESC)`, `(tenant_id, state)` partial non-terminal, `(tenant_id, approval_id)`.

## Tables: `prescription_events` and `prescription_state_history`

| Column | Type | Constraints / notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `tenant_id` | uuid | NOT NULL; RLS key |
| `prescription_id` | uuid | NOT NULL; composite FK `(tenant_id, prescription_id)` |
| `event_type` / `from_state`, `to_state` | text | NOT NULL; controlled vocabulary |
| `actor_id` | uuid | NULL; `SYSTEM` for jobs |
| `reason_code`, `detail` | text, jsonb | NULL; controlled vocabulary; `detail` redacted — state change and field **names** only |
| `occurred_at` | timestamptz | NOT NULL; server clock |

`prescription_events` is the audit-facing event log (`04-database-erd.md` §3.8); `prescription_state_history`
is the append-only transition ledger (`21-technical-design.md` §8); the source-name divergence is recorded in the Open items below.

## The state machine

```
DRAFT ──sign──> SIGNED ──gate blocks──> BLOCKED ──approval obtained──> QUEUED
                  │                       (retry, no re-sign)             │
                  └──gate passes──> QUEUED ──> DISPATCHED ──reversal──> REVERSED
                                       │            └──provider error──> FAILED
                  unknown outcome ──> REQUIRES_RECONCILIATION   DRAFT/SIGNED ──cancel──> CANCELLED
```

- Allowed: `DRAFT→{SIGNED, CANCELLED}`, `SIGNED→{QUEUED, BLOCKED, CANCELLED}`,
  `BLOCKED→{QUEUED, CANCELLED}`, `QUEUED→{DISPATCHED, FAILED, REQUIRES_RECONCILIATION}`,
  `FAILED→{QUEUED, CANCELLED}`, `REQUIRES_RECONCILIATION→{DISPATCHED, FAILED}`,
  `DISPATCHED→REVERSED`. Everything else is `409 INVALID_STATE_TRANSITION`.
- **Transitions are server-managed.** A client-supplied target state is not a parameter of any route and is
  rejected as an unknown field (`422`) by the strict Pydantic schema.
- **`SIGNED` is immutable — a correction is an addendum, never an edit.** An addendum inserts a new
  `prescriptions` row with `supersedes_id` set; the original row and its signature are never updated.
- The transition **`SIGNED → QUEUED` invokes the FEAT-10 gate**. This module calls the gate and records the
  resulting transition; it contains no approval lookup and no reason-code logic of its own.
- A **`BLOCKED`** prescription may be re-submitted **without re-signing** — the clinical decision has not
  changed; obtaining the approval is the change.

## Database privileges

The application connects as non-owner role `clinos_app`, which has no `BYPASSRLS`.

```sql
GRANT SELECT, INSERT, UPDATE ON prescriptions TO clinos_app;      -- UPDATE only for non-signed lifecycle
REVOKE DELETE, TRUNCATE ON prescriptions FROM clinos_app;
GRANT SELECT, INSERT ON prescription_events TO clinos_app;         -- append-only
REVOKE UPDATE, DELETE, TRUNCATE ON prescription_events FROM clinos_app;
GRANT SELECT, INSERT ON prescription_state_history TO clinos_app;  -- append-only
REVOKE UPDATE, DELETE, TRUNCATE ON prescription_state_history FROM clinos_app;
```

A `BEFORE UPDATE` fail-closed trigger, `trg_prescriptions_lock_signed`, raises `SIGNED_IS_IMMUTABLE` on any
payload, signature or grain change after `SIGNED`. Mutating an append-only table raises `42501`.

## Row-Level Security

- `ENABLE` and `FORCE ROW LEVEL SECURITY` on all three tables; the app role is not the owner and has no `BYPASSRLS`.
- Policy, `AS RESTRICTIVE`, `FOR ALL TO clinos_app`: `USING` and `WITH CHECK` both
  `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` — an unset tenant matches **no** row.
- Context is set with `SET LOCAL` inside the transaction, never per pooled connection.

## Endpoints

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/v1/prescriptions` | `prescription:read` | cursor-paginated; tenant-scoped |
| `POST /api/v1/prescriptions` | `prescription:stage` | creates `DRAFT`; idempotency key |
| `GET /api/v1/prescriptions/{id}` | `prescription:read` | exposes advisory `approval_status`; `404` cross-tenant |
| `PATCH /api/v1/prescriptions/{id}` | `prescription:stage` | `DRAFT` only; `409` otherwise |
| `POST /api/v1/prescriptions/{id}/sign` | `prescription:sign` | step-up; prescriber of record |
| `POST /api/v1/prescriptions/{id}/addendum` | `prescription:sign` | new version; original unchanged |
| `POST /api/v1/prescriptions/{id}/dispatch` | `prescription:dispatch` | the FEAT-10 gate route; step-up |
| `POST /api/v1/prescriptions/{id}/cancel` | `prescription:cancel` | reason code required |
| `GET /api/v1/prescriptions/{id}/history` | `prescription:read` | ordered transitions |

No `DELETE` endpoint. Per `21-technical-design.md` §7 every route declares auth, permission, tenant scope,
ownership, input/output schema, audit event, rate limit and error behaviour; error envelope
`{"error": {"code", "message", "request_id", "details"}}`.

## Deny-by-default request path

1. Authenticate the session; deny if missing or expired, and require fresh step-up on `sign` and `dispatch`.
2. Resolve `tenant_id` from the session; `SET LOCAL app.tenant_id` for the transaction. Never from the body.
3. Check the route permission; deny if not held.
4. Record the decision, including a refusal, before returning it.
5. Validate the body against a strict schema; unknown fields are rejected, so a supplied `state` or `tenant_id` is refused.
6. Resolve the resource inside the RLS-scoped transaction; a cross-tenant or unknown id returns `404`.
7. Compute the next state server-side; reject an illegal transition with `409`.

## Failure behaviour

Any error resolving tenant, authorisation or the resource is treated as **deny**; an audit write failure
aborts the operation. Errors return a generic message with a request id, no stack trace and no clinical content.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Column-name divergence: doc 04 §3.8 names `dosage`, `frequency`, `route`, `duration`; doc 12 §3 names `dose_instruction`, `quantity`, `repeats`, `schedule8_flag`. This design adopts the doc 12 §3 names | CTO + CSO | OPEN |
| Doc 20 §7 also names `prescription_items`, `prescription_signatures`, `prescription_idempotency_keys`; this MVP folds signature and idempotency into `prescriptions` | CTO | OPEN |
| The trigger name and exact locked-column set are provisional until Gate 2 review | Security Lead | OPEN |
