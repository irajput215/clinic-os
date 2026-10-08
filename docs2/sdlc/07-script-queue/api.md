# Script queue and safety gate: API

**Status: Agreed 2026-10-07 (owner).** Built in `backend/app/modules/prescriptions/` (Milestone 2,
phase 2D). Where this contract and `docs/features/10-13` disagreed, `docs/` was followed; each
reconciliation is listed at the end.

All routes follow the repo's non-negotiables: tenant from the session only, RLS (enabled and forced) on
every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`,
strict request bodies (unknown fields are `422`).

## Endpoints

| Method | Path | Permission | Contract |
|---|---|---|---|
| `GET` | `/api/v1/prescriptions?state=&prescriber_id=&patient_id=&cursor=&limit=` | `prescription:read` | Keyset page `{data, next_cursor}`, newest first. `state` may repeat. Each `PrescriptionRead` carries patient, prescriber and drafter names, the latest `dispatch` row, and - for `DRAFT`, `SIGNED`, `BLOCKED`, `FAILED` - the **current** `gate` (`TgaMatchResponse`, evaluated now, display only). |
| `GET` | `/api/v1/prescriptions/prescribers` | `prescription:create` | `{data: [{id, name}]}`: active colleagues holding `prescription:sign` (decided by permission, never a role name). |
| `POST` | `/api/v1/prescriptions` | `prescription:create` | Stage a `DRAFT`: `{patient_id, prescriber_id, medicine_name, tga_category, dosage_form, dose_instruction, quantity, repeats (0-12), triage_outcome, conventional_therapy, date_of_service}`. `201`. `404 PATIENT_NOT_FOUND`; `422 PRESCRIBER_NOT_AUTHORIZED`. Audited `prescription.create`. |
| `POST` | `/api/v1/auth/step-up` | session | `{password, operation: prescription.sign \| prescription.dispatch, resource_id}` -> `201 {step_up_token, expires_at}`: single use, 2 minutes, bound to user + operation + resource. Wrong password `403 STEP_UP_FAILED`. Audited `auth.step_up` / `auth.step_up_failed`. |
| `POST` | `/api/v1/prescriptions/{id}/sign` | `prescription:sign` + prescriber of record | `{step_up_token}`. In **one transaction**: lock the row `FOR UPDATE`, check the signer, spend the grant, check `DRAFT`, run the gate with every approval of the patient locked `FOR UPDATE`, then `SIGNED` with `signed_at`, `signed_by`, `payload_hash` and the covering `approval_id`. Refusals: `403 NOT_PRESCRIBER_OF_RECORD`, `403 STEP_UP_REQUIRED`, `409 INVALID_STATE_TRANSITION`, `422 <match reason>` ("Active TGA Approval Required"; the row stays `DRAFT`). Audited `prescription.sign` (`SUCCESS` or `DENIED` with `block_reason`). |
| `POST` | `/api/v1/prescriptions/{id}/dispatch` | `prescription:dispatch` | Header `Idempotency-Key` required (`422 IDEMPOTENCY_KEY_REQUIRED`), body `{step_up_token}`. Same transaction shape as sign: the gate runs again (fail closed). Refused: `SIGNED -> BLOCKED`, `422 <match reason>`, `prescription.dispatch_blocked`. Allowed: `-> QUEUED`, one `dispatch_attempts` outbox row and `prescription.dispatch` with `approval_id` and the server-computed key, **`202 Accepted`**. Replaying the same key answers `200` with the current state and changes nothing. A second intent while one is live is `409`. |

## Dispatch, the outbox, and what is not built

**Nothing is sent to a pharmacy.** No pharmacy or eRx transport exists, and adding one is a new
third-party data flow. A dispatched prescription is `QUEUED`, its `dispatch.transport_configured` is
`false`, and the UI says "Queued, not sent". `backend/app/modules/prescriptions/transport.py` defines
the transport interface and lists exactly what a real transport needs (certified conformant party
and contract, secret-store credentials, timeouts/retry/breaker, egress allow-list, payload
minimisation, the FEAT-12 webhook receiver, an outage playbook).

The worker the documents require is a per-tenant command with no new infrastructure:

```bash
cd backend && uv run python -m app.modules.prescriptions.outbox drain --tenant-id <uuid>
cd backend && uv run python -m app.modules.prescriptions.outbox reconcile --tenant-id <uuid>
```

With no transport both change nothing and exit `2`. With one (tested against a simulated driver):
claim `FOR UPDATE SKIP LOCKED` and re-run the gate before sending; send once with the key;
`Confirmed -> DISPATCHED`, `Rejected`/`NotSent -> FAILED`, timeout or unparsable `->
REQUIRES_RECONCILIATION` (never success); reconciliation resolves both directions with
`resolution_reason = RECONCILED`; a claimed-but-unrecorded row is never sent again.

## Reconciliations with `docs/`

- Gate refusals are **`422`** at sign and at dispatch (FEAT-10 design steps 7-8), not docs2's `409`.
- The sign-time refusal is audited `prescription.sign` `DENIED`: `prescription.sign_blocked` is not in
  the closed audit catalogue and was not invented.
- Reason codes are the existing TGA match vocabulary (`TGA_APPROVAL_NOT_FOUND`, `..._REVOKED`, ...);
  FEAT-10's `NO_ACTIVE_TGA_APPROVAL_FOR_*` family is recorded as an open reconciliation for the CSO.
- Missing step-up is **`403 STEP_UP_REQUIRED`** (feature 02, and the client signs out on `401`), not
  FEAT-10/11's `401`. The grant is bound to the user, not a session (no session record exists, D-003).
- The draft takes `medicine_name`, `tga_category` and `dosage_form` (FEAT-11 columns), not a
  `product_id`: there is no drug catalogue. `repeats` is `0..12` (FEAT-11), not `0..5`.
- `prescriber_id` is accepted on staging (docs2 R1, FEAT-11 US-6) and validated server-side, although
  FEAT-11 R2 lists it as refused.
- Not built (no route in this contract): `PATCH`, `addendum`, `cancel`, `history`, single read, the
  pharmacy webhook and receipts (FEAT-12), a separate worker database role.
