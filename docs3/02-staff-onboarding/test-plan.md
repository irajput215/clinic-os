# Staff onboarding: test plan

Denial paths first.

| Level | Case | Where |
|---|---|---|
| api | Identifier `PUT`: no permission `403`; no / reused / wrong-operation step-up `403`; another tenant's user `404`; bad AHPRA/HPI-I format `422` | `backend/tests/rbac/test_identifiers.py` |
| api | Onboarding read: a nurse reading a doctor's pack `403`; self allowed; values masked; read audited | same |
| api | Identifier values never appear in logs, audit payloads or error bodies (log capture assertion) | `backend/tests/security/test_no_phi_in_logs.py` |
| api | **Sign gate:** each missing item alone → `403 PRESCRIBER_NOT_READY` naming it; denial audited; the script stays unsigned | `backend/tests/prescriptions/test_sign_requires_pack.py` |
| api | Sign gate fails closed: no identifier rows at all → refused | same |
| api | Pack complete → sign proceeds to the existing safety gate unchanged | same |
| api | A new SOP version un-completes every affected pack until re-acknowledged | `backend/tests/sops/test_versions.py` |
| api | SOP: acknowledge an old version `409`; acknowledge an SOP that doesn't apply `404`; versions append-only (no `UPDATE`/`DELETE` grant) | `backend/tests/sops/` |
| api | Granting `DOCTOR` creates pending identifier rows in the same transaction | `backend/tests/rbac/test_role_administration_authz.py` |
| perf | Sign stays within its round-trip budget with the pack check in the same flight | `backend/tests/performance/test_round_trips.py` |
| e2e | Invite → accept → first sign-in shows the nurse "first hour" card; dismissed, it stays gone | `frontend/tests/staff-onboarding.spec.ts` |
| e2e | Owner completes a doctor's pack (with step-up); the staff row reads Ready; the doctor can now sign | same |
| e2e | A doctor with an incomplete pack sees the refusal naming what's missing on Review & sign | `frontend/tests/scripts.spec.ts` |
| e2e | SOP publish v2 → staff see the badge → acknowledge → badge clears; print shows UNCONTROLLED COPY | `frontend/tests/sops.spec.ts` |
