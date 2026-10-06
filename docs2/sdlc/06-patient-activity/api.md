# Patient activity: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `GET` | `/api/v1/audit/events?resource_id=&limit=` | `backend/app/modules/audit/router.py` (merged #42) | `{data: AuditEventRead[], count, next_cursor}`. Needs `audit:read` |

No new endpoints needed.
