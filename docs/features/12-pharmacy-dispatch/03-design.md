---
doc_id: OZ-FEAT-12-DESIGN
title: "Pharmacy dispatch — design"
owner: Head of Platform
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-12
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md
  - clinic-os-secure-by-design/21-technical-design.md
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

## Table: `pharmacy_dispatches`

| Column | Type | Constraints / notes |
| --- | --- | --- |
| `id` | uuid PK | server-generated |
| `tenant_id` | uuid NOT NULL | RLS key; resolved from the **verified payload** |
| `prescription_id` | uuid NOT NULL | composite FK `(tenant_id, prescription_id)` to `prescriptions` |
| `pharmacy_id` | uuid NOT NULL | receiving pharmacy |
| `provider` | text NOT NULL | e.g. `PARCHMENT` |
| `provider_dispatch_ref` | text NULL | external rail reference |
| `status` | text NOT NULL | `CHECK IN ('RECEIVED','DISPENSED','REJECTED','CANCELLED')` |
| `received_at` | timestamptz NOT NULL | from the verified event, not the local clock |
| `dispensed_at`, `dispensed_by` | timestamptz, uuid NULL | pharmacy confirm; actor recorded |
| `quantity_dispensed` | integer NULL | `CHECK (quantity_dispensed IS NULL OR quantity_dispensed > 0)` |
| `rejection_reason_code` | text NULL | code, never free text; required when `REJECTED` |
| `last_event_seq` | bigint NULL | provider sequence, used for ordering (R6) |

Constraints: `UNIQUE (tenant_id, provider, provider_dispatch_ref)` (R12). A `BEFORE UPDATE` trigger
`trg_pharmacy_dispatch_terminal` refuses any transition out of a terminal state (R6). Indexes:
`(tenant_id, status, received_at DESC)`, `(tenant_id, prescription_id)`.

## Table: `dispatch_attempts` — owned by FEAT-10, not restated

Defined in [03-design.md](../10-prescription-safety-gate/03-design.md) and `09-prescription-safety-gate.md`
§7. FEAT-12 reads `idempotency_key`, `provider_reference` and `provider_event_id` to correlate an event;
an inbound event creates **one receipt**, never a second dispatch.

## Table: `webhook_events` (append-only)

| Column | Type | Constraints / notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `tenant_id` | uuid NOT NULL | RLS key; **quarantine row shape is OPEN-2** |
| `provider` | text NOT NULL | |
| `provider_event_id` | text NOT NULL | the provider's event identifier |
| `event_type` | text NOT NULL | strict schema; unknown types rejected |
| `signature_verified` | boolean NOT NULL | `CHECK (signature_verified)` for any stored row |
| `payload_sha256` | text NOT NULL | proof of identity, **never the payload** |
| `provider_occurred_at`, `provider_seq` | timestamptz, bigint | from the signed payload; ordering source |
| `received_at` | timestamptz NOT NULL DEFAULT now() | |
| `process_result` | text NOT NULL | `CHECK IN ('APPLIED','DUPLICATE','STALE','QUARANTINED','REJECTED')` |
| `correlation_id` | text NULL | provider correlation where present |
| `source_ip` | inet NOT NULL | |

**`UNIQUE (provider, provider_event_id)`** is deliberately global, so a replay cannot be laundered by re-routing to another tenant. Dedupe resolves with `INSERT … ON CONFLICT (provider, provider_event_id) DO NOTHING RETURNING id`; zero rows means duplicate, so the handler returns `200` with no state change and without disclosing the other tenant's row. Indexes: `(tenant_id, received_at DESC)`, `(provider, provider_occurred_at DESC)`.

The **raw body is held in memory for verification only and is never logged**; it is not persisted on the normal path (`10 §7`; retention OPEN-5).

## The webhook contract (normative for this feature)

| # | Rule | Source |
| --- | --- | --- |
| 1 | Verify the signature over the **raw body before parsing**, and require the signed timestamp within a **5-minute** window; otherwise drop `401` | `10 §7` |
| 2 | Dedupe on **`UNIQUE (provider, provider_event_id)`**; a duplicate returns `200` with **no state change** | `10 §7` |
| 3 | Route the tenant from the **verified payload**; never a path parameter or header | `10 §7` |
| 4 | A payload mapping to no tenant is quarantined and alerted, and returns `202` (**OPEN-2**) | `10 §7` |
| 5 | Process idempotently; an out-of-order event never regresses a terminal state | `10 §7` |
| 6 | Body cap **256 KB** ⇒ `413`; `application/json` only | `10 §7` |
| 7 | Return `200` **only after the state change commits**; a failure returns `500` so the provider retries | `10 §7` |
| 8 | Unverified webhooks are dropped `401`, counted, and alerted when the rate exceeds threshold; IP allow-listing is a **second** control only | `10 §7` |
| 9 | `integration.request` on arrival plus the dispatch state effect; never a clinical payload; never fetch a URL from a payload | `10 §7`; `07 §1`; `10 §8` |

