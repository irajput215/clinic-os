---
doc_id: OZ-FEAT-15-THREAT
title: "Administration and configuration — threat model"
owner: Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-15
phase: 04-phase-4-pilot-go-live
gate: [4]
source:
  - clinic-os-secure-by-design/03-threat-model.md §11 Module 8
  - clinic-os-secure-by-design/02-security-architecture.md §1 control 12, §6, §11
  - clinic-os-secure-by-design/06-authentication-rbac.md §8, §9
  - clinic-os-secure-by-design/14-retention-and-deletion.md §3
  - clinic-os-secure-by-design/21-technical-design.md §10
  - clinic-os-secure-by-design/26-security-gates.md §5 Gate 4
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Threat model and residual risk register

## Risk assessment method (5×5)

$$\text{Risk Score} = \text{Likelihood (1--5)} \times \text{Impact (1--5)}$$

- **Low:** 1–4 — acceptable residual; monitored by standard telemetry.
- **Medium:** 5–9 — managed; requires automated CI test verification.
- **High:** 10–16 — serious; must be mitigated before pilot deployment.
- **Critical:** 17–25 — catastrophic clinical or regulatory risk; **blocks release**.

## STRIDE assessment

| ID | STRIDE | Threat and attack path | Inherent | Control / mitigation | Residual | Owner | Source |
| --- | --- | --- | :---: | --- | :---: | --- | --- |
| **T-15.1** | Tampering | **Flag silently weakens a control.** An administrator flips a flag that relaxes validation or the approval path, and nothing downstream notices. | High (3×4=12) | Safety-gate keys are unrepresentable as disabled (`CHECK` plus `SAFETY_GATE_FLAG_IMMUTABLE` trigger); an `affects_safety_gate` flag requires an approval reference; the key list is an allowlist. | **Low (1×4=4)** | Clinical Safety Officer | `20 §12`; `26 §5` |
| **T-15.2** | Tampering | **Flag change with no approval reference.** A change is made without a recorded approval, so no one can show who authorised it. | High (4×4=16) | `CHECK (NOT affects_safety_gate OR approval_reference IS NOT NULL)`, service-layer rejection `422`, step-up bound to the flag resource, append-only history row. | **Low (1×4=4)** | Security Lead | `21 §10`; `20 §12` |
| **T-15.3** | Repudiation | **Administrative change not attributable.** An actor denies a configuration change; the audit write fails or is skipped. | High (3×4=12) | Audit row written in the same transaction as the change; write failure aborts the change; history tables are append-only by grant; denials audited with equal fidelity. | **Low (1×4=4)** | Compliance Lead | `07 §3`; `20 §12` |
| **T-15.4** | Elevation of privilege | **Break-glass abuse or an unexpiring elevation.** The emergency path is used for convenience, or an elevation is renewed indefinitely. | High (3×5=15) | Time-boxed, scoped elevation with server-side expiry re-checked per request; reason plus ticket reference required; dual notification; its own event type; no silent renewal; mandatory retrospective review. | **Medium (2×4=8)** | Compliance Lead | `06 §8`; `22 US-03`; `03 §11` |
| **T-15.5** | Tampering | **Retention job runs against a legal hold.** A filter error purges records under hold or open investigation. | High (2×5=10) | Dry-run by default with a manifest and count; live run requires approval by a different actor; explicit hold check before every delete; fail closed if the check cannot be evaluated; dedicated `clinos_retention` role. | **Low (1×4=4)** | Privacy Officer | `14 §3.2, §3.6`; `03 §11` |
| **T-15.6** | Elevation of privilege | **Configuration falls back to a permissive default.** A missing key resolves to a permissive value and a control quietly disappears. | High (3×4=12) | Precedence `environment → secret store → fail closed`; an absent required key refuses startup and names the key; no permissive default in code; asserted by CI. | **Low (1×4=4)** | Head of Platform | `21 §10`; `20 §12` |
| **T-15.7** | Tampering | **Stale cached flag.** A cached flag value outlives a change and an old, weaker state is applied. | Medium (3×3=9) | Cache keyed on `(tenant_id, key, version)` and invalidated on write; an unknown flag resolves to the enforcing default; a safety-gate flag has no disabled state to cache. | **Low (1×4=4)** | Head of Platform | `06 §11`; `21 §10` |
| **T-15.8** | Elevation of privilege | **Privilege escalation through the admin surface.** An actor grants themselves a permission they do not hold, or reaches a platform-scope route from a clinical role. | Critical (4×5=20) | Central policy layer recomputes per request; a grantor must already hold every permission granted (`06 §9`); platform-scope administration is not grantable to clinical roles; step-up with passkey or hardware key only. | **Low (1×4=4)** | Security Lead | `06 §9`; `20 §12`; `03 §11` |
| **T-15.9** | Information disclosure | **Secret readable through the admin surface.** A config endpoint or log exposes an API key, signing key or credential. | Critical (4×5=20) | SECRET never persists in an application column; the database stores the Secrets Manager ARN; the response schema is an allow-list; secret scanning in CI. | **Low (1×4=4)** | Security Lead | `02 §6`; `12 §1`; `20 §12` |
| **T-15.10** | Tampering | **History rewrite.** A flag, configuration or policy history row is altered or deleted to hide a change. | High (3×4=12) | `GRANT SELECT, INSERT` only on the history tables; `REVOKE UPDATE, DELETE, TRUNCATE`; a grant-inspection test runs in CI. | **Low (1×4=4)** | Security Lead | `07 §3`; `05 §4` |
| **T-15.11** | Information disclosure | **Cross-tenant admin IDOR.** An actor probes identifiers to read another tenant's configuration or policy. | High (3×4=12) | Tenant-scoped RLS with the `NULLIF` guard and `FORCE`; tenant resolved from the session; random UUIDv4; `404 Not Found`, never `403`. | **Low (1×4=4)** | Security Lead | `05 §4`; `06 §12` |
| **T-15.12** | Denial of service | **Admin route flooding.** High-volume calls to `/api/v1/admin/*` exhaust workers or mask a change. | Medium (3×3=9) | 20 requests per minute per session on `/admin/*`; alerting on a break-glass event and on cross-tenant authorisation denials. | **Low (2×2=4)** | Head of Platform | `02 §11` |

## Assumptions
- Single database, modular monolith, RLS enabled; the app role is a non-owner with no `BYPASSRLS`.
- Identity and step-up tokens are provided by feature 02, not re-implemented here.
- The safety gate (feature 10) reads flags but never writes them.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Break-glass retrospective review cadence and escalation on an unreviewed grant | Compliance Lead | OPEN |
| Cache TTL for non-safety flags and the invalidation transport | Head of Platform | OPEN |
| Whether a per-tenant flag may override a platform default, and who approves | CTO + Clinical Safety Officer | OPEN |
| Legal-hold ownership and the retention consequences of purging configuration history | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
