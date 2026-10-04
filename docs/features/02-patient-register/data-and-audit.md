# Data Classification and Audit Ledger: Patient Register

## 1. Field-Level Classification (Doc 12 Alignment)

All patient demographic data is classified as Health Information under Privacy Act 1988 (Cth) Section 6(1).

| Field Name | Classification Level | Storage & Encryption | Redaction in Logs | Export Control |
|---|---|---|:---:|---|
| `first_name`, `last_name` | **RESTRICTED** | AES-256 (RDS at rest) | No (Auditable identity) | Role-restricted |
| `date_of_birth` | **RESTRICTED** | AES-256 (RDS at rest) | Age only in debug logs | Role-restricted |
| `medicare_number` | **HIGHLY RESTRICTED** | AES-256 / KMS Envelope | **ALWAYS MASKED** (`******1234`) | Requires step-up auth |
| `ihi_number` | **HIGHLY RESTRICTED** | AES-256 / KMS Envelope | **ALWAYS MASKED** (`800360******1234`) | Requires step-up auth |
| `phone`, `email` | **RESTRICTED** | AES-256 | Yes (Email domain only) | Role-restricted |
| `address` | **RESTRICTED** | Encrypted JSONB | Redact street address | Role-restricted |

---

## 2. Retention and Deletion Constraints (Doc 14 Alignment)
- **Adult Records**: Must be retained for a minimum of **7 years** from the date of the last clinical service.
- **Pediatric Records**: Must be retained until the patient attains **25 years of age** (NSW HRIPA s 25, VIC Health Records Act HPP 4.2).
- **Hard Deletes Disallowed**: Requests under Privacy Act APP 12/13 for correction trigger an audited correction or archiving, never a database `DELETE`.

---

## 3. Audit Event Catalogue for Feature 02

| Event Name | Trigger Condition | Severity | Audit Envelope Payload |
|---|---|:---:|---|
| `PATIENT_CREATED` | New patient registered | INFO | `patient_id`, `clinic_id`, `duplicate_checked: true` |
| `PATIENT_VIEWED` | Patient chart or summary opened | INFO | `patient_id`, `viewing_clinician_id`, `reason: consult` |
| `PATIENT_UPDATED` | Demographics or contact info modified | NOTICE | `patient_id`, `fields_modified: [...]` (values excluded) |
| `DUPLICATE_CANDIDATE_FLAGGED` | Registration matched existing record | WARN | `candidate_patient_id`, `matched_criteria` |
| `PATIENT_MERGED` | Two charts merged into one master | **ALERT** | `source_patient_id`, `target_patient_id`, `approved_by` |
| `PATIENT_MERGE_REVERSED` | Prior merge unlinked | **ALERT** | `source_patient_id`, `target_patient_id`, `reason` |
| `PATIENT_EXPORTED` | Bulk list or chart export initiated | **ALERT** | `patient_count`, `export_format`, `step_up_token` |
