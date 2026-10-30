# Patient record: test plan

Denial paths first.

| Level | Case | Where |
|---|---|---|
| api | Status change: no `patient:update` `403`; another tenant `404`; missing reason for `BLOCKED` `422`; audited | `backend/tests/patients/test_status.py` |
| api | `BLOCKED` patient: staff booking, public application and script staging all refused; unblocked, all allowed | same |
| api | Identifiers: bad Medicare / IRN / IHI `422` and the value is not echoed; ciphertext in the column, never plaintext (raw SQL read as the app role) | `backend/tests/patients/test_identifiers.py` |
| api | Masking: every response shows `•••• ••• 123`; logs and audit payloads contain no identifier (log capture) | same + `backend/tests/security/test_no_phi_in_logs.py` |
| api | Blind-index search finds the exact match only; a different tenant's identical Medicare is not found | `backend/tests/patients/test_search.py` |
| api | Key rotation: a record written under key v1 still reads after v2 becomes current | `backend/tests/core/test_field_encryption.py` |
| api | `escript_ready`: each missing item reported; all present → ready | `backend/tests/patients/test_escript_ready.py` |
| api | Receives communications off: reminder skipped; booking confirmation still sent | `backend/tests/appointments/test_notifications.py` |
| api | Migration backfill: existing rows `CURRENT`, deceased rows `DECEASED`; `alembic check` clean | `backend/tests/core/test_schema_conventions.py` |
| e2e | Register a patient over the phone with sex, address, Medicare, IHI → record shows ⚡ eScript-ready and masked identifiers | `frontend/tests/patients.spec.ts` |
| e2e | Add an alert → it appears on the header and in the calendar's patient picker | same |
| e2e | Block a patient → booking them on the calendar shows the refusal | `frontend/tests/calendar-and-booking.spec.ts` |
| e2e | Status filter hides archived patients by default | `frontend/tests/patients.spec.ts` |
