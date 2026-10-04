# Threat Model: Patient Register and Demographics

## 1. Scope & Healthcare Regulatory Exposure
- **Protected Assets**: Patient Health Information (PHI), Personally Identifiable Information (PII), Medicare/IHI numbers, treating relationship audit records.
- **Relevant Frameworks**: Privacy Act 1988 (Cth) Australian Privacy Principles (APPs), Notifiable Data Breaches (NDB) scheme, Healthcare Identifiers Act 2010.

## 2. STRIDE Assessment Matrix

| Threat ID | STRIDE Category | Threat Description | Control / Mitigation | Residual Risk | Owner |
|:---:|---|---|---|:---:|---|
| **T-02.1** | **Spoofing** | Compromised staff account scrapes patient database via bulk search queries. | Rate-limiting on `/patients/search` (max 30 req/min); cursor pagination capped at 50 records; step-up auth for bulk export. | Low | Security Lead |
| **T-02.2** | **Tampering** | User intentionally modifies a patient's date of birth or Medicare number to bypass prescription safety checks. | Full field-level change history kept; mutations emit `PATIENT_UPDATED` with previous vs. new values. | Low | Clinical Safety Officer |
| **T-02.3** | **Repudiation** | Clinician views unauthorized celebrity patient record and denies browsing the chart. | Every `GET /patients/{id}` executes an immutable audit insert `PATIENT_VIEWED` logging actor ID, patient ID, and IP address. | Negligible | Security Lead |
| **T-02.4** | **Information Disclosure** | Medicare numbers or IHIs exposed in application error messages or logs. | Logging filter strips patterns matching `\d{10}` (Medicare) and `800360\d{10}` (IHI). Frontend masks all but the last 4 digits. | Low | CTO |
| **T-02.5** | **Denial of Service** | Replay of massive unindexed text searches exhausts PostgreSQL CPU. | Full-text and trigram search indexed exclusively with `tenant_id` prefix; minimum query length enforced (>= 3 chars). | Low | Platform Lead |
| **T-02.6** | **Elevation of Privilege** | Receptionist uses chart merge endpoint to overwrite or hide medical alerts. | `patient:merge` permission restricted to Clinical Safety Officer / Senior Admin role; step-up authentication required. | Low | Head of Product |
