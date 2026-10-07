# TGA approvals: API

## Endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `GET` | `/api/v1/tga-approvals` | `backend/app/modules/tga_approvals/router.py` | The practice-wide register. Contract below |
| `GET` | `/api/v1/patients/{patient_id}/tga-approvals` | same (#46) | `TgaApprovalsPublic` |
| `POST` | `/api/v1/tga-approvals` | same | `TgaApprovalCreate`, `extra=forbid`, two-year and forward-window checks |
| `POST` | `/api/v1/tga-approvals/{id}/verify` | same | `{tga_application_number}`, four-eyes |
| `POST` | `/api/v1/tga-approvals/{id}/revoke` | same | `{reason_code}` |
| `POST` | `/api/v1/tga-approvals/match` | same | The gate lookup. Not called by the app yet: feature 07 is preview, and its server will run the gate itself |

## `GET /api/v1/tga-approvals` - the practice-wide register

**Status: Agreed 2026-10-07 (owner).** Built in M2 phase 2A.

All of the repo's non-negotiables hold: tenant from the session only, RLS on every table, `404`
across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

### Request

| Parameter | Type | Rule |
|---|---|---|
| `state` | repeatable, one of `PENDING ACTIVE EXPIRED REJECTED REVOKED SUPERSEDED` | Selects approvals in any of the named states. An unknown state is `422` |
| `expiring_within_days` | integer `0..731` | Selects `ACTIVE` approvals whose **last covered day** is at most this many days after today (Australia/Sydney, database clock), including ones already lapsed that the expiry job has not reached. Under the interim D-006 `[)` boundary the last covered day is `valid_to - 1` |
| `limit` | integer `1..100`, default `25` | Page size |
| `cursor` | opaque, at most 512 characters | `next_cursor` of the previous page. Signed; a forged or garbled one is `422 INVALID_CURSOR` |

`state` and `expiring_within_days` are **two selectors, combined as a union**: a row is listed when
it matches either. Neither given lists every approval. The union is what makes the register's
"Needs action" filter (`state=PENDING&expiring_within_days=30`) one keyset over one query.

A `tenant_id` in the query string is ignored; the read is still answered from the session's tenant,
and its audit event carries `reason = CLIENT_TENANT_ID_IGNORED` (INV-1).

### Response `TgaApprovalRegister`

```json
{
  "data": [ { "...TgaApprovalRead fields": "...", "patient_display_name": "Grace Liu" } ],
  "count": 25,
  "next_cursor": "eyJ...",
  "counts": {
    "by_state": { "PENDING": 3, "ACTIVE": 12, "EXPIRED": 1, "REJECTED": 0, "REVOKED": 2, "SUPERSEDED": 0 },
    "expiring": 2,
    "expiring_within_days": 30
  }
}
```

- Order: newest first on the `(created_at, id)` keyset, the same keyset and cursor format as the
  per-patient list (backed by the new `ix_tga_approvals_tenant_created` index). A cursor continues
  only the filter it was issued for.
- `patient_display_name`: preferred name (or given name) and family name, from the patients facade.
  `null` when the patient record is no longer readable (soft-deleted); the row stays listed.
- `counts`: the practice's totals, **independent of the filter and the page**, so every filter chip
  can show its count. `expiring` is counted over `expiring_within_days` when given, else 30.

### Controls

| Control | Value |
|---|---|
| Permission | `tga_approval:read` (existing; no new code) |
| Refusals | `401` unauthenticated; `403 PERMISSION_NOT_HELD`; `422` for an unknown state, an out-of-range number or a bad cursor |
| Audit | `tga_approval.read`, one event per page, same transaction, payload `query_filters` (state codes, the day count, whether a cursor was used) and `result_count`. A refusal is `DENIED` with its reason |

### Reconciliation with `docs/` (recorded)

- `docs/features/08-tga-approvals/05-data-and-audit.md` names `approval.read`; the closed catalogue in
  `docs/features/04-audit-log/05-data-and-audit.md` had no TGA read action (HANDOFF section 8). It is
  now registered there as `tga_approval.read`, in the catalogue's lowercase dotted form, the same
  mapping already applied to `approval.created` -> `tga_approval.create`. The per-patient list and the
  detail read emit it too, refusals included, so TGA read refusals are no longer unaudited.
- US-4 (feature 08) asks for a server-computed warning list of approvals expiring within 90 days:
  `expiring_within_days=90` is that list. The register's own window stays 30 days (requirements R7).
- `docs/features/09-tga-inbox` defines no register route; nothing to reconcile.
