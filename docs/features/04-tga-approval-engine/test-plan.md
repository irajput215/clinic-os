# Test Plan & Definition of Done: TGA Approval Engine

## 1. Regulatory Grain & Safety Test Suite

### Test 4.1: The 4-Part Approval Grain Match
* **Goal**: Validate that approvals only match when ALL four components align.
* **Test Setup**:
  - Patient A has an `ACTIVE` approval for `(CATEGORY_5, OIL, [2026-01-01, 2028-01-01))`.
* **Assertions**:
  1. Match for `(Patient A, CATEGORY_5, OIL, 2026-06-01)` -> **RETURNS ACTIVE** (Match success).
  2. Match for `(Patient A, CATEGORY_5, FLOWER, 2026-06-01)` -> **FAILS** (Wrong dosage form).
  3. Match for `(Patient A, CATEGORY_1, OIL, 2026-06-01)` -> **FAILS** (Wrong category).
  4. Match for `(Patient B, CATEGORY_5, OIL, 2026-06-01)` -> **FAILS** (Wrong patient).
  5. Match for `(Patient A, CATEGORY_5, OIL, 2028-01-02)` -> **FAILS** (Temporal interval expired).

### Test 4.2: Temporal Exclusion Constraint (GiST)
* **Goal**: Prove that the database rejects overlapping active intervals for the same grain.
* **Execution**:
  1. Insert active approval for Patient A: `CATEGORY_5, OIL, [2026-01-01, 2027-01-01)`.
  2. Attempt to insert second active approval for Patient A: `CATEGORY_5, OIL, [2026-06-01, 2027-06-01)`.
  3. **Assert**: PostgreSQL raises exclusion violation error (`no_overlapping_active_approvals`).

### Test 4.3: Separation of Duties on Verification
* **Goal**: Prevent self-verification when configured.
* **Execution**:
  1. Admin User A enters pending approval.
  2. Admin User A attempts to call `POST /api/v1/tga-approvals/{id}/verify`.
  3. **Assert**: Returns HTTP `403 Forbidden` (`VERIFIER_CANNOT_BE_CREATOR`).
  4. User B (Doctor) calls verify endpoint -> **Succeeds**, transitions state to `ACTIVE`.

---

## 2. Definition of Done Checklist (Doc 24)

- [ ] **1. Schema & Constraints**: `tga_approvals` table created with `validity_interval DATERANGE` and GiST exclusion constraint.
- [ ] **2. Grain Verification**: Match query evaluated on `Patient + Category + Dosage Form + Date of Service`.
- [ ] **3. State Transitions**: Server-side state machine strictly enforced (Pending -> Active -> Expired/Revoked).
- [ ] **4. Step-Up Verification**: Verification and Revocation endpoints require step-up challenge.
- [ ] **5. Audit Verification**: Match events and failures log directly to `audit_log`.
- [ ] **6. Gate 4 & 5 Sign-Off**: Formally signed off by Clinical Safety Officer and Head of Product.
