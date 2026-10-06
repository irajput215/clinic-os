# Script queue and safety gate: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `POST` | `/api/v1/tga-approvals/match` | `backend/app/modules/tga_approvals/router.py` (#46) | `{patient_id, tga_category, dosage_form, date_of_service}` gives `TgaMatchResponse` (`matched`, `reason_code`, window, timezone). POST so PHI stays out of URLs. |

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/prescriptions?state=&prescriber_id=&cursor=` | Queue and history. For actionable scripts the server includes the **current** `gate` (`TgaMatchResponse`). |
| `POST` | `/api/v1/prescriptions` | Stage: `ScriptDraft` (see `src/data/types.ts`). Product resolves category and form server-side. Needs `prescription:create`. |
| `POST` | `/api/v1/prescriptions/{id}/sign` | Needs `prescription:sign`, the assigned prescriber and a step-up proof (D-003). Runs the gate in the same transaction with `SELECT … FOR UPDATE`. A refusal gives `409` with `detail.code` (the match reason) and writes `prescription.sign_blocked` to the audit log. |
| `POST` | `/api/v1/prescriptions/{id}/dispatch` | Needs `Idempotency-Key`. Re-runs the gate (fail closed) and writes a transactional outbox row. The worker calls the Parchment adapter with timeouts and jittered retries. A timeout gives **REQUIRES_RECONCILIATION**, never failure or false success. Every block writes `prescription.dispatch_blocked` with the reason. |
