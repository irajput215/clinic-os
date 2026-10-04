---
doc_id: OZ-FEAT-04-THREAT
title: "FEAT-04 — TGA Approval Module: STRIDE Threat Model & Residual Risk Register"
owner: Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-04
phase: 02-phase-2-tga-approval-engine
gate: [2, 4]
source:
  - Therapeutic Goods Act 1989 (Cth)
  - clinic-os-secure-by-design/03-threat-model.md §7, §12, §13
  - clinic-os-secure-by-design/04-database-erd.md §3.6, §8, §9
  - clinic-os-secure-by-design/08-tga-approval-model.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Threat Model & Residual Risk Register

## Risk Assessment Methodology (5×5 Matrix)

Risk score is computed as:
$$\text{Risk Score} = \text{Likelihood (1--5)} \times \text{Impact (1--5)}$$

* **Residual-Risk Bands:**
  * **Low (L):** $1 - 4$ (Acceptable residual risk; monitored via standard telemetry)
  * **Medium (M):** $5 - 9$ (Managed risk; requires automated CI test verification)
  * **High (H):** $10 - 16$ (Serious risk; must be mitigated before pilot deployment)
  * **Critical (C):** $17 - 25$ (Catastrophic clinical/regulatory risk; **blocks release outright**)

---

## STRIDE Assessment & Residual Risk Matrix

| ID | STRIDE | Threat & Attack Path | Inherent Risk | Control / Mitigation | Residual Risk | Owner | Source |
|---|---|---|:---:|---|:---:|---|---|
| **T-04.1** | **Spoofing** | **Stolen Session / Credential:** Attacker uses hijacked session to create or verify approvals. | High (4×3=12) | Short-lived JWT sessions, MFA enforcement, server-enforced step-up re-authentication within 15 min for `verify` and `revoke`. | **Low (2×2=4)** | Security Lead | `03 §7 row 1; 06 §4` |
| **T-04.2** | **Spoofing** | **Forged Approval / Reference:** Attacker creates plausible fake approval number to release unapproved drugs. | Critical (4×5=20) | Manual entry lands `pending_verification`; requires clinical four-eyes verification by qualified doctor/CSO with source PDF before reaching `active`. | **Low (2×2=4)** | Clinical Safety Officer | `08 §3, §4; 11 §3` |
| **T-04.3** | **Tampering** | **Retrospective Date Tampering:** Insider extends `valid_to` via SQL or API on an active approval. | High (4×4=16) | Once `active`, row is immutable. `trg_tga_approval_lock_verified` trigger blocks core field updates; extensions require a new grant that supersedes. | **Low (1×4=4)** | CTO | `03 §13; 08 §5; D-006` |
| **T-04.4** | **Tampering** | **Overlapping Active Approvals:** Ambiguity from multiple active approvals at the same grain causes safety gate miscalculation. | High (3×4=12) | Partial GiST exclusion constraint `no_overlapping_active_approvals` on `(tenant_id, patient_id, category, dosage_form, daterange) WHERE status = 'active'`. | **Negligible (1×4=4)** | CTO | `04 §3.6; 20 §5; D-006` |
| **T-04.5** | **Tampering** | **Database History Rewrite:** Malicious actor deletes records or drops audit trail. | Critical (3×5=15) | Non-owner app role (`clinos_app`); `REVOKE DELETE, TRUNCATE` on `tga_approval`; `GRANT SELECT, INSERT` only on `tga_approval_events`. Verified by CI test. | **Low (1×4=4)** | Security Lead | `04 §9; 07 §3` |
| **T-04.6** | **Repudiation** | **Verifier Denies Action:** Practitioner claims they did not authorise an off-label prescription. | High (3×4=12) | Step-up auth captures actor, IP, timestamp, role at decision time, and writes append-only row to `tga_approval_events` in the same DB transaction. | **Low (1×4=4)** | Compliance Lead | `07 §5; 03 §7` |
| **T-04.7** | **Info Disclosure** | **Cross-Tenant IDOR / Enumeration:** Attacker probes UUIDs or enumerates IDs to detect another clinic's patient approvals. | High (3×4=12) | Tenant-scoped RLS (`NULLIF(current_setting('app.tenant_id', true), '')::uuid`), `FORCE ROW LEVEL SECURITY`, random UUIDv4, and returns `404 Not Found` (never `403`). | **Low (1×4=4)** | Security Lead | `03 §12; 04 §8` |
| **T-04.8** | **Info Disclosure** | **PHI / Clinical Leak into Logs:** Category or dosage details leak into observability/log sinks. | High (4×3=12) | Data classification: `category`, `dosage_form` classified `HIGHLY_SENSITIVE`. Log sanitization, strict Pydantic serialisation, no error body leak. | **Low (2×2=4)** | Security Lead | `12 §2, §3; 07 §7` |
| **T-04.9** | **Elevation of Priv** | **Unauthorised Verification:** Non-clinical staff (admin, receptionist) verifies an approval to clear backlog. | Critical (4×5=20) | Central RBAC policy checks `tga_approval:verify` restricted to `DOCTOR` or `CLINICAL_SAFETY_OFFICER`. Checked server-side on route entry. | **Low (1×4=4)** | Clinical Safety Officer | `06 §4; 20 §5` |
| **T-04.10** | **Elevation of Priv** | **Self-Verification (Conflict of Interest):** Prescriber verifies their own approval without four-eyes oversight. | High (4×4=16) | Database constraint `CHECK (verified_by IS NULL OR verified_by <> created_by)` and service layer rejection `403 VERIFIER_CANNOT_BE_CREATOR`. | **Low (1×4=4)** | Clinical Safety Officer | `20 §5; 23 §4` |
| **T-04.11** | **Elevation of Priv** | **Bypass of Safety Gate:** Prescription released despite expired or mismatched approval. | Critical (4×5=20) | Gate evaluates all 4 dimensions plus `date_of_service` server-side; client cannot assert validity; database failure causes immediate fail-closed denial. | **Low (1×4=4)** | Clinical Safety Officer | `09 §3; 27 §2.3` |
| **T-04.12** | **Denial of Service** | **Bulk Import / Flood:** Exhausts database pool or API worker capacity. | Medium (3×3=9) | Token-bucket rate limiting (sensitive-write tier: 10 req/min per IP/user), pagination ceiling (`limit <= 100`). | **Low (2×2=4)** | Head of Platform | `03 §12` |

## Assumptions
- Single database, modular monolith, RLS enabled.
- Identity is provided by a library or managed provider, not hand-rolled (see D-003).

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Whether an approval verified by mistake can be reversed, and how | CSO | OPEN |
| Whether OCR/extraction is in scope, and its data-processing position | Head of Product | OPEN — REQUIRES LEGAL/REGULATORY VALIDATION |
