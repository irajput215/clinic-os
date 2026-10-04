---
doc_id: FEAT-TEN-01
title: Tenancy and clinics, data and audit
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 04-database-erd, 06-authentication-rbac
---

# Tenancy and clinics: data and audit

## The seven classification levels
From `12-data-classification.md` §1, which defines **seven** — no column is unclassified.

| Level | Definition | Tenant/clinic example |
|---|---|---|
| PUBLIC | Approved for release to anyone; no harm on disclosure | Public clinic address and opening hours |
| INTERNAL | ClinicOS staff and contracted operators; minor operational harm | `tenants.id`, `slug`, `status`, `data_region`, timestamps |
| CONFIDENTIAL | Harms an organisation, a clinic or a commercial relationship | `tenants.legal_name`, `tenants.retention_profile`, credential references |
| SENSITIVE | Harms an individual or a clinic; not itself health information | `tenant_id` on tenant-scoped tables, audit events, access records |
| HEALTH_INFORMATION | Health, health services or healthcare identifiers | Patient identifiers referenced by `resource_id`, in the audit trail |
| HIGHLY_SENSITIVE | Health information with high risk of serious harm, discrimination or stigma | Clinical notes, prescriptions, TGA approval records |
| SECRET | Disclosure grants access or defeats a control | Database credentials, signing keys, MFA seeds, session signing keys |

The ladder is a containment ladder: each level is a superset of the controls above it (`12 §1`).

## Field classification

`In logs` is the application log; `In analytics` is any aggregate or reporting pipeline. Per `12 §4`,
HIGHLY_SENSITIVE and SECRET **never** reach a log or an analytics pipeline.

| Field | Table | Level | In logs | In analytics | Notes |
|---|---|---|---|---|---|
| `id` | `tenants` | INTERNAL | yes | aggregate only | identifier only |
| `slug` | `tenants` | INTERNAL | yes | aggregate only | routing only; never an authorisation input |
| `legal_name` | `tenants` | CONFIDENTIAL | with tenant context | aggregate only | the practice entity |
| `status` | `tenants` | INTERNAL | yes | aggregate only | enforced at resolution on every request |
| `data_region` | `tenants` | INTERNAL | yes | aggregate only | `ap-southeast-2` only in this release |
| `retention_profile` | `tenants` | CONFIDENTIAL | with tenant context | **never** | named retention schedule |
| `created_at`, `updated_at` | `tenants` | INTERNAL | yes | aggregate only | |
| `tenant_id` | every tenant-scoped table | SENSITIVE | yes, with tenant context | aggregate only | the isolation key; not a secret, not public (`12 §3`) |
| `clinics.*` | `clinics` | **OPEN** | unknown | unknown | The ERD does not specify the `clinics` column set, so no level is assigned. Not invented. Owner: Head of Platform + Privacy Officer. |

Classification is declared at schema level and enforced by CI (`12 §6`). The legal characterisation of
each field as personal or sensitive information is a legal question, not an engineering one:
**REQUIRES LEGAL/REGULATORY VALIDATION**, owner Privacy Officer.

## Residency
All fields are stored and processed in Australia, `ap-southeast-2`, unless a documented transfer
satisfies all five conditions in `13-data-residency.md` §1. No third party receives tenant or clinic
data in the MVP. A move to schema- or database-per-tenant, and any per-tenant encryption key
requirement, is **REQUIRES LEGAL/REGULATORY VALIDATION** (owner Commercial Lead + Security Lead).

## Audit events emitted

| Event | Trigger | Key fields (no clinical payload) | Result values |
|---|---|---|---|
| `tenant.viewed` | a tenant identity or metadata read | actor, tenant, `resource_type = TENANT`, request ID | `SUCCESS` |
| `tenant.config_changed` | a security setting change with step-up | actor, tenant, `changed_fields` (names only), step-up flag | `SUCCESS`, `DENIED` |
| `clinic.created` | a clinic created inside a tenant | actor, tenant, clinic ID | `SUCCESS`, `DENIED` |
| `clinic.updated` | a clinic renamed or edited | actor, tenant, clinic ID, `changed_fields` (names only) | `SUCCESS`, `DENIED` |
| `TENANT_CROSS_ACCESS_ATTEMPT` | a client-supplied `tenant_id` is dropped, or a cross-tenant resource is addressed | actor, resolved tenant, attempted action, `reason`, `source_ip`, request ID | `DENIED` |

**Naming conflict, recorded not resolved.** `07-audit-architecture.md` §1 uses lowercase dot form
(`tenant.security_config_change`); `20-product-requirements.md` §1 uses `UPPER_SNAKE`
(`TENANT_SETTING_CHANGED`, `CLINIC_CREATED`, `CLINIC_UPDATED`). This document uses the five catalogue
names above and maps them to the source; **reconciliation is OPEN** with owner CTO. A `CLINIC` value is
absent from the closed `resource_type` enum in `07 §2` — **OPEN**, owner CTO.

## The standard envelope
Every event above carries the envelope from `07-audit-architecture.md` §2:
`event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result,
reason, source_ip, request_id, correlation_id` plus the tamper-evidence pair `prev_hash, hash`.
`event_id` is assigned by the writer, never the caller; `tenant_id` comes from the request context, never
the body; `reason` is a controlled code unless the actor typed a justification. The envelope carries no
clinical payload. The audit store is append-only: the app role holds `INSERT` and `SELECT` only, and
**denied and failed attempts are audited with the same fidelity as successes**.

## Retention
- Audit events for this module are SENSITIVE; 12 months is the recommended minimum, longer if the log
  forms part of the clinical record (`14-retention-and-deletion.md` §2).
- `tenants`, `clinics` and `tenant_settings` retention is **not** in the published schedule.
  **REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy Officer.
- Working assumption for design only: a tenant with retention obligations is soft-deleted; its data
  remains under the retention schedule. The ERD status vocabulary has no `DELETED` value, so the
  mechanism is **OPEN** (owner CTO + Privacy Officer).

## Open items
| Item | Owner | Status |
|---|---|---|
| `clinics` field classification | Head of Platform + Privacy Officer | OPEN |
| Audit action-name form (`tenant.config_changed` vs `TENANT_SECURITY_CONFIG_CHANGED`) | CTO | OPEN |
| No `CLINIC` value in the `resource_type` enum | CTO | OPEN |
| Retention for `tenants`, `clinics`, `tenant_settings`, and their audit events | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Tenant soft-delete mechanism against the four-value status vocabulary | CTO + Privacy Officer | OPEN |
