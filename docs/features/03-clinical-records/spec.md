---
feature_id: FEAT-03
title: Clinical Records and Consultations Specification
status: DRAFT
owner: Clinical Safety Officer / Head of Product
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
traceability_docs:
  - clinic-os-secure-by-design/04-database-erd.md
  - clinic-os-secure-by-design/12-data-classification.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md
  - clinic-os-secure-by-design/20-product-requirements.md
  - clinic-os-secure-by-design/21-technical-design.md
---

# Feature 03: Clinical Records and Consultations

## 1. Overview & Purpose
Maintain the medical history, consultation encounters, SOAP notes, vital observations, and uploaded clinical documents for each patient within a tenant.

**Core Clinical & Legal Invariant:**
A signed clinical note is **strictly immutable**. In-place `UPDATE` or `DELETE` on a signed note is impossible at both the API and database levels. All amendments and corrections spawn **new version records** that maintain explicit provenance linking back to the original version.

---

## 2. Personas & User Stories

### Story 3.1: Authoring and Signing Clinical Encounter Notes
- **As a** Treating Doctor / Nurse Practitioner
- **I want to** record subjective/objective notes and finalize the encounter with a cryptographic sign-off
- **So that** the clinical assessment is permanently and legally recorded.
  - *Clinical Safety Criterion:* Authoring is identity-bound to the authenticated clinician. Notes in `DRAFT` state can be edited; once `SIGNED`, the record locks permanently.
  - *Audit Criterion:* Emits `CLINICAL_NOTE_CREATED` and `CLINICAL_NOTE_SIGNED` recording clinician ID, patient ID, and SHA-256 hash of the note content.

### Story 3.2: Amending an Immutable Note
- **As a** Treating Clinician
- **I want to** append a clarification or error correction to a previously signed note
- **So that** the patient's record reflects new information without erasing what was previously recorded.
  - *Clinical Safety Criterion:* Amendments create a new version with an explicit reason; the original signed note remains retrievable in its exact historical state.
  - *Audit Criterion:* Emits `CLINICAL_NOTE_AMENDED` with amendment reason and previous version reference.

### Story 3.3: Viewing Clinical Records with Treating Relationship Verification
- **As a** Consulting Doctor
- **I want to** load the complete timeline of previous encounters and vital observations
- **So that** I make informed treatment decisions during the consultation.
  - *Security Criterion:* Query must resolve in < 200ms p95 under pilot load. Server-side check confirms active treating relationship before returning PHI.
  - *Audit Criterion:* Emits `CLINICAL_RECORD_VIEWED`. Audit metadata never contains clinical text.

---

## 3. API Endpoints (Deny-by-Default)

| Method | Endpoint | Required Permission | Step-Up? | Audit Event |
|---|---|---|:---:|---|
| `GET` | `/api/v1/patients/{patient_id}/encounters` | `clinical_record:read` | No | `ENCOUNTER_LIST_VIEWED` |
| `POST` | `/api/v1/patients/{patient_id}/encounters` | `clinical_record:create` | No | `ENCOUNTER_STARTED` |
| `GET` | `/api/v1/encounters/{id}` | `clinical_record:read` | No | `CLINICAL_RECORD_VIEWED` |
| `POST` | `/api/v1/encounters/{id}/notes` | `clinical_record:create` | No | `CLINICAL_NOTE_CREATED` |
| `POST` | `/api/v1/notes/{id}/sign` | `clinical_record:create` | **Yes** | `CLINICAL_NOTE_SIGNED` |
| `POST` | `/api/v1/notes/{id}/amend` | `clinical_record:amend` | **Yes** | `CLINICAL_NOTE_AMENDED` |
| `POST` | `/api/v1/patients/{patient_id}/documents` | `clinical_record:create` | No | `DOCUMENT_UPLOADED` |
| `GET` | `/api/v1/documents/{id}/presigned-url` | `clinical_record:document:read` | No | `DOCUMENT_VIEWED` |

---

## 4. Database Schema & Immutable Versioning

```sql
-- 1. Encounters Table
CREATE TABLE clinical_encounters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    clinic_id UUID NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
    practitioner_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    encounter_type VARCHAR(50) NOT NULL, -- TELEHEALTH, IN_PERSON, ASYNC_REVIEW
    status VARCHAR(30) NOT NULL DEFAULT 'IN_PROGRESS', -- IN_PROGRESS, COMPLETED, CANCELLED
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_encounters_patient ON clinical_encounters(tenant_id, patient_id);

-- 2. Clinical Notes (Immutable Root + Versions)
CREATE TABLE clinical_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    encounter_id UUID NOT NULL REFERENCES clinical_encounters(id) ON DELETE RESTRICT,
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
    author_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    is_signed BOOLEAN NOT NULL DEFAULT FALSE,
    signed_at TIMESTAMPTZ,
    signed_by UUID REFERENCES users(id),
    signature_digest CHAR(64),          -- SHA-256 of finalized content
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE clinical_note_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    note_id UUID NOT NULL REFERENCES clinical_notes(id) ON DELETE RESTRICT,
    version_number INTEGER NOT NULL DEFAULT 1,
    subjective TEXT,                    -- Chief complaint & patient history
    objective TEXT,                     -- Physical examination & observations
    assessment TEXT,                    -- Clinical impression & diagnosis
    plan TEXT,                          -- Treatment plan & follow-up
    amendment_reason TEXT,              -- Required if version_number > 1
    authored_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_note_version UNIQUE (note_id, version_number)
);

-- RLS Backstop
ALTER TABLE clinical_encounters ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_encounters FORCE ROW LEVEL SECURITY;
ALTER TABLE clinical_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_notes FORCE ROW LEVEL SECURITY;
ALTER TABLE clinical_note_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_note_versions FORCE ROW LEVEL SECURITY;

CREATE POLICY encounters_tenant_isolation ON clinical_encounters
    FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY notes_tenant_isolation ON clinical_notes
    FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY versions_tenant_isolation ON clinical_note_versions
    FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
```
