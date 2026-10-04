# Test Plan & Definition of Done: Clinical Records

## 1. Clinical Invariants & Security Test Suite

### Test 3.1: Immutable Signed Note Enforcement (Critical)
* **Goal**: Prove that once a note is signed, neither the API nor SQL UPDATE can modify it in place.
* **Test Case**:
  1. Author a clinical note for Patient A: `is_signed = FALSE`.
  2. Execute `POST /api/v1/notes/{id}/sign` with valid step-up auth.
  3. Verify note status is `is_signed = TRUE`, `signed_at` populated.
  4. Attempt `PUT /api/v1/notes/{id}` or `PATCH /api/v1/notes/{id}` modifying text.
  5. **Assert**: API rejects with HTTP `403 Forbidden` (`NOTE_ALREADY_SIGNED`).
  6. Attempt direct database update: `UPDATE clinical_note_versions SET assessment = 'Altered' WHERE note_id = :id`.
  7. **Assert**: DB trigger or check constraint aborts transaction.

### Test 3.2: Versioned Amendment Integrity
* **Goal**: Confirm that amending a note creates version 2 and preserves version 1.
* **Test Case**:
  1. For the signed note from Test 3.1, execute `POST /api/v1/notes/{id}/amend` with `amendment_reason = 'Added follow-up advice'`.
  2. Query version history: `GET /api/v1/encounters/{encounter_id}`.
  3. **Assert**: Response contains both Version 1 (original text) and Version 2 (amended text) in deterministic ascending order.

### Test 3.3: Cross-Tenant Clinical Isolation (Gate 2)
* **Goal**: Tenant B doctor cannot read clinical encounters belonging to Tenant A patients.
* **Test Case**:
  1. As Tenant A doctor, create encounter and note for Patient A.
  2. As Tenant B doctor, execute `GET /api/v1/encounters/{encounter_id}`.
  3. **Assert**: HTTP `404 Not Found` returned.
  4. Assert `TENANT_CROSS_ACCESS_ATTEMPT` audit event emitted.

---

## 2. Definition of Done Checklist (Doc 24)

- [ ] **1. Schema & RLS**: Encounters and Note Version tables configured with RLS and `FORCE`.
- [ ] **2. Immutability Trigger**: Database enforces no modification of signed notes.
- [ ] **3. Step-Up Signature**: Signing and amending endpoints require step-up challenge.
- [ ] **4. Log Redaction**: Verified that SOAP clinical text never appears in stdout/datadog/audit logs.
- [ ] **5. Latency Gate**: Clinical record query resolves under 200ms p95 with 50 previous encounters.
- [ ] **6. Audit Trail Verified**: Note creation, signing, viewing, and amendment write to `audit_log`.
- [ ] **7. Gate 4 Sign-Off**: Reviewed and signed by Clinical Safety Officer.
