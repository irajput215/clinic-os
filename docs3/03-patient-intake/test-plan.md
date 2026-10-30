# Patient intake: test plan

Denial paths first.

| Level | Case | Where |
|---|---|---|
| api | Public submit: under 18 `422 UNDER_AGE` and nothing stored; declaration mismatch `422`; stale consent version `422`; slot not offered `422`; unknown slug `404`; no consents published `423` | `backend/tests/intake/test_public_application.py` |
| api | A `tenant_id` in the public body is ignored, audited as cross-tenant; the application lands in the slug's tenant | same |
| api | **No enumeration:** new, existing and duplicate applicants get byte-identical response shape and status | same |
| api | The request body never reaches logs at any level, including on error (log capture) | `backend/tests/security/test_no_phi_in_logs.py` |
| api | One transaction: a failed audit write or a failed appointment hold leaves no patient, application or appointment behind (INV-4) | `backend/tests/intake/test_atomicity.py` |
| api | Product and brand names: the form endpoint and every public error contain none from the formulary list | `backend/tests/intake/test_no_product_names.py` |
| api | Queue: no `patient:read` `403`; another tenant's application `404`; accept / reject without `patient:create` `403`; decide twice `409` | `backend/tests/intake/test_queue.py` |
| api | Accept: patient `CURRENT`; consents recorded at the signed versions; own pharmacy added; an **existing** patient's details untouched; audited | same |
| api | Reject: appointment cancelled; created patient `ARCHIVED` with reason; email sent without the reason | same |
| api | Briefing: a doctor without a care relationship `403 AUTHZ_CARE_RELATIONSHIP_DENIED`; with one `200`; read audited | `backend/tests/intake/test_briefing.py` |
| api | Consent: publish needs `tenant:configure`; versions append-only; a material change flags patients on older versions | `backend/tests/intake/test_consents.py` |
| perf | Submit and accept pinned at their round-trip budgets | `backend/tests/performance/test_round_trips.py` |
| e2e | A patient completes all six steps on a 360 px viewport and books; the application appears in the queue | `frontend/tests/intake.spec.ts` |
| e2e | Under-18 stops at step 1; Back keeps answers; the URL never contains an answer | same |
| e2e | Reception accepts → patient record shows consents, pharmacy and the briefing (for the treating doctor) | same |
| e2e | Reception rejects with a reason → the calendar slot is free again | same |
| a11y | Every step reachable by keyboard; errors announced; labels on every control | same |
