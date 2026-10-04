# Threat Model: Clinical Records and Consultations

## 1. Scope & Healthcare Regulatory Exposure
- **Protected Assets**: Consultation SOAP notes, pathology documents, clinical assessments, treatment plans.
- **Regulatory Frameworks**: Health Records Acts (NSW HRIPA 2002, VIC Health Records Act 2001), Privacy Act 1988 (Cth), Medical Board of Australia Code of Conduct (Good Medical Practice).

## 2. STRIDE Assessment Matrix

| Threat ID | STRIDE Category | Threat Description | Control / Mitigation | Residual Risk | Owner |
|:---:|---|---|---|:---:|---|
| **T-03.1** | **Spoofing** | Attacker impersonates doctor to author or sign medical advice. | Session validation re-checks user role `DOCTOR` on server; signing requires step-up auth challenge. System accounts cannot author notes. | Low | Security Lead |
| **T-03.2** | **Tampering** | Clinician alters a medical note after an adverse event to conceal diagnostic error. | `clinical_notes.is_signed = TRUE` triggers database trigger/application check forbidding updates. Amendments create distinct version records. | Low | Clinical Safety Officer |
| **T-03.3** | **Repudiation** | Doctor claims they did not author or authorize a treatment plan. | Signature generates an immutable SHA-256 digest of the note content, stored with `signed_by`, timestamp, and client IP in `audit_log`. | Negligible | CTO |
| **T-03.4** | **Information Disclosure** | Clinical note text leaked into server logs or audit tables. | Application logger explicitly filters `subjective`, `objective`, `assessment`, and `plan` fields. Audit envelope records record ID and hash only. | Low | Security Lead |
| **T-03.5** | **Information Disclosure** | Direct S3 object path access allows downloading uploaded clinical PDFs. | S3 bucket is private (block all public access). Files are served exclusively via short-lived (15-minute) KMS-encrypted presigned URLs. | Low | Platform Lead |
| **T-03.6** | **Denial of Service** | Deep unindexed joins on clinical note versions degrade encounter loading. | Compound indexing on `(tenant_id, encounter_id)` and `(tenant_id, patient_id)`. Versions partitioned by note ID. | Low | Platform Lead |
