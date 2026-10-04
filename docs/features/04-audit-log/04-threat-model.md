---
doc_id: FEAT-AUD-04
title: Audit log, threat model
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 07-audit-architecture, 21-technical-design, 26-security-gates
source:
  - clinic-os-secure-by-design/07-audit-architecture.md §3, §4, §7, §9, §10, §11, §12
  - clinic-os-secure-by-design/04-database-erd.md §9
  - clinic-os-secure-by-design/26-security-gates.md §3
  - clinic-os-secure-by-design/29-operations-and-observability.md §5
  - clinic-os-secure-by-design/18-incident-response.md
  - OWASP Top 10:2025 A09 Security Logging and Alerting Failures
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Threat model

## Scoring

`Risk = Likelihood (1–5) × Impact (1–5)`. Bands: **Low ≤4 · Medium 5–9 · High 10–16 · Critical ≥17**.
Owner is a named role, never "the dev team". A row with no source control is an OPEN item, not a
control.

| ID | STRIDE | Threat & attack path | Inherent | Control | Residual | Owner | Source |
| --- | --- | --- | :---: | --- | :---: | --- | --- |
| **T-AUD-1** | Tampering | **Insider edits or deletes an audit row** to remove their own access to a record. Direct SQL as the app role: `UPDATE audit_log SET reason=…` or `DELETE FROM audit_log`. | Critical (4×5=20) | `GRANT SELECT, INSERT` only to `clinos_app`; `REVOKE UPDATE, DELETE, TRUNCATE`; no `UPDATE` or `DELETE` policy exists; `42501 insufficient_privilege` at the engine; repo lint rule fails the build on an `UPDATE audit_log` string | **Low (1×4=4)** | Security Lead | `07 §3; 04 §9; Gate 2` |
| **T-AUD-2** | Elevation of privilege | **A migration or app path widens the app role's grants** — `GRANT UPDATE` added "temporarily", a new role with `DELETE`, or the app role promoted toward ownership. | High (3×4=12) | `information_schema.role_table_grants` inspection after **every** migration in CI asserting exactly `{SELECT, INSERT}`; app role is a non-owner with no `BYPASSRLS`; `FORCE ROW LEVEL SECURITY` applies to the owner too; a control change needs CTO + Security Lead approval | **Low (1×4=4)** | Security Lead | `07 §3; 05 §4; Gate 2; 17 §9` |
| **T-AUD-3** | Repudiation | **A failed audit write is swallowed** — the writer catches the exception to "keep the clinical change", so an action happens with no evidence and the actor plausibly denies it. | Critical (4×5=20) | Audit row and domain change in one transaction; a failure fails the operation and rolls back to `500`; no orphan event survives a rollback; SEV2 alert on any failed audit write | **Low (1×4=4)** | Security Lead | `07 §5, §11; 21 §4; 29 §5` |
| **T-AUD-4** | Information disclosure | **PHI leaks into the audit payload** — a developer adds `patient_name`, `medicine_name`, `directions` or `approval_number` to `metadata`, turning the trail into a second copy of the medical record. | High (4×4=16) | Per-action `metadata` allow-list enforced by type and by a runtime schema check before insert; an unlisted key throws, request fails `500 AUDIT_PAYLOAD_REJECTED`; `reason` captured but never written to a log line; payload review at every new action | **Low (1×4=4)** | Clinical Safety Officer | `07 §7, §11; 12 §3, §4` |
| **T-AUD-5** | Tampering | **Log injection through an unsanitised field** — a newline, control character or forged envelope fragment in `reason`, `action` or a resource identifier corrupts the JSONL export or forges an apparent event boundary. | High (3×4=12) | Canonical JSON serialisation (sorted keys, UTF-8); structured JSONL rather than concatenated text; `action` from a closed vocabulary; `reason` a controlled code unless an actor typed a justification, which is escaped by the serialiser and never rendered into a log line | **Medium (2×4=8)** | Security Lead | `07 §2, §7, §10; OWASP A09` |
| **T-AUD-6** | Tampering | **Hash-chain breakage** — a row is modified or deleted at the source, the chain is recomputed by an attacker, or a sequence gap appears so that tamper evidence is silently lost. | Critical (3×5=15) | `SHA-256(canonical_json(without hash) ‖ prev_hash)`; genesis 64 zeroes; continuous verification of the last 24 h every 15 min; full-chain scheduled verification with a signed report; a break stops the export upload and raises a P1 incident; the Object Lock copy cannot be rewritten | **Low (1×5=5)** | Security Lead | `07 §10; 18; 21 §4` |
| **T-AUD-7** | Tampering | **The retention job over-deletes** — a partition drop or purge runs against a partition under legal hold, or outside the retention window, destroying evidence that was required. | Critical (3×5=15) | Retention runs as `clinos_retention` with drop-only rights and **no** row-level delete path; legal-hold check precedes every drop and fails closed if it cannot be evaluated; the hold and the release are themselves audit events; expiry operates on whole partitions, never individual rows | **Medium (2×5=10)** | Head of Legal and Compliance | `07 §9; 14 §3.2, §3.6; 12 §3` |
| **T-AUD-8** | Information disclosure | **Cross-tenant audit read** — an auditor at tenant A enumerates tenant B identifiers through the read API or the export bundle. | High (3×4=12) | RLS with `FORCE ROW LEVEL SECURITY` and `NULLIF(current_setting('app.tenant_id', true), '')::uuid`; two policies only; export bundle tenant-scoped; a foreign event id returns `404`, never `403`; an unset tenant matches no rows | **Low (1×4=4)** | Security Lead | `07 §3, §8, §12 tests 3, 13; 05 §5` |
| **T-AUD-9** | Repudiation | **An audit-read purpose code is not required for every filter** — the trail records that a read happened but not why, weakening an access-accounting answer. | Medium (3×3=9) | `patient.read` and `clinical_record.read` carry `purpose` and `care_relationship_id`; every audit read is itself audited with its filters | **Medium (2×3=6)** | Privacy Officer | `07 §1, §8` — no source control for query-only reads; tracked as 01-requirements OPEN-6 |
| **T-AUD-10** | Information disclosure | **Break-glass platform access reads a tenant trail** without the tenant knowing, or without a review, so oversight access is invisible. | High (3×4=12) | Time-boxed break-glass grant with notification and its own audit event; platform staff cannot read a trail without it; bucket policy denies deletion to all but the audited break-glass role; retrospective review | **Low (2×4=8)** | Security Lead | `07 §5, §8; 29 §5` — procedure tracked as 01-requirements OPEN-5 |

## Assumptions

- Single database, modular monolith, RLS enabled; the app connects as `clinos_app`, never as the owner.
- The audit trail outlives the application: the immutable export is the copy that survives a
  compromised application server.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| T-AUD-7 residual is Medium and OPEN until the retention period per jurisdiction is confirmed | Head of Legal and Compliance | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| T-AUD-9 purpose-code requirement for query-only reads | Privacy Officer | OPEN |
| Break-glass procedure and approver | Security Lead | OPEN |
| Whether S3 Object Lock `COMPLIANCE` mode is acceptable to the first enterprise customer | CTO | OPEN |
| Signed verification report format and where the signing key lives | Security Lead | OPEN |
