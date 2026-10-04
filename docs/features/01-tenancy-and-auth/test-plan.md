# Test Plan & Definition of Done: Tenancy and Authentication

## 1. Security & Isolation Test Catalogue

### Test 1.1: Cross-Tenant Negative Assertions (Gate 2)
* **Goal**: Prove that Tenant B can never see or mutate Tenant A’s records.
* **Execution**:
  1. Authenticate as User A (`tenant_id = A_UUID`), create a clinic branch: "Alpha Clinic".
  2. Authenticate as User B (`tenant_id = B_UUID`), execute `GET /api/v1/clinics`.
  3. **Assert**: Response items count is 0; "Alpha Clinic" is absent.
  4. User B attempts `GET /api/v1/clinics/{alpha_clinic_id}`.
  5. **Assert**: Returns `404 Not Found` (never reveals existence via `403`).

### Test 1.2: Connection Pool Reuse Leak Test (Doc 05 Trap)
* **Goal**: Prove that pooled database connections do not bleed `app.tenant_id`.
* **Execution**:
  1. Acquire a DB connection from pool, execute query for Tenant A with `SET LOCAL app.tenant_id = A`.
  2. Commit/close transaction and return connection to pool.
  3. Acquire the same DB connection, execute query without setting `app.tenant_id`.
  4. **Assert**: Query returns 0 rows (fails closed), or raises an exception because `app.tenant_id` is null.

### Test 1.3: Brute Force Account Lockout (Gate 3)
* **Goal**: Confirm account locks after 5 consecutive failures.
* **Execution**:
  1. Submit 5 invalid login requests for `test-clinician@clinic.com`.
  2. 6th attempt with valid credentials must be rejected with `423 Locked`.
  3. Assert `ACCOUNT_LOCKED` event is recorded in `audit_log`.

---

## 2. Definition of Done Checklist (Doc 24)

- [ ] **1. Code Complete**: Schema migrations applied cleanly forward and rollback tested.
- [ ] **2. RLS Enforced**: `FORCE ROW LEVEL SECURITY` active on all tenant tables.
- [ ] **3. Security Negative Tests**: Isolation suite and pool reuse tests passing in CI.
- [ ] **4. Audit Integrity**: All 8 authentication events write to `audit_log` with correct actor and timestamp.
- [ ] **5. Zero High/Critical Scans**: Clean report from Semgrep & Trivy.
- [ ] **6. Gate Sign-off**: Gate 1, 2, and 3 approvals signed by Security Lead & CTO.
