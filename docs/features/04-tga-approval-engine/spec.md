---
feature_id: FEAT-04
title: TGA Approval Engine and Register Specification
status: DRAFT
owner: Clinical Safety Officer / Head of Product
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
traceability_docs:
  - clinic-os-secure-by-design/08-tga-approval-model.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md
  - clinic-os-secure-by-design/20-product-requirements.md
  - clinic-os-secure-by-design/21-technical-design.md
---

# Feature 04: TGA Approval Engine and Register

## 1. Overview & Purpose
Maintain the authoritative regulatory approval register that gates unapproved therapeutic goods (such as medicinal cannabis or Schedule 8 substances) under the Australian Therapeutic Goods Administration (TGA) Authorised Prescriber (AP) and Special Access Scheme (SAS B) pathways.

**The Golden Law: The TGA Approval Grain**
Every approval in ClinicOS is strictly evaluated against this 4-part grain:
```
PATIENT ID + TGA CATEGORY + DOSAGE FORM + 2-YEAR TEMPORAL VALIDITY INTERVAL
```
An approval is **never** evaluated at the patient level alone, never at the medicine/brand level alone, and never as a static boolean.

---

## 2. Personas & User Stories

### Story 4.1: Registering and Verifying a TGA Approval Letter
- **As a** Clinic Administrator / Clinical Safety Officer
- **I want to** enter the TGA approval reference, category, dosage form, and validity dates with the source PDF attached
- **So that** prescriptions can legally be written for this patient under this category.
  - *Clinical Safety Criterion:* Creation starts in `PENDING` state. Transition to `ACTIVE` requires verification by a clinician possessing `tga_approval:verify` (separated from creator where Separation of Duties is enforced).
  - *Audit Criterion:* Emits `TGA_APPROVAL_CREATED` and `TGA_APPROVAL_VERIFIED` with full grain metadata.

### Story 4.2: Point-in-Time Regulatory Matching
- **As the** Prescription Safety Gate service
- **I want to** query whether an active approval covered the patient on the exact date of consultation/service
- **So that** I know whether a script can be issued, or if it must be blocked.
  - *Clinical Safety Criterion:* Evaluated against `date_of_service`, NOT the current system clock (supports retrospective review and audit).
  - *Audit Criterion:* Emits `TGA_APPROVAL_MATCHED` or `TGA_APPROVAL_MATCH_FAILED`.

### Story 4.3: Revoking or Superseding an Approval
- **As a** Prescribing Doctor / Practice Owner
- **I want to** revoke an approval if clinical indication ceases or TGA status changes
- **So that** no further prescriptions can be dispensed against it.
  - *Security Criterion:* Revocation requires step-up authentication, a mandatory reason code, and immediately locks dispatch for matching categories.

---

## 3. TGA Approval State Machine

```
               ┌──────────┐
               │ PENDING  │ (Created from PDF / Manual Entry)
               └────┬─────┘
                    │
         verify()   │   reject()
       ┌────────────┴────────────┐
       ▼                         ▼
┌──────────────┐          ┌──────────────┐
│    ACTIVE    │          │   REJECTED   │ (Invalid / illegible)
└──────┬───────┘          └──────────────┘
       │
       ├─────────────────┬──────────────────┐
       │ (after 2 years) │ revoke()         │ supersede()
       ▼                 ▼                  ▼
┌──────────────┐  ┌──────────────┐   ┌──────────────┐
│   EXPIRED    │  │   REVOKED    │   │  SUPERSEDED  │ (Replaced by new grant)
└──────────────┘  └──────────────┘   └──────────────┘
```

---

## 4. API Endpoints (Deny-by-Default)

| Method | Endpoint | Required Permission | Step-Up? | Audit Event |
|---|---|---|:---:|---|
| `GET` | `/api/v1/patients/{patient_id}/tga-approvals` | `tga_approval:read` | No | `TGA_APPROVAL_LISTED` |
| `POST` | `/api/v1/patients/{patient_id}/tga-approvals` | `tga_approval:create` | No | `TGA_APPROVAL_CREATED` |
| `GET` | `/api/v1/tga-approvals/{id}` | `tga_approval:read` | No | `TGA_APPROVAL_VIEWED` |
| `POST` | `/api/v1/tga-approvals/{id}/verify` | `tga_approval:verify` | **Yes** | `TGA_APPROVAL_VERIFIED` |
| `POST` | `/api/v1/tga-approvals/{id}/revoke` | `tga_approval:revoke` | **Yes** | `TGA_APPROVAL_REVOKED` |
| `GET` | `/api/v1/tga-approvals/match` | `tga_approval:read` | No | `TGA_APPROVAL_MATCHED` |

---

## 5. Database Schema & GiST Temporal Exclusion Constraint

```sql
-- Ensure btree_gist extension is available for compound temporal constraints
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE tga_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
    
    -- The Core Approval Grain
    tga_category VARCHAR(50) NOT NULL, -- e.g. 'CATEGORY_1', 'CATEGORY_3', 'CATEGORY_5'
    dosage_form VARCHAR(50) NOT NULL,  -- e.g. 'OIL', 'FLOWER', 'VAPE', 'CAPSULE'
    validity_interval DATERANGE NOT NULL, -- [valid_from, valid_to) — max 2 years
    
    -- Status & References
    state VARCHAR(30) NOT NULL DEFAULT 'PENDING', -- PENDING, ACTIVE, EXPIRED, REJECTED, REVOKED, SUPERSEDED
    tga_application_number VARCHAR(100),
    source_document_id UUID,           -- S3 object pointer to approval PDF
    
    -- Verification & Attribution
    created_by UUID NOT NULL REFERENCES users(id),
    verified_by UUID REFERENCES users(id),
    verified_at TIMESTAMPTZ,
    revocation_reason TEXT,
    revoked_by UUID REFERENCES users(id),
    revoked_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- CONSTRAINT: No two ACTIVE approvals may overlap for the same (tenant, patient, category, dosage_form)
    CONSTRAINT no_overlapping_active_approvals EXCLUDE USING gist (
        tenant_id WITH =,
        patient_id WITH =,
        tga_category WITH =,
        dosage_form WITH =,
        validity_interval WITH &&
    ) WHERE (state = 'ACTIVE')
);

-- RLS Backstop
ALTER TABLE tga_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE tga_approvals FORCE ROW LEVEL SECURITY;

CREATE POLICY tga_approvals_tenant_isolation ON tga_approvals
    FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
```
