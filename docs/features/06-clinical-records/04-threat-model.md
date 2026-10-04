---
doc_id: FEAT-CLIN-04
title: Clinical records, threat model
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Threat model & residual risk register

## Risk assessment method
$$\text{Risk Score} = \text{Likelihood (1--5)} \times \text{Impact (1--5)}$$

| Band | Score | Meaning |
| --- | --- | --- |
| **Low** | ≤ 4 | Acceptable residual; standard telemetry |
| **Medium** | 5–9 | Managed; automated CI test required |
| **High** | 10–16 | Mitigate before pilot deployment |
| **Critical** | ≥ 17 | Blocks release outright |

Inherent risk is scored before the control; residual after it. Every row names one accountable role,
never a team. Sources: `03-threat-model.md` §5 (Module 2), §8 (Module 5), §13 (forbidden failure
modes); `04-database-erd.md` §3.5, §9; `07-audit-architecture.md` §1–§3, §7; `21-technical-design.md`
§9; `22-user-stories.md` US-11–US-13.

## STRIDE assessment & residual risk matrix

| ID | STRIDE | Threat & attack path | Inherent Risk | Control / Mitigation | Residual Risk | Owner | Source |
|---|---|---|---|---|---|---|---|
| **T-CLIN-01** | Spoofing | Stolen session authors or signs a note as the treating clinician | High (4×4=16) | MFA for clinical roles, short-lived access tokens, identity-bound signing (`author_id` from the session), full attribution in audit | **Low (1×4=4)** | Security Lead | `06` §2, §10; `22` US-12 |
| **T-CLIN-02** | Spoofing | A clinician signs a version they did not author, or a forged `author_id` is submitted | High (4×4=16) | `author_id` and `signed_at` are server-set; strict schema rejects them in the body; sign route requires actor = version author, else `403` | **Low (1×4=4)** | Clinical Safety Officer | `06` §10; `22` US-12 |
| **T-CLIN-03** | Tampering | **In-place alteration of a signed note to conceal a diagnostic error** | Critical (4×5=20) | Immutability at two layers: app role holds exactly `SELECT, INSERT` on `clinical_record_versions` (R13); `BEFORE UPDATE OR DELETE` trigger for every role including owner and migration role (R14); no mutating route; corrections are new versions | **Medium (1×5=5)** | Clinical Safety Officer | `04` §3.5, §6, §9; `22` US-13 |
| **T-CLIN-04** | Tampering | **Immutability bypassed by a migration or admin path** — `clinos_migrator` or the table owner runs `UPDATE`/`DELETE` | High (3×5=15) | The trigger has no role exemption, so the owner and migration role hit `CLINICAL_RECORD_VERSION_IMMUTABLE`; forward-only expand-and-contract migrations; a CI lint fails on any `UPDATE`/`DELETE` against versions in repo SQL | **Medium (1×5=5)** | Security Lead | `04` §4, §9; D-002 |
| **T-CLIN-05** | Tampering | **Unsigned-note edit races** — two concurrent `PATCH` calls lose an update or create duplicate versions | High (3×4=12) | Append-only versions; `UNIQUE (tenant_id, clinical_record_id, version)`; retry once on unique violation, then `409 VERSION_CONFLICT`; deterministic `ORDER BY version ASC` | **Low (1×3=3)** | Engineering Lead | `04` §3.5; `20` §4 failure modes |
| **T-CLIN-06** | Repudiation | A clinician denies authoring or signing a note | High (3×4=12) | Identity-bound authoring, `author_id` and `signed_at` immutable, audit `clinical_record.write` written in the same transaction as the change | **Low (1×4=4)** | Compliance Lead | `07` §1, §5; `22` US-12 |
| **T-CLIN-07** | Repudiation / Tampering | **Insider audit-trail tampering** — an operator removes the read or write event to hide an access | Critical (3×5=15) | `audit_log` is append-only by grant (`SELECT, INSERT` only); no `UPDATE`/`DELETE` policy exists; SHA-256 hash chain; Object Lock export in a separate account; alert on audit write failure | **Low (1×4=4)** | Security Lead | `07` §3, §10; `21` §4 |
| **T-CLIN-08** | Information disclosure | **Clinical text leaking into logs** — the narrative reaches a debug line, stack trace, APM payload or crash report | High (4×4=16) | `body` is `HIGHLY_SENSITIVE`: excluded from application logs, analytics and error telemetry; allow-list logger; redaction before any sink; the error envelope carries only `request_id`; sentinel test S12 | **Low (1×4=4)** | Security Lead | `12` §2, §3, §5.2; `07` §7; `02` §7 |
| **T-CLIN-09** | Information disclosure | **Cross-tenant read of a chart** — a substituted UUID returns another clinic's clinical record | High (3×5=15) | Tenant resolved from the verified token, `FORCE ROW LEVEL SECURITY`, `NULLIF(current_setting(...))` fail-closed policy, random UUIDv4, `404` never `403` | **Low (1×4=4)** | Security Lead | `03` §5, §13; `04` §8 |
| **T-CLIN-10** | Information disclosure | A colleague inside the tenant browses a chart with **no treating relationship** — the inherent insider risk | High (4×4=16) | Relationship check in the central policy layer, never inferred from clinic membership and never widened to the tenant; every read and denial audited; per-patient access history for the practice | **Medium (2×4=8)** | Practice Owner | `03` §5, TH-015; `06` §10; `22` US-11 |
| **T-CLIN-11** | Elevation of privilege | Mass assignment sets `author_id`, `signed_at` or `version`, or a role without the permission writes a note | High (4×4=16) | Permission checked server-side on route entry; strict Pydantic v2 model rejects unknown fields; attribution columns are server-set; RBAC matrix test S6 | **Low (1×4=4)** | Clinical Safety Officer | `06` §9–§10; `27` §2.5 |
| **T-CLIN-12** | Information disclosure | The narrative is exposed through a search index, cache or analytics pipeline outside RLS | High (3×5=15) | `body` stays plaintext **under RLS only** (search is a care requirement); the full-text index is row-scoped by RLS; no cache of narrative; `HIGHLY_SENSITIVE` is never sent to analytics | **Low (1×4=4)** | Security Lead | `02` §5.1; `12` §2, §5.2 |
| **T-CLIN-13** | Denial of service | **Unindexed join denial of service** — the timeline query scans `clinical_record_versions` and exhausts the pool | High (3×4=12) | Compound indexes for the per-record and per-patient read paths; `200 ms` p95 target with 50 prior entries; cursor pagination cap; `statement_timeout`; single-resource read limit 300/min | **Low (2×2=4)** | Head of Platform | `04` §3.5; `20` §4; `02` §11 |
| **T-CLIN-14** | Elevation of privilege | Break-glass or admin elevation reads a chart with no clinical purpose | High (3×4=12) | Read still requires `clinical_record:read`; break-glass is time-boxed, reason-required, dual-notified and audited; no clinical modification under break-glass | **Medium (2×4=8)** | Security Lead | `06` §6; `22` US-11 |

## Assumptions
- Single database, modular monolith, PostgreSQL 16, RLS enabled and forced.
- Identity comes from the managed provider decision (D-003), not hand-rolled.
- `care_relationships` exists as described by `06` §10; its ERD definition is missing (OPEN-3), so
  T-CLIN-10 cannot be fully evidenced until it is defined.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| T-CLIN-04 residual: the migration role retains DDL capability; confirm the CI trigger-definition check before Gate 2 | Security Lead + CTO | OPEN |
| T-CLIN-10 cannot be fully evidenced while `care_relationships` has no ERD table | CSO + Engineering Lead | OPEN — blocked |
| Legal-hold model and its interaction with tamper evidence | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether the CSO needs standing read access for safety review, and its purpose basis | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| `signature_digest`, if adopted, introduces a forgery/replay path that is not yet modelled | Security Lead | OPEN |
