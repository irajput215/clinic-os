# Clinic setup: test plan

Denial paths first.

| Level | Case | Where |
|---|---|---|
| api | `GET /tenants/current/setup` without `tenant:configure` → `403`; another tenant's data never counted | `backend/tests/tenancy/test_setup.py` |
| api | `PATCH /tenants/current/settings`: no permission `403`; retention 6 → `422`; `NURSE` removed → `422`; unknown field → `422`; a `tenant_id` in the body is ignored and audited | `backend/tests/tenancy/test_settings.py` |
| api | A failed audit write fails the settings change (INV-4) | same |
| api | Each step flips to `done` only when its source data exists; deleting the source (e.g. last invite revoked) flips it back | `backend/tests/tenancy/test_setup.py` |
| api | Missing `tenant_settings` row → defaults returned and `workflow` step `todo` (fail closed) | same |
| perf | `GET /tenants/current/setup` is pinned at 1 round trip after the prelude | `backend/tests/performance/test_round_trips.py` |
| e2e | A freshly verified owner sees the checklist on Today; a nurse in the same clinic does not | `frontend/tests/setup-checklist.spec.ts` |
| e2e | Completing hours from the checklist link returns to Today with that step done | same |
| e2e | All required steps done → "Your clinic is ready" once, then the card is gone | same |
| e2e | Settings → Practice is read-only for a doctor | `frontend/tests/clinic-settings.spec.ts` |
