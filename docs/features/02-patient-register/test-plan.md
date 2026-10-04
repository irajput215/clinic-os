# Test Plan & Definition of Done: Patient Register

## 1. Clinical Safety & Security Test Suite

### Test 2.1: Duplicate Detection Algorithm
* **Goal**: Ensure the system prevents accidental duplicate charts for the same patient.
* **Test Case**:
  1. Insert Patient A: `Jane Doe`, DOB: `1985-04-12`, Medicare: `2345678901 / 1`.
  2. Attempt `POST /api/v1/patients` with Patient B: `Jane M Doe`, DOB: `1985-04-12`.
  3. **Assert**: API returns HTTP `409 Conflict` with candidate duplicate ID and match reason `NAME_AND_DOB_MATCH`.
  4. Attempt `POST /api/v1/patients` with Patient C: `Alice Smith`, DOB: `1990-01-01`, but Medicare: `2345678901 / 1`.
  5. **Assert**: API returns HTTP `409 Conflict` with match reason `MEDICARE_NUMBER_MATCH`.

### Test 2.2: Cross-Tenant Patient Isolation (Gate 2)
* **Goal**: Guarantee Tenant B cannot read Tenant A’s patients.
* **Test Case**:
  1. As Tenant A clinician, register patient "Bob Martin".
  2. As Tenant B clinician, execute `GET /api/v1/patients?q=Martin`.
  3. **Assert**: Returns 0 results.
  4. Tenant B attempts direct access `GET /api/v1/patients/{bob_martin_id}`.
  5. **Assert**: Returns HTTP `404 Not Found`.

### Test 2.3: Patient Access Audit Trail (APP 11 / Doc 07)
* **Goal**: Every patient file view must generate an immutable audit log row.
* **Test Case**:
  1. Clinician visits `GET /api/v1/patients/{id}`.
  2. Inspect database `audit_log` table within the same transaction.
  3. **Assert**: Exactly 1 record created with `event_type = 'PATIENT_VIEWED'`, matching `actor_id` and `patient_id`.

---

## 2. Definition of Done Checklist (Doc 24)

- [ ] **1. Schema & RLS**: `patients` table created with `tenant_id NOT NULL` and `FORCE ROW LEVEL SECURITY`.
- [ ] **2. Modulus 10 Validation**: Medicare number validator rejects invalid check-digits before hitting the DB.
- [ ] **3. Duplicate Guard Active**: Creation workflow enforces fuzzy/exact duplicate candidate check.
- [ ] **4. PII Masking Verified**: Frontend components mask Medicare and IHI by default with an audit-logged reveal action.
- [ ] **5. CI Isolation Green**: Test suite includes cross-tenant absence and unmerge test cases.
- [ ] **6. Audit Verified**: All view and mutation routes write to `audit_log`.
- [ ] **7. Gate 4 Sign-Off**: API and data validation reviewed by Head of Product and CSO.