## Database privileges

```sql
GRANT SELECT, INSERT ON webhook_events TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON webhook_events FROM clinos_app;   -- append-only by grant
GRANT SELECT, INSERT, UPDATE ON pharmacy_dispatches TO clinos_app;   -- lifecycle, trigger-guarded
REVOKE DELETE, TRUNCATE ON pharmacy_dispatches FROM clinos_app;
```

The app role is not the table owner and has no `BYPASSRLS`; `webhook_events` is written once per event with its final `process_result`, so it needs no `UPDATE` privilege.

## RLS

- `ENABLE` and `FORCE ROW LEVEL SECURITY` on `pharmacy_dispatches` and `webhook_events`.
- Policy `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` for `SELECT`, `INSERT`, `UPDATE`; an unset tenant matches nothing instead of raising a cast error. Tenant is set with `SET LOCAL` inside the transaction, never per pooled connection.
- Before the tenant is known a tenant-scoped policy cannot apply: signature verification and the dedupe insert are proposed for a dedicated `clinos_webhook_ingest` role with `INSERT` only on `webhook_events` and no read of clinical tables; the state change then runs under the resolved tenant. **Policy shape for that window is OPEN-2.**

## Endpoints

| Method and path | Auth | Permission | Notes |
| --- | --- | --- | --- |
| `POST /api/v1/pharmacy/webhooks/{provider}` | none (signature) | — | 600/min per provider; IP allow-list second control |
| `GET /api/v1/pharmacy/dispatches` | session | `pharmacy_dispatch:read` | tenant-scoped; cursor-paginated |
| `GET /api/v1/pharmacy/dispatches/{id}` | session | `pharmacy_dispatch:read` | `404` on cross-tenant |
| `POST /api/v1/pharmacy/dispatches/{id}/dispense` | session | `pharmacy_dispatch:confirm` | step-up; terminal |
| `POST /api/v1/pharmacy/dispatches/{id}/reject` | session | `pharmacy_dispatch:confirm` | reason code required |

**Mount point (OPEN-1):** this feature adopts `/api/v1/pharmacy/webhooks/{provider}` — provider-scoped under `/api/v1`, matching `02 §11`'s `/pharmacy/webhooks/*` shape rather than `10 §7`'s bare `/webhooks/:provider`. The conflict is logged, not silently resolved.

## Deny-by-default request path (webhook)

1. WAF rate rule, then the application rate limit per provider.
2. Reject a non-`application/json` content type and any body over 256 KB before reading further.
3. Verify the signature over the raw body and enforce the 5-minute window; on failure `401`, count, alert.
4. Parse against a strict schema; unknown fields rejected.
5. Resolve the tenant from the verified payload; no mapping ⇒ quarantine `202` (**OPEN-2**).
6. Dedupe on `(provider, provider_event_id)`; a duplicate returns `200` with no state change.
7. `SET LOCAL app.tenant_id`; apply the state change only if it does not regress a terminal state, and write the audit event in the same transaction.
8. Commit, then return `200`. Any error before commit returns `500` and changes nothing.

## Failure behaviour

| Failure | Detection | Behaviour |
| --- | --- | --- |
| Provider down | connection refused / breaker open | non-terminal `REQUIRES_RECONCILIATION`; clinical fallback (`10 §9`) |
| Processing failure | exception before commit | rollback, `500` so the provider retries, park after the retry budget |
| Malformed body | schema validation | `422`, event recorded `REJECTED`, no state change |
| Duplicate event | unique conflict | `200`, no state change |
| Unknown tenant | no mapping | `202`, quarantine and alert |
| Audit write failure | DB error | the state change does not commit (`07 §5`) |

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 webhook mount point (`10 §7` `/webhooks/:provider` vs `02 §11` `/pharmacy/webhooks/*`) | Head of Platform + Security Lead | OPEN |
| OPEN-2 quarantine storage for a no-tenant payload: sentinel tenant, nullable tenant with a policy exception, or a separate un-scoped quarantine table | Security Lead + CTO | OPEN |
| OPEN-3 reason-code and HTTP-code vocabulary | CTO + Security Lead | OPEN |
| Terminal-state trigger availability on the target PostgreSQL build | Head of Platform | OPEN |
