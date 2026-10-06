# Today: API

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/dashboard/today` | One aggregated, tenant-scoped read: `TodaySummary` (see `src/data/types.ts`). The gate state for each awaiting script is evaluated server-side for the script's date of service. |
