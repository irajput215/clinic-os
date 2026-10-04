---
feature_id: FEAT-02
title: Patient Register and Demographics Specification
status: DRAFT
owner: Head of Product / Clinical Safety Officer
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
traceability_docs:
  - clinic-os-secure-by-design/04-database-erd.md
  - clinic-os-secure-by-design/12-data-classification.md
  - clinic-os-secure-by-design/20-product-requirements.md
  - clinic-os-secure-by-design/22-user-stories.md
---

# Feature 02: Patient Register and Demographics

## 1. Overview & Purpose
Maintain the authoritative clinical patient index for each clinic tenant. The Patient Register manages patient identity, Australian demographic identifiers (Medicare, IHI, DVA), contact details, consent flags, and deterministic duplicate candidate detection.

**Clinical Invariant:**
A patient record is medical history and must **never be hard-deleted**. Merges are reversible, and viewing a patient record is an audited clinical action.

---

## 2. Personas & User Stories

### Story 2.1: Patient Intake and Duplicate Detection
- **As a** Clinic Receptionist / Administrator
- **I want to** register a new patient by entering their name, date of birth, phone, and Medicare number
- **So that** they have an authoritative medical record without creating duplicate charts.
  - *Clinical Safety Criterion:* If a patient matches on `(first_name + last_name + DOB)` OR `Medicare Number`, the system halts creation, surfaces the duplicate candidate, and prompts for confirmation or chart merge.
  - *Audit Criterion:* Emits `PATIENT_CREATED` or `DUPLICATE_CANDIDATE_FLAGGED`.

### Story 2.2: Treating Relationship Access Control
- **As a** Treating Doctor / Nurse
- **I want to** search and open the clinical chart of an active patient
- **So that** I can review their history before a consultation.
  - *Security Criterion:* Clinicians can only view patients assigned to their clinic branch or with an active treating relationship. Bulk export requires step-up authentication.
  - *Audit Criterion:* Emits `PATIENT_VIEWED` with patient ID, clinician ID, and purpose.

### Story 2.3: Reversible Patient Chart Merge
- **As a** Clinical Safety Officer
- **I want to** merge duplicate records for the same individual
- **So that** all clinical encounters and TGA approvals consolidate into one master record.
  - *Security Criterion:* Merges require step-up authentication and are strictly reversible (`PATIENT_MERGE_REVERSED`). Original identifiers are retained.

---

## 3. Australian Healthcare Identifiers & Data Model

| Identifier | Format / Validation | Storage / Encryption | Privacy Act (Cth) Obligation |
|---|---|---|---|
| **Medicare Number** | 10 digits + 1 digit IRN (Luhn/Modulus 10 check) | AES-256 encrypted; masked in UI as `****** 1234 1` | Section 133 of Health Insurance Act 1973 |
| **IHI (Individual Healthcare Identifier)** | 16-digit number starting with `800360` | AES-256 encrypted; masked in UI | Healthcare Identifiers Act 2010 |
| **DVA File Number** | State prefix + alphanumeric | Encrypted at rest | Veterans' Entitlements Act |
| **Date of Birth** | `YYYY-MM-DD` | Standard date column; indexed | Privacy Act Sensitive Info |

---

## 4. API Endpoints (Deny-by-Default)

| Method | Endpoint | Required Permission | Step-Up? | Audit Event |
|---|---|---|:---:|---|
| `GET` | `/api/v1/patients` | `patient:read` | No | `PATIENT_LIST_VIEWED` |
| `POST` | `/api/v1/patients` | `patient:create` | No | `PATIENT_CREATED` |
| `GET` | `/api/v1/patients/{id}` | `patient:read` | No | `PATIENT_VIEWED` |
| `PATCH` | `/api/v1/patients/{id}` | `patient:update` | No | `PATIENT_UPDATED` |
| `GET` | `/api/v1/patients/search?q=` | `patient:read` | No | `PATIENT_SEARCH_PERFORMED` |
| `POST` | `/api/v1/patients/{id}/merge` | `patient:merge` | **Yes** | `PATIENT_MERGED` |
| `POST` | `/api/v1/patients/{id}/unmerge` | `patient:merge` | **Yes** | `PATIENT_MERGE_REVERSED` |

---

## 5. Database Schema & RLS

```sql
CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    clinic_id UUID NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
    
    -- Demographics
    first_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    last_name VARCHAR(100) NOT NULL,
    preferred_name VARCHAR(100),
    date_of_birth DATE NOT NULL,
    gender VARCHAR(50) NOT NULL,
    
    -- Contact & Identifiers
    email VARCHAR(255),
    phone VARCHAR(50) NOT NULL,
    medicare_number VARCHAR(20),       -- Validated Modulus 10
    medicare_irn SMALLINT,            -- Individual Reference Number (1-9)
    medicare_expiry DATE,
    ihi_number VARCHAR(20),           -- 16-digit Healthcare Identifier
    address JSONB NOT NULL DEFAULT '{}'::jsonb,
    
    -- Safety & Duplicate Flags
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, MERGED, ARCHIVED
    merged_into_patient_id UUID REFERENCES patients(id),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Compound indexes for fast, tenant-isolated lookups
CREATE INDEX idx_patients_tenant_lookup ON patients(tenant_id, last_name, first_name);
CREATE INDEX idx_patients_tenant_dob ON patients(tenant_id, date_of_birth);
CREATE INDEX idx_patients_tenant_phone ON patients(tenant_id, phone);

-- RLS Backstop
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients FORCE ROW LEVEL SECURITY;

CREATE POLICY patients_tenant_isolation ON patients
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
```
