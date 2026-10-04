---
doc_id: FEAT-PAT-04
title: Patients, threat model
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Threat model & residual risk register

## Risk-scoring method (5×5)
$$\text{Risk Score} = \text{Likelihood (1--5)} \times \text{Impact (1--5)}$$

* **Low (L):** 1–4 — acceptable; monitored by standard telemetry.
* **Medium (M):** 5–9 — managed; requires automated CI test verification.
* **High (H):** 10–16 — serious; must be mitigated before pilot deployment.
* **Critical (C):** ≥17 — blocks release outright.

## STRIDE assessment

| ID | STRIDE | Threat & attack path | Inherent | Control / mitigation | Residual | Owner | Source |
|---|---|---|---|---|---|---|---|
| **T-05.1** | Info Disclosure | **Bulk scraping through search:** an authenticated user iterates demographic filters to harvest the tenant's patient list. | High (4×4=16) | `patient:read` plus the treating-relationship filter; cursor pagination capped; per-tenant quota; bulk-read anomaly alert; `search.autocomplete_tenant_scoped` (I-025). | **Medium (2×4=8)** | Security Lead | `03-threat-model.md` §5; `27-security-testing.md` §2.2 |
| **T-05.2** | Info Disclosure | **Wildcard / `LIKE` abuse:** `%` or `_` injected into a name filter broadens the result set to the whole tenant. | High (3×4=12) | `%` and `_` escaped before the parameter is bound; closed sort-column mapping; result cap; tenant predicate added by the repository. | **Low (1×4=4)** | Security Lead | `02-security-architecture.md` §9; `04-database-erd.md` §7 |
| **T-05.3** | Info Disclosure | **Cross-tenant IDOR:** an authenticated user substitutes another tenant's patient id. | Critical (4×5=20) | Tenant from the verified session; RLS `FORCE` + `NULLIF`; explicit ownership check; **`404`, never `403`**; I-001…I-004. | **Low (1×4=4)** | Security Lead | `03-threat-model.md` §5; `05-tenant-isolation.md` §8 |
| **T-05.4** | Info Disclosure | **PHI in error messages and logs:** a Medicare number, IHI or name reaches a log line, stack trace or error body. | High (4×4=16) | `HIGHLY_SENSITIVE` never logged; redaction before the sink; error envelope carries `request_id` only; sentinel log-leak tests; `patient.read` payload carries field names, not values. | **Low (1×4=4)** | Security Lead | `12-data-classification.md` §2, §5.2; `02-security-architecture.md` §7 |
| **T-05.5** | Info Disclosure | **Blind-index equality leakage:** anyone with database read access plus the index key learns that two rows share an identifier. | High (3×4=12) | Keyed HMAC with restricted key custody; equality accepted **only** for high-entropy identifiers and rejected for date of birth or postcode; blind index never serialised in a response. | **Medium (2×3=6)** — accepted | Security Lead | `02-security-architecture.md` §5.1 consequence 2 |
| **T-05.6** | Tampering / Repudiation | **Merge as a data-hiding vector:** an insider merges a record into another to bury a history or an error, then denies it. | Critical (4×5=20) | Step-up plus `patient:merge`; reason required; both original identifiers preserved; reversal is a designed, audited procedure; no data destruction. | **Low (1×5=5)** | Clinical Safety Officer | `22-user-stories.md` US-14; `20-product-requirements.md` §3 |
| **T-05.7** | Tampering | **Hard deletion of medical history:** an insider or a compromised app deletes a patient row or truncates the table. | High (3×5=15) | `REVOKE DELETE, TRUNCATE` from `clinos_app`; no delete endpoint; deletion only through the approved retention role; grant-inspection test fails CI on drift. | **Low (1×4=4)** | Privacy Officer | `04-database-erd.md` §6, §9; `05-tenant-isolation.md` §4 |
| **T-05.8** | Info Disclosure | **Enumeration through duplicate detection:** an attacker probes identifier values and reads the candidate list to confirm whether a person is a patient. | High (3×4=12) | Tenant-scoped, **exact-match only** on the blind index; candidate response masked; rate-limited per identity; every refusal audited with `result=DENIED`. | **Low (1×4=4)** | Security Lead | `20-product-requirements.md` §3; `12-data-classification.md` §3 |
| **T-05.9** | Elevation of Privilege | **Read outside the treating relationship:** a colleague in the same tenant browses a record with no active care relationship. | High (3×4=12) | Relationship check in the central policy facade; `patient.read` permission; per-patient access history; `authz.care_relationship_denied` test. | **Medium (2×4=8)** — insider risk inherent | Practice Owner | `06-authentication-rbac.md` §10; `03-threat-model.md` §5 |
| **T-05.10** | Spoofing | **Stolen session:** a hijacked session reads records at scale. | High (4×4=16) | Short-lived access tokens, MFA for clinical and administrative roles, server-side revocation, access anomaly alerting. | **Medium (2×3=6)** | Security Lead | `02-security-architecture.md` §1; `06-authentication-rbac.md` §3 |
| **T-05.11** | Repudiation | **Viewer denies access:** a clinician denies having viewed or searched a record. | High (3×4=12) | `patient.read` written in the same transaction for reads **and denials**; per-patient access history; append-only hash-chained audit. | **Low (1×3=3)** | Security Lead | `07-audit-architecture.md` §1, §3 |
| **T-05.12** | Tampering | **Mass assignment:** extra body fields set `medicare_blind_index`, `merged_into_patient_id` or `deleted_at`. | High (3×4=12) | Strict Pydantic v2 schema, unknown fields rejected; column allow-list in the update statement; no entity spread. | **Low (1×4=4)** | CTO | `02-security-architecture.md` §1 control 4; `27-security-testing.md` §2.5 |
| **T-05.13** | Denial of Service | **Search or export flood:** repeated expensive searches exhaust the connection pool. | Medium (3×3=9) | Token-bucket rate limit per identity and tenant; pagination ceiling; export asynchronous, capped and re-authorised at download. | **Low (2×2=4)** | Head of Platform | `02-security-architecture.md` §11; `27-security-testing.md` §2.5 |

## Assumptions
- Single database, modular monolith, RLS enabled and forced; the app role is not the table owner.
- Identity is federated to a managed provider, not hand-rolled.
- Search runs on plaintext name and date-of-birth columns under RLS; identifier search is exact-match only.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| `care_relationships` is undefined, so T-05.9 cannot be fully evidenced | Clinical Safety Officer | **OPEN — blocked** |
| Is the residual equality leakage in T-05.5 accepted per tenant or globally? | Security Lead + Privacy Officer | OPEN |
| Whether merge reversal must remain available after a clinical event | Clinical Safety Officer | OPEN |
| Rate-limit values for the search and duplicate-candidate routes | Head of Platform | OPEN |
