# Threat Model: TGA Approval Engine and Register

## 1. Scope & Healthcare Regulatory Exposure
- **Protected Assets**: TGA regulatory authorizations, prescription gating decisions, TGA application numbers, approval PDF letters.
- **Regulatory Frameworks**: Therapeutic Goods Act 1989 (Cth), Therapeutic Goods Regulations 1990 (Special Access Scheme B & Authorised Prescriber scheme). Criminal and civil liability attaches to dispensing unapproved goods without an active approval.

## 2. STRIDE Assessment Matrix

| Threat ID | STRIDE Category | Threat Description | Control / Mitigation | Residual Risk | Owner |
|:---:|---|---|---|:---:|---|
| **T-04.1** | **Spoofing** | Attacker fabricates a fake TGA letter number to activate prescribing rights. | Letter numbers are checked for standard TGA format; physical/digital PDF attachment is mandatory; human clinical verification is required before `ACTIVE`. | Low | Clinical Safety Officer |
| **T-04.2** | **Tampering** | Prescriber alters the `valid_to` date of an expired approval directly in DB or via API. | State transitions are server-managed; approvals are immutable once verified; extensions require a new grant record. | Low | CTO |
| **T-04.3** | **Repudiation** | Clinical Safety Officer denies approving an inappropriate category approval. | Verification requires step-up auth; `verified_by` and `verified_at` permanently saved and emitted to `audit_log`. | Negligible | Security Lead |
| **T-04.4** | **Information Disclosure** | Competitor clinics infer patient prescribing volumes by enumerating approval IDs. | Approval IDs are randomly generated UUIDv4; endpoints are protected by tenant-scoped RLS (`tenant_id = :id`). | Negligible | Security Lead |
| **T-04.5** | **Tampering / Logic Flaw** | Overlapping approvals for the same patient and category cause ambiguity in prescription validation. | Enforced at the database level by PostgreSQL `EXCLUDE USING gist (... WITH &&)` on `validity_interval`. | Negligible | CTO |
| **T-04.6** | **Elevation of Privilege** | Receptionist verifies approval letter to bypass doctor backlog. | `tga_approval:verify` permission is restricted to `CLINICAL_SAFETY_OFFICER` and `DOCTOR`. Separation of duties prevents creator self-verification. | Low | Head of Product |
