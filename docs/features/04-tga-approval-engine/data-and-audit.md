# Data Classification and Audit Ledger: TGA Approval Engine

## 1. Field-Level Classification (Doc 12 Alignment)

| Field Name | Classification Level | Storage & Encryption | Redaction in Logs | Export Policy |
|---|---|---|:---:|---|
| `tga_category` | **RESTRICTED** | Standard RDS | Unredacted | TGA 6-monthly reporting |
| `dosage_form` | **RESTRICTED** | Standard RDS | Unredacted | TGA 6-monthly reporting |
| `validity_interval` | **RESTRICTED** | Standard RDS | Unredacted | Auditable |
| `tga_application_number` | **RESTRICTED** | AES-256 | Unredacted | TGA regulatory audit |
| `source_document_id` (PDF) | **HIGHLY RESTRICTED** | S3 KMS SSE-KMS | Path masked | Presigned URL only |
| `revocation_reason` | **RESTRICTED** | Standard RDS | Unredacted | Clinical compliance review |

---

## 2. Retention and Reporting Obligations (Doc 14 Alignment)
- **TGA Six-Monthly Reporting**: Regulation requires prescribers to report unapproved therapeutic goods supply biannually (January and July). Stored approvals and matching prescription events must be retrievable for 7 years.
- **Audit Immobility**: An approval record (even when revoked or expired) is never deleted while the patient's record is active.

---

## 3. Audit Event Catalogue for Feature 04

| Event Name | Trigger Condition | Severity | Audit Envelope Payload |
|---|---|:---:|---|
| `TGA_APPROVAL_CREATED` | New approval entered in pending state | INFO | `approval_id`, `patient_id`, `category`, `dosage_form` |
| `TGA_APPROVAL_VERIFIED` | Clinician verifies and transitions to `ACTIVE` | **NOTICE** | `approval_id`, `verified_by`, `validity_interval` |
| `TGA_APPROVAL_REJECTED` | Pending approval rejected due to discrepancy | WARN | `approval_id`, `rejection_reason` |
| `TGA_APPROVAL_REVOKED` | Active approval prematurely cancelled | **ALERT** | `approval_id`, `revoked_by`, `reason` |
| `TGA_APPROVAL_MATCHED` | Safety gate successfully matches active approval | INFO | `approval_id`, `date_of_service`, `category` |
| `TGA_APPROVAL_MATCH_FAILED` | Safety gate halts prescription (no active approval) | **ALERT** | `patient_id`, `category`, `dosage_form`, `reason` |
