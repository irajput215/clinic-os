# Data Classification and Audit Ledger: Clinical Records

## 1. Field-Level Classification (Doc 12 Alignment)

All clinical encounter content is classified as **HIGHLY RESTRICTED** Health Information under Section 6(1) of the Privacy Act 1988 (Cth).

| Field Name | Classification Level | Storage & Encryption | Redaction in Logs | Export Policy |
|---|---|---|:---:|---|
| `subjective` | **HIGHLY RESTRICTED** | AES-256 (RDS at rest) | **STRICTLY EXCLUDED** | Requires treating relationship |
| `objective` | **HIGHLY RESTRICTED** | AES-256 (RDS at rest) | **STRICTLY EXCLUDED** | Requires treating relationship |
| `assessment` | **HIGHLY RESTRICTED** | AES-256 (RDS at rest) | **STRICTLY EXCLUDED** | Requires treating relationship |
| `plan` | **HIGHLY RESTRICTED** | AES-256 (RDS at rest) | **STRICTLY EXCLUDED** | Requires treating relationship |
| `amendment_reason` | **RESTRICTED** | AES-256 | Allowed in audit trail | Preserved in history |
| `signature_digest` | **INTERNAL** | SHA-256 hash string | Unredacted (Integrity proof) | Auditable |
| Document files (S3) | **HIGHLY RESTRICTED** | AWS S3 KMS SSE-KMS | Object URLs unguessable | Presigned URL only |

---

## 2. Retention and Legal Hold Rules (Doc 14 Alignment)

- **Standard Retention**: Clinical encounter notes must be retained for at least **7 years** from the last date of entry.
- **Pediatric Rule**: Must be retained until the patient reaches **25 years of age** if created when patient was a minor.
- **Coroner / Legal Hold**: If `legal_hold = TRUE`, automated archiving or retention expiries are suspended indefinitely.

---

## 3. Audit Event Catalogue for Feature 03

| Event Name | Trigger Condition | Severity | Audit Envelope Payload |
|---|---|:---:|---|
| `ENCOUNTER_STARTED` | Doctor initiates consultation | INFO | `encounter_id`, `patient_id`, `practitioner_id`, `type` |
| `CLINICAL_NOTE_CREATED` | Draft note saved | INFO | `note_id`, `encounter_id`, `version_number: 1` |
| `CLINICAL_NOTE_SIGNED` | Clinician executes step-up sign-off | **NOTICE** | `note_id`, `signed_by`, `signature_digest` |
| `CLINICAL_NOTE_AMENDED` | New version appended to signed note | **ALERT** | `note_id`, `version_number`, `reason`, `authored_by` |
| `CLINICAL_RECORD_VIEWED` | Patient notes timeline loaded | INFO | `patient_id`, `encounter_id`, `viewer_id` |
| `DOCUMENT_UPLOADED` | Clinical PDF or image attached | INFO | `document_id`, `patient_id`, `s3_hash`, `mime_type` |
| `DOCUMENT_VIEWED` | Presigned URL generated for viewing | NOTICE | `document_id`, `viewer_id`, `expiry_seconds: 900` |
