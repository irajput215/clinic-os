---
doc_id: OZ-REF-CM
title: Consolidated control register
owner: Compliance Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
source: ../../clinic-os-secure-by-design/17-compliance-control-matrix.md
---

# Consolidated Control Register

The single place a reviewer looks to find out whether a control is real. It consolidates the control
tables published across the source contract into one register, deduplicated, grouped by theme, and
re-expressed against the stack in [D-001](decisions/D-001-python-fastapi-stack.md).

> **Status of this repo, stated plainly.** Nothing in the ClinicOS domain exists in code. The checkout
> contains the FastAPI template (`backend/`), the frontend template (`frontend/`) and a documentation
> spine. There is no `tenant_id`, no RLS policy, no `audit_log`, no module package, no isolation suite
> and no safety gate. **No ClinicOS control is `Implemented` in this repo today.** Where a source
> document wrote `Implemented`, this register records `Planned` and cites the source row. Two
> source-contract dependencies are unresolved and block gates: [D-003](decisions/D-003-identity-model.md)
> (identity, blocks Gate 3) and [D-004](decisions/D-004-deployment-target.md) (deployment, blocks
> Gate 6). Any row that depends on them cannot advance past `OPEN`.

---

## 1. How to read this register

| Column | Meaning |
|---|---|
| Requirement | What must be true |
| Source (instrument or internal decision) | The primary instrument, or the internal decision that created the obligation. A source document is not an instrument |
| Control | The one engineering or operational control chosen for the requirement |
| Implementation | Where the control lives in the build. Names are **target** locations under the layout in [`docs/reference/build-contract.md` §7](build-contract.md#7-module-map) |
| Evidence | The artefact an auditor or a customer's security team is shown |
| Owner role | The single accountable role. A role with no person behind it is an open item |
| Status | See §2 |
| Phase | The delivery phase in which the control's implementation and evidence land. Phase 0 foundation · Phase 1 foundations · Phase 2 TGA approval engine · Phase 3 e-prescribing · Phase 4 pilot go-live. `0–1` means some work lands in Phase 0 and the evidence at the Phase 1 boundary |
| Last reviewed | The review date of this row in this register |

### 1.1 The rule that makes a row a control

**A row without an evidence artefact is not a control.** It is a claim, and it is a coverage gap.
A test name without its output does not satisfy the evidence column. An artefact that does not link to
the control it proves is not evidence. Where the evidence does not exist, the status says so.

### 1.2 Deduplication

The same requirement appears in several source documents with different wording and different IDs.
Each row below names the documents it was merged from in the **Control** cell, in the form
`[merged: 02 §1 control 6; 07 Control summary; 17 AUD-01; 24 §7]`. A requirement whose control is
shared is kept once and the sharing is stated. Nothing was merged across different instruments: two
requirements that name different instruments stay as two rows.

### 1.3 Where the rows came from

| Source document | Contribution |
|---|---|
| `17-compliance-control-matrix.md` | The master matrix: APP-01…APP-14, NDB-01…NDB-04, MHR/STATE-01…03, TGA-01…04, EP-01…02, SOCI/E8-01…08, SBD-01…12, TEN-01…03, AUD-01…03, RX-01…03, DOC-01…03, SEC-01…03, ENV-01…02, IR-01…04 |
| `02-security-architecture.md` §1, §10, Control table | The twelve controls; eleven frontend requirements; encryption, secrets, error and abuse rows |
| `21-technical-design.md` §13 | Architecture-level control rows |
| `23-sprint-plan.md` §12 | Gate, environment separation and pipeline rows |
| `24-definition-of-done.md` §7 | Review, severity, audit completeness, exception rows |
| `26-security-gates.md` §10 | Gate and residual-risk rows |
| `27-security-testing.md` §11 | Test, SLA and penetration-test rows |
| `01`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`, `12`, `13`, `14`, `15`, `16`, `18`, `19`, `20`, `22`, `28`, `29` | Module control summaries and control tables, merged rather than reproduced |

Statuses in the source documents were set on 2026-02-14 against a build that does not exist here.
They are **not** carried forward. Every row below is `Planned` unless a decision or an unresolved
legal position holds it at `OPEN` or `REQUIRES LEGAL/REGULATORY VALIDATION`.

### 1.4 Modules the register names

`identity_tenancy`, `users_roles`, `patients`, `clinical_records`, `audit`, `tga_approvals`,
`tga_inbox`, `reports`, `prescribing`, `pharmacy`, `documents`, `admin` — target modules under
`backend/app/modules/<module_id>/`, mapped to phases in
[`docs/reference/build-contract.md` §7](build-contract.md#7-module-map). A module is **not a phase**: the module
map is the target layout, not a schedule.

---

## 2. Status vocabulary

| Status | Meaning here | What must happen next |
|---|---|---|
| `Implemented` | The control exists and its evidence artefact exists | Re-review at the next cycle. **No row in this register carries this status today** |
| `In progress` | The control is being built and evidence is partial | Name the completion date and the evidence artefact |
| `Planned` | The control is designed and not built | Schedule it in a phase and name the owner |
| `OPEN` | The requirement is known and no control is chosen yet, or a decision it depends on is unresolved | Choose a control, or record an accepted risk |
| `REQUIRES LEGAL/REGULATORY VALIDATION` | The position depends on a regulator, a contract term or advice we do not have | Obtain advice and record the outcome in [`open-questions.md`](open-questions.md) |

Never close a validation row by writing an opinion. It closes when a named role records advice, per
[`docs/reference/build-contract.md` §10](build-contract.md#10-evidence-discipline) and the rule in
[`open-questions.md`](open-questions.md#4-the-rule).

---

## 3. Tenancy and isolation

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| Tenant isolation at the database layer, below the application | Privacy Act 1988 (Cth) APP 11; internal decision | RLS enabled and forced; tenant context set per transaction; a missing application filter cannot expose another tenant `[merged: 05 Control table; 17 TEN-01; 21 §13; ADR-002]` | Alembic raw-SQL migrations adding `USING` + `WITH CHECK` policies and `FORCE ROW LEVEL SECURITY`; `core/db.py` tenant-scoped transaction helper | RLS policy listing, grant listing, isolation test report | Security Lead | Planned | 1 | 2026-10-04 |
| No tenant context leakage through connection pooling | Internal decision; PgBouncer transaction-mode behaviour | `SET LOCAL` inside the transaction only; plain `SET` forbidden; reset proven | `core/db.py`; pooler configuration per environment | `backend/tests/isolation/test_pool_reuse.py` output | Head of Platform | OPEN | 1 | 2026-10-04 |
| Least privilege at the database | ACSC Essential Eight (restrict administrative privileges) | Dedicated non-owner application role, explicit grants, no `BYPASSRLS`, no `DELETE` where retention applies | Alembic grants; migration role separated from application role | `rls.app_role_is_not_owner` output; grant inspection | Security Lead | Planned | 1 | 2026-10-04 |
| `tenant_id NOT NULL` on every clinical table | Internal decision; source `04-database-erd.md` | Tenant column on every clinical table; composite keys include it | `backend/app/modules/<module_id>/models.py`; one migration per schema change | Migration lint output; RLS policy listing | Engineering Lead | Planned | 1 | 2026-10-04 |
| A tenant table with no policy fails CI | Internal decision | Schema lint rule that fails the build when a tenant table lacks an RLS policy | CI stage; lint script | Schema lint output in CI | Security Lead | Planned | 1 | 2026-10-04 |
| A request with no tenant context reads nothing | Internal decision; APP 11 | Fail-closed tenant resolution: no context means no rows and a refusal | `core/db.py`; `core/security.py` | Isolation test report, no-context case | Security Lead | Planned | 1 | 2026-10-04 |
| A forged `tenant_id` in a write is refused | Internal decision | `WITH CHECK` on every policy; caller-supplied tenant values ignored and audited | RLS policy migrations; `core/security.py` | `test_rls_write_forged_tenant_rejected` output | Security Lead | Planned | 1 | 2026-10-04 |
| Tenant identity is resolved, never supplied | Internal decision (`00-README.md` rule 3) | Tenant resolved from the session and the resource; a client value is ignored and its presence audited `[merged: 17 TEN-03]` | `core/security.py`; request middleware | Denial tests and audit events | Security Lead | Planned | 1 | 2026-10-04 |
| Isolation holds across every leakage channel | OWASP API1:2023 Broken Object Level Authorization; internal decision | Tenant context carried explicitly into API, workers, cron, SQS, exports, cache keys, S3 prefixes, presigned URLs, search, webhooks and analytics `[merged: 05 Control table; 17 TEN-02]` | Per-channel context plumbing in each module facade | Isolation suite asserting absence across list, filter, sort, search, direct id, nested resource, export and cache | Security Lead | Planned | 1 | 2026-10-04 |
| Isolation is proven by asserting absence | Internal decision; research note B15 | 35 named isolation tests against a seeded canary tenant, each asserting what cannot be seen | `backend/tests/isolation/` | CI isolation test report; release gate record | Security Lead | Planned | 1 | 2026-10-04 |
| A practitioner working across two clinics is modelled correctly | Internal decision | Decide two user rows versus one identity with two tenant memberships, and its isolation consequences | `users_roles` model; `identity_tenancy` service | Written design decision; isolation tests for the chosen model | Engineering Lead + Clinical Safety Officer | OPEN | 1 | 2026-10-04 |
| Alerting on cross-tenant authorisation denials | Privacy Act 1988 (Cth); Notifiable Data Breaches scheme | Alert on a cross-tenant denial with a documented assessment path `[merged: 05 Control table; 18 §11]` | Alert catalogue; `18-incident-response.md` assessment path | Alert configuration; incident runbook | Security Lead | Planned | 1 | 2026-10-04 |
| Contractual isolation expectations | Customer contracts, unseen | Nothing claimed beyond shared schema plus RLS | Sales collateral review; product documentation | Signed review record; §10 of source `05-tenant-isolation.md` | Commercial Lead | REQUIRES LEGAL/REGULATORY VALIDATION | Before Gate 7 | 2026-10-04 |
| Per-tenant encryption keys, if a contract requires them | Customer contracts, unseen | Shared CMK domain today; per-tenant keys only on a contractual trigger | KMS key policy; migration path to per-tenant keys | Executed contract terms; key policy | Commercial Lead + Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION | Before Gate 7 | 2026-10-04 |

---

## 4. Identity and access

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| Authentication | Internal control 1; NIST SP 800-63; ACSC Essential Eight | Token verification of `iss`/`aud`/`exp`, MFA for clinical and administrative roles, 15-minute access tokens, refresh rotation, server-side revocation `[merged: 02 §1 control 1; 17 SBD-01; 17 E8-07; 06 Control summary; 21 §13]` | `core/security.py`; `identity_tenancy` module; IdP or hardened self-hosted auth per D-003 | Auth test module output; MFA policy export; session revocation test | Security Lead | OPEN — blocked by D-003 | 1 | 2026-10-04 |
| Authorisation | Internal control 2; OWASP API1:2023 | Thin role bundles over granular permissions; one central policy layer; decision recomputed per request from identity, tenant and resource `[merged: 02 §1 control 2; 17 SBD-02; 06 Control summary; 21 §13]` | `core/security.py` policy layer; `users_roles` module | `backend/tests/security/test_authz_recomputes_server_side.py` output; permission matrix test per role | Security Lead | OPEN — blocked by D-003 | 1 | 2026-10-04 |
| The frontend cannot enforce or grant access | Internal decision (`00-README.md` rule 2); OWASP API1:2023 | Every mutation re-authorised server-side; UI state advisory only `[merged: 06 Control summary]` | `core/security.py`; frontend reads capabilities only | `test_authz_recomputes_server_side`; frontend capability test | Security Lead | Planned | 1 | 2026-10-04 |
| Sessions end when they should and can be revoked | Internal decision | Rotating refresh tokens, idle and absolute timeouts, server-side revocation list; a revoked session is refused before token expiry `[merged: 06 Control summary]` | `identity_tenancy` module; `refresh_tokens` table | Session revocation test output; session metric | CTO | OPEN — blocked by D-003 | 1 | 2026-10-04 |
| MFA cannot be bypassed by a direct API call | ACSC Essential Eight; NIST SP 800-63 | MFA mandatory for clinical and administrative roles; enforced in the token contract, not the UI `[merged: 17 E8-07]` | Auth module; IdP policy or self-hosted TOTP per D-003 | MFA enforcement test including direct API call | Security Lead | OPEN — blocked by D-003 | 1 | 2026-10-04 |
| Step-up for the named high-risk operations | Internal policy; ACSC Essential Eight | Server-side step-up for the five named operations; no client-controlled bypass `[merged: 06 Control summary; 17 SBD-01]` | `core/security.py`; step-up token with a single-purpose window | Step-up test results; step-up audit events | Security Lead | OPEN — blocked by D-003 | 1 | 2026-10-04 |
| Lockout, and an audited release path | Internal decision | Lockout after the defined failure count, with the release path audited | Auth module; `audit` module | Lockout test result; release-path audit event | Security Lead | OPEN — blocked by D-003 | 1 | 2026-10-04 |
| Credentials and tokens never reach a log | Internal decision; OWASP Secrets Management | Redaction filter at the logger boundary plus a deny list `[merged: 06 Control summary]` | `core/audit.py`; logging redaction pipeline | Redaction test; log sampling review | CTO | Planned | 1 | 2026-10-04 |
| Roles map to granular permissions, not hard-coded checks | Internal decision | Role bundles resolve to a permission set at login; handlers query the policy layer `[merged: 06 Control summary]` | `users_roles` module; permission seed data | Permission matrix review at each release; `USER_PERMISSION_CHANGED` audit events | Practice Owner | OPEN — blocked by D-003 | 1 | 2026-10-04 |
| Break-glass access is time-boxed and audited | Internal decision; APP 11 | Just-in-time elevation with a reason, expiry, notification and retrospective review `[merged: 17 SEC-03; 28 §14; 29 §12]` | `admin` module; IAM elevation workflow | Elevation records and reviews | Security Lead | Planned | 4 | 2026-10-04 |
| Identity data is covered by the residency register | Privacy Act 1988 (Cth) APP 8 | Every identity provider under consideration is entered with its hosting region and support locations | Residency register row per provider | Completed register rows | Privacy Officer | OPEN | 1 | 2026-10-04 |
| No shared accounts exist | Internal decision | One identity per person; no shared clinical or administrative account | Auth module; onboarding procedure | Access-review baseline; exception register | Security Lead | Planned | 1 | 2026-10-04 |
| Account recovery is logged with login-level fidelity | Internal decision | Recovery events emitted into the append-only audit log | Auth module; `audit` module | Recovery audit event sample | Security Lead | OPEN — blocked by D-003 | 1 | 2026-10-04 |

---

## 5. Audit and evidence

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| Audit is append-only | Privacy Act 1988 (Cth); internal decision | The application role holds `INSERT` and `SELECT` only; no `UPDATE` or `DELETE` grant and no update policy `[merged: 02 §1 control 6; 17 AUD-01; 07 Control summary; 21 §13; 04 Control table]` | `audit_log` grants in Alembic; `core/audit.py` as the single writer | GRANT inspection test; append-only test | Security Lead | Planned | 1 | 2026-10-04 |
| The trail survives a compromised application server | Internal decision; NDB reconstruction | Outbox to queue to immutable object storage with a verified hash chain `[merged: 17 AUD-02; 07 Control summary; 14 §6]` | Audit export job; immutable archive bucket with Object Lock | Store policy; export records; chain verification job | CTO | Planned | 4 | 2026-10-04 |
| Audit and the business write commit together | Internal decision | One transaction for the domain change, the audit event and the outbox row `[merged: 07 Control summary]` | `core/audit.py`; transaction helper in `core/db.py` | `backend/tests/security/test_audit_writes_in_same_transaction.py` output | CTO | Planned | 1 | 2026-10-04 |
| Audit write failure fails the operation | Internal definition of done Part 3 | A failure to write an audit event for an audited operation fails the operation | `core/audit.py` | Audit coverage test output; denial case | Security Lead | Planned | 1 | 2026-10-04 |
| Denied and failed attempts are audited | Internal definition of done Part 3 | Denials and failures emit an audit event, not only successes | `core/audit.py`; per-module audit calls | Audit coverage test output | Security Lead | Planned | 1 | 2026-10-04 |
| Audit events carry the full fixed envelope | Internal decision; NDB scheme | `event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result, reason, source_ip, request_id, correlation_id` `[merged: 24 §7; 07 Control summary]` | `core/audit.py`; audit event schema | Sample event with the full envelope; envelope validator test | Security Lead | Planned | 1 | 2026-10-04 |
| No clinical content in an audit payload | Internal decision; APP 11 | Per-action metadata allow-list enforced by type and runtime schema `[merged: 07 Control summary]` | `core/audit.py` payload allow-list | Payload review at each new action; redaction unit tests | Clinical Safety Officer | Planned | 1 | 2026-10-04 |
| Tamper-evident hash chaining | Internal decision | Hash chain over audit rows with a verification job that detects a modified row `[merged: 17 AUD-01; 04 Control table]` | `audit` module; verification job | Chain verification report | Security Lead | Planned | 1 | 2026-10-04 |
| The audit trail is searchable for the questions actually asked | Internal decision | Tenant-scoped audit read with keyset pagination, filters and export rules `[merged: 07 Control summary]` | `audit` module; `/api/v1/audit/*` routes | Audit read test; per-patient access history view | Compliance Lead | Planned | 4 | 2026-10-04 |
| Audit reads are themselves audited | Internal decision | An `audit.read` event on every call, including an empty result `[merged: 07 Control summary]` | `audit` module; `core/audit.py` | Audit read test output | Security Lead | Planned | 4 | 2026-10-04 |
| Audit write failure is alerted | OWASP A09; internal decision | Alert on audit write failure and on queue depth `[merged: 17 AUD-03; 29 §12]` | Alert catalogue; audit writer | Alert definition and test | Security Lead | Planned | 4 | 2026-10-04 |
| Required events are written in the same transaction | Privacy Act 1988 (Cth); state and territory health records legislation | Audit coverage test over the mandatory event list `[merged: 24 §7; 22 §5]` | `audit` module; audit coverage test | Coverage test output | Compliance Lead | Planned | 1 | 2026-10-04 |
| Audit retention and legal hold are provable | APP 11.2; state and territory health records legislation | Partition-level expiry, a legal-hold register, and no row-level deletion `[merged: 07 Control summary; 17 AUD-02]` | `audit_log` partitions; `legal_holds` table; partition job | Partition drop log; legal-hold report | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |

---

## 6. Data protection and residency

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| Encryption in transit and at rest | APP 11; ASD cloud security guidance | TLS 1.2+ with HSTS, SSE-KMS at rest for database, object store, queues and logs; envelope encryption for documents `[merged: 02 §1 control 7; 02 Control table; 17 SBD-07; 21 §13]` | Terminated TLS configuration; KMS key policies; storage configuration | TLS scan result; KMS key inventory and policy review | Engineering Lead | Planned | 0–1 | 2026-10-04 |
| Field-level encryption is a per-field decision with the search trade-off recorded | APP 11; engineering judgement | Medicare number and IHI encrypted with a keyed blind index; narrative and search keys plaintext under RLS `[merged: 02 §5.1; 02 Control table; 12 §8]` | Column-level encryption and blind index columns; migration job | Written per-field decision; ADR; blind index key custody decision | Security Lead | OPEN | 1 | 2026-10-04 |
| Key custody and rotation | Internal decision | CMK ownership, annual rotation, key policies least-privilege per workload role, and a re-key migration path | KMS key policies; re-key migration job | Key policy review; rotation record; re-key run record | Security Lead | OPEN — blocked by D-003 for signing-key custody | 1 | 2026-10-04 |
| Classification drives storage, encryption, access and monitoring | Internal decision (`00-README.md` rule 4); APP 11.1, APP 11.3 | Classification declared at schema level and enforced by a CI lint; redaction, encryption, access and monitoring read from it `[merged: 12 §8; 04 Control table]` | Schema annotations; classification lint; redaction pipeline | Classification lint output; redaction tests; key policy | Security Lead | Planned | 1 | 2026-10-04 |
| Government related identifiers are not adopted or used without a basis | Privacy Act 1988 (Cth) APP 9 | Internal opaque patient id; Medicare number and IHI as restricted attributes, never primary or join keys `[merged: 12 §8; 17 APP-10]` | `patients` model; RLS; access control | Schema evidence; tests; APP 9 assessment | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION | 1 | 2026-10-04 |
| Purpose-scoped access and deny-by-default for secondary use | Privacy Act 1988 (Cth) APP 3, APP 6 | Purpose recorded per field and per request; secondary use denied by default; de-identification at the pipeline boundary `[merged: 15 §8; 17 APP-04, APP-07]` | Policy layer; consent records; analytics boundary | Purpose tests; consent records; minimisation notes | Privacy Officer | Planned | 1 | 2026-10-04 |
| Collection notices record the served version | Privacy Act 1988 (Cth) APP 5 | Layered collection notices with the served version recorded `[merged: 17 APP-06; 15 §8]` | Notice service and notice versions | Notice text and version log | Privacy Officer | Planned | 4 | 2026-10-04 |
| Unsolicited personal information is quarantined and dispositioned | Privacy Act 1988 (Cth) APP 4 | Inbox quarantine with a recorded disposition decision `[merged: 17 APP-05]` | Inbox pipeline quarantine queue | Quarantine metrics and disposition records | Privacy Officer | Planned | 2 | 2026-10-04 |
| Data quality, provenance and correction | Privacy Act 1988 (Cth) APP 10, APP 13 | Validation, provenance, last-verified stamps, duplicate detection and a correction workflow that appends `[merged: 17 APP-11, APP-14; 14 §6]` | `patients` module; correction workflow | Validation tests; correction records | Privacy Officer | Planned | 1 | 2026-10-04 |
| Cross-border disclosure and accountability | Privacy Act 1988 (Cth) APP 8 and s 16C | Residency rule, cross-border register, five-condition test before any transfer, vendor gate `[merged: 02 Control table; 13 §7; 17 APP-09; 21 §13]` | Residency register; onboarding gate; region pinning | Completed register rows; executed terms | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION | 0–2 | 2026-10-04 |
| Australian-only holding of My Health Record data where applicable | My Health Records Act 2012 (Cth) | Single-region design; a feature flag blocks My Health Record data if the position changes `[merged: 13 §7; 17 MHR-01; 20 §15]` | Region pinning; feature flag | Legal advice and design note | Data Protection Officer (if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| No unapproved region in infrastructure as code | Internal decision | CI region check plus a service control policy denying other regions | CI check; SCP | CI log; SCP listing | Engineering Lead | OPEN — blocked by D-004 | 4 | 2026-10-04 |
| Vendor data minimisation | Internal decision; APP 3 | A vendor receives only the data its function requires, per a written minimum data set `[merged: 13 §7; 16 §7; 17 APP-03]` | Per-flow data category list; adapter field allow-list | Register rows; adapter field review | Privacy Officer | Planned | 2 | 2026-10-04 |
| Residency of logs, metrics and telemetry | Privacy Act 1988 (Cth) APP 8 | Logs and metrics stored in the approved Australian region | Region configuration; log store configuration | Residency register rows; store configuration | Security Lead | OPEN — blocked by D-004 | 4 | 2026-10-04 |
| Access on request, with a defined clock | Privacy Act 1988 (Cth) APP 12 | DSAR access workflow with states, a clock and audit events `[merged: 17 APP-13; 14 §6]` | Request module and export path | Request records; audit events | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Retention schedule with triggers and a purge job | Privacy Act 1988 (Cth) APP 11.2; state and territory health records legislation | Per-jurisdiction configuration, deletion certificates, and no hard delete where a retention obligation applies `[merged: 14 §6; 17 STATE-01; 12 §8]` | Retention engine; purge worker; jurisdiction rule table | Purge run records; certificate sample; rule tests | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Legal hold excludes a record from purge | Internal decision | Hold register with review and purge exclusion | `legal_holds` table; purge integration | Hold register; hold test | Compliance Lead | Planned | 2 | 2026-10-04 |
| Retention and destruction integrity for the audit trail | Privacy Act 1988 (Cth) s 26WE, s 26WH; state legislation | Audit and access records retained beyond the breach assessment window `[merged: 14 §6; 17 NDB-04]` | Append-only store; retention configuration | Retention configuration; store policy | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Production data is never copied into development | APP 11; internal decision | Synthetic data by default; extract approval and a re-identification test `[merged: 17 ENV-02; 12 §8; 23 §12; 27 §11]` | Extract workflow; environment separation | Extract manifest and approval; leak test | Privacy Officer | Planned | 0–1 | 2026-10-04 |
| Documents are stored privately | APP 11; ASD guidance | Private object store; bucket policy denies public access; no public ACLs `[merged: 17 DOC-01]` | Object store configuration | Bucket policy; access analyser output | Engineering Lead | OPEN — blocked by D-004 | 1 | 2026-10-04 |
| Documents are served only by a short-lived, tenant-scoped signed URL | APP 11; internal decision | Short expiry, attachment disposition, tenant scope `[merged: 17 DOC-02; 11 Control summary]` | `documents` module; presigned URL minting | Signed-URL tests; expiry test | Engineering Lead | Planned | 1 | 2026-10-04 |
| Uploaded documents are validated and scanned | OWASP file upload guidance; internal decision | Type allow-list, magic-byte validation, size caps, malware scan, quarantine `[merged: 17 DOC-03; 11 Control summary]` | Upload pipeline; scan integration | Upload tests; scan records | Security Lead | Planned | 2 | 2026-10-04 |
| Unsettled residency positions are never closed by an engineer | Privacy Act 1988 (Cth) APP 8; Health Records Act 2001 (Vic) HPP 9 | Register row per flow, marked until advice is recorded | Residency register | Advice reference recorded against the row | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION | Before Gate 7 | 2026-10-04 |

---

## 7. Clinical safety

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| No dispatch without an `ACTIVE` approval at the grain | TGA therapeutic goods framework; Authorised Prescriber pathway; internal clinical safety decision | Backend safety gate evaluates approval state at the moment of dispatch; no or frontend field can bypass it `[merged: 02 §1; 09 Control summary; 17 RX-01; 21 §13; 22 §5; 26 §10]` | `prescribing` module; one exported gate entry point | `test_dispatch_blocks_without_active_approval`; negative dispatch matrix; Gate 4 test report | Clinical Safety Officer | Planned | 3 | 2026-10-04 |
| Approval recorded at the stated grain | TGA therapeutic goods framework; Authorised Prescriber pathway | Approval register keyed to patient + category + dosage form + validity, with an exclusion constraint on overlapping active intervals `[merged: 04 Control table; 06 §Control summary; 08 Control summary; 17 TGA-01; 22 §5]` | `tga_approvals` table; approval service; GiST exclusion constraint in an Alembic raw-SQL migration | Register schema; `tga.overlapping_active_approval_rejected`; grain match test | Clinical Safety Officer | OPEN — the grain interpretation is a legal-validation item | 2 | 2026-10-04 |
| Approval states are modelled and transitions controlled | Internal decision; TGA guidance | State machine over `PENDING, ACTIVE, EXPIRED, REJECTED, REVOKED, SUPERSEDED` with a permitted-trigger list and an audit action per row `[merged: 08 Control summary; 17 TGA-02]` | Approval service; `tga_approval_events` | State transition tests; audit review | Clinical Safety Officer | Planned | 2 | 2026-10-04 |
| Expiry is computed, not inferred | Internal decision | Daily idempotent job flips `ACTIVE` to `EXPIRED` in `Australia/Sydney` | Expiry job | Job run log; expiry test | CTO | Planned | 2 | 2026-10-04 |
| No automated write to clinical state | Internal clinical safety decision | Every clinical state change requires an attributable human action `[merged: 11 Control summary; 15 §8; 17 RX-02]` | Approval, inbox and prescription services | Gate tests; audit events | Clinical Safety Officer | Planned | 2–3 | 2026-10-04 |
| A timeout is never reported as success | Internal clinical safety decision; research note C25 | An unknown outcome becomes `REQUIRES_RECONCILIATION`, resolved by a reconciliation job `[merged: 09 Control summary]` | `pharmacy` module; `dispatch_attempts`; reconciliation worker | Timeout and reconciliation tests; reconciliation report | CTO | Planned | 3 | 2026-10-04 |
| Duplicate dispatch is prevented by the database | Research note C25 | Unique idempotency key per intent, reused on every retry `[merged: 09 Control summary; 17 EP-02]` | `prescriptions` / `dispatch_attempts` unique constraint; idempotency handling | Idempotency test; duplicate-suppression test | CTO | Planned | 3 | 2026-10-04 |
| Only one code path may reach the prescription rail | Internal decision | One exported gate entry point plus an import lint rule | `prescribing` module facade; import lint in CI | Import lint output in CI | CTO | Planned | 3 | 2026-10-04 |
| Blocked attempts are security-relevant and recorded | Internal decision; audit architecture | A dispatch-blocked event with a specific reason code on every refusal `[merged: 09 Control summary]` | Safety gate; `audit` module | Blocked-attempt test; monitoring | Security Lead | Planned | 3 | 2026-10-04 |
| Every gate change is clinically reviewed | Internal change control | Gate 4 and Gate 6 re-run with Clinical Safety Officer approval `[merged: 09 Control summary]` | Change control in [`gates.md`](gates.md) | Gate record per release | Clinical Safety Officer | Planned | 2–4 | 2026-10-04 |
| Human verification of OCR and extraction output | Internal clinical safety decision; research note C24 | Confidence scoring, per-field floors, a deterministic cross-check and human verification; nothing is auto-activated | `tga_inbox` module; extraction results; verification queue | Pipeline tests; verification-rate metric; reconstructability drill | Clinical Safety Officer | Planned | 2 | 2026-10-04 |
| No auto-association below the threshold | Internal decision | Threshold is a tenant policy value with clinical sign-off | Tenant policy configuration; matching service | Policy change audit events; threshold review record | Clinical Safety Officer | OPEN — thresholds unconfirmed | 2 | 2026-10-04 |
| Duplicate, allergy and dose safety checks | Clinical safety guidance | Deterministic checks with the result recorded; "none known" distinguished from "not recorded" `[merged: 17 RX-03]` | `prescribing` module | Safety check tests | Clinical Safety Officer | Planned | 3 | 2026-10-04 |
| Jurisdiction-driven Schedule 8 and monitoring rules | State and territory drugs and poisons legislation | Jurisdiction-driven workflow rules and mandatory-check configuration `[merged: 17 STATE-03; 20 §15]` | Configuration model; jurisdiction attribute | Configuration and test evidence | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION | 3 | 2026-10-04 |
| Controlled vocabulary for category and dosage form | Internal decision | A maintained controlled vocabulary with a named owner | Reference data; vocabulary owner | Vocabulary file and change log | Clinical Safety Officer | OPEN | 2 | 2026-10-04 |
| Clinical record immutability | Internal clinical safety decision | Signed records are versioned, never updated in place `[merged: 04 Control table; 17 RX-02]` | `clinical_records` module; immutability trigger | `clinical.version_update_rejected` output | Clinical Safety Officer | Planned | 1 | 2026-10-04 |

---

## 8. Integration boundaries

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| No integration bypasses internal validation | Internal decision | Fixed sequence: internal validation, security check, approval check, audit, then the external call `[merged: 10 Control summary]` | Adapter interface; `pharmacy` module | Adapter tests; sandbox test report | Head of Integrations | Planned | 2–3 | 2026-10-04 |
| Provider credentials live only in a managed secret store | Internal decision; ACSC Essential Eight | Secrets per environment, with rotation; no secret in an image, a task definition or the repository `[merged: 10 Control summary; 02 §1 control 8]` | Secret store adapter written against an interface in Phase 0; credential loaders | Secret rotation log; no-secret-in-image test | Security Lead | OPEN — the secret store depends on D-004 | 0–3 | 2026-10-04 |
| Every provider call is bounded and idempotent | Research note C25 | Connect and read timeouts, a capped retry with jitter, a circuit breaker, a bulkhead and an idempotency key `[merged: 10 Control summary; 17 EP-02]` | Adapter configuration; outbound integration layer | Failure-mode tests; reconciliation report | Head of Integrations | Planned | 3 | 2026-10-04 |
| Inbound events are validated before any state change | Research note B15 | Signature verification, a replay window, payload-derived tenant routing and schema validation `[merged: 10 Control summary]` | `/webhooks/:provider`; `webhook_events` table | Webhook tests | Security Lead | Planned | 3 | 2026-10-04 |
| No patient information in an integration log | Internal decision; APP 11 | Structured logs with correlation identifiers and outcome classes only `[merged: 10 Control summary; 02 §1 control 9]` | Integration logging with the same redaction pipeline | Integration log test; redaction test | Privacy Officer | Planned | 3 | 2026-10-04 |
| A forged request cannot reach an internal service | Research note A7 (SSRF) | Egress allow-list, resolver checks, metadata service restricted, no tenant-supplied URL fetched `[merged: 10 Control summary]` | Network configuration; outbound HTTP client policy | SSRF tests | Security Lead | Planned | 3 | 2026-10-04 |
| Production shares nothing with development | Internal decision; ASD guidance | Separate credentials, queues, buckets and databases per environment `[merged: 10 Control summary; 17 ENV-01; 23 §12; 28 §14]` | Per-environment configuration | Environment inventory; separation tests | CTO | OPEN — blocked by D-004 | 4 | 2026-10-04 |
| The conformant party for the e-prescribing rail is identified | E-prescribing requirements; ADHA conformance model | Adapter behind one interface; conformance stays with the certified party `[merged: 17 EP-01; 19 §14; 20 §15; 21 §13]` | Parchment adapter | Sandbox and conformance evidence | CTO | REQUIRES LEGAL/REGULATORY VALIDATION | 3 | 2026-10-04 |
| Vendor onboarding gate and evidence standard | APP 8 and s 16C; APP 11.3; SOCI Act where applicable | Residency check, contractual flow-down and a tiered evidence standard before onboarding `[merged: 16 §7; 17 SOCI-02]` | Onboarding gate; vendor register; evidence store | Executed terms; completed questionnaires; five-condition test | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION | 2–4 | 2026-10-04 |
| Vendor breach notification path | Privacy Act 1988 (Cth) s 26WH, s 26WK | Breach notification terms and a contact tree `[merged: 16 §7; 18 §11]` | Contract clause; incident response contact tree | Executed clause; contact tree | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Data return and deletion on exit | APP 11.2; internal decision | Decommissioning procedure with a deletion certificate `[merged: 16 §7]` | Decommissioning procedure | Deletion certificates | Compliance/Auditor | Planned | 4 | 2026-10-04 |
| The TGA correspondence channel is treated as an untrusted boundary | Internal decision; APP 11 | Mailbox restricted; transport, retention and handling obligations recorded | Inbox pipeline; mailbox configuration | Configuration evidence; register row | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION | 2 | 2026-10-04 |

---

## 9. Operations and delivery

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| Technical controls are assessed before release | ACSC Essential Eight; internal policy | Seven gates with named approvers, produced during the phase `[merged: 23 §12; 26 §10; 24 §7]` | [`gates.md`](gates.md) | Signed gate records | Security Lead | Planned | 0–4 | 2026-10-04 |
| No self-approval of a gate | Internal change control | The deliverer and the approver are different roles `[merged: 23 §12; 26 §10]` | Gate sign-off template | Signed records | CTO | Planned | 0–4 | 2026-10-04 |
| Every feature carries a security review | ACSC Essential Eight; internal policy | Six-part checklist with a named reviewer `[merged: 24 §7]` | Pull request template and review record | Signed checklist | Security Lead | Planned | 0–4 | 2026-10-04 |
| No release with an open Critical finding | Internal security baseline | Severity threshold blocks deployment `[merged: 23 §12; 24 §7; 26 §10]` | CI pipeline and release gate | Pipeline record; scan reports | Security Lead | Planned | 0–4 | 2026-10-04 |
| Residual risk is accepted by the right owner | Internal risk management | Gate 7 with documented acceptance `[merged: 26 §10]` | Risk acceptance register | Signed acceptances | Practice Owner | Planned | 4 | 2026-10-04 |
| Exceptions are recorded and expire | Internal change control | Exception register with approvers and expiry `[merged: 24 §7]` | Exception register | Exception register entries | Delivery Lead | Planned | 0–4 | 2026-10-04 |
| Clinical behaviour changes require clinical acceptance | Clinical governance | Clinical Safety Officer sign-off; cannot be waived `[merged: 24 §7]` | Review record | Sign-off | Clinical Safety Officer | Planned | 0–4 | 2026-10-04 |
| CI blocks on a critical finding in a fixed pipeline order | Internal security baseline | `lint → typecheck → unit → integration → security tests → SAST → dependency scan → container scan → secret scan → build → deploy` `[merged: 23 §12; 27 §11; D-001]` | CI pipeline definition | Pipeline run record | Security Lead | Planned | 0 | 2026-10-04 |
| Vulnerabilities are managed to a stated SLA | ACSC Essential Eight | Vulnerability workflow with severities and SLAs `[merged: 27 §11]` | Vulnerability process | Triage and closure records | Security Lead | Planned | 0–4 | 2026-10-04 |
| Independent assurance before go-live | Production readiness gate | Penetration test before the pilot and annually `[merged: 27 §11]` | Penetration test engagement | Penetration test report and retest | Security Lead | OPEN — booking and provider unconfirmed | 4 | 2026-10-04 |
| Access control is tested | Privacy Act 1988 (Cth); APPs | Access-control matrix and authorisation tests `[merged: 27 §11]` | `backend/tests/security/` | Test report | Security Lead | Planned | 1 | 2026-10-04 |
| Tenant isolation is proven by absence in the test suite | Privacy Act 1988 (Cth); APPs | Isolation and pool-reuse tests `[merged: 27 §11; 05 Control table]` | `backend/tests/isolation/` | Test report | Security Lead | Planned | 1 | 2026-10-04 |
| Secrets never reach the repository | ACSC Essential Eight | Secret scanning over full history plus pre-commit scanning `[merged: 27 §11; 17 SEC-01; 12 §8; 29 §12]` | Gitleaks over full history; pre-commit hook | Scan report | Security Lead | Planned | 0 | 2026-10-04 |
| Vulnerabilities never ship suppressed without a record | Internal evidence discipline | A scanner finding is closed by a fix or an accepted risk with a justification and an expiry `[merged: 24 §7]` | Suppression register | Suppression entries with expiry | Security Lead | Planned | 0–4 | 2026-10-04 |
| Reproducible infrastructure | Production readiness gate | IaC with a locked encrypted backend and drift detection `[merged: 28 §14]` | Infrastructure code | Backend configuration; drift reports | Head of Platform | OPEN — blocked by D-004 | 4 | 2026-10-04 |
| Network segmentation | ACSC Essential Eight; internal policy | Public, application and data tiers with no database internet route `[merged: 28 §14]` | Network configuration | Network and security group export | Head of Platform | OPEN — blocked by D-004 | 4 | 2026-10-04 |
| Least-privilege machine identity | ACSC Essential Eight; ASD guidance | Workload identity federation, scoped roles, no long-lived access keys `[merged: 17 SEC-02; 28 §14]` | IAM configuration | Role policy review; credential report | Security Lead | OPEN — blocked by D-004 | 4 | 2026-10-04 |
| No standing production access | Production readiness gate; APP 11 | Just-in-time elevation with a reason and notification `[merged: 28 §14; 29 §12]` | IAM elevation workflow | Elevation records | Security Lead | OPEN — blocked by D-004 | 4 | 2026-10-04 |
| Application control and image hardening | ACSC Essential Eight | Allowlisted images, pinned dependencies, non-root, read-only root filesystem, digest pinning `[merged: 17 E8-01; 17 E8-06]` | Container build and registry policy | Image inventory; admission checks; rebuild record | Engineering Lead | Planned | 0 | 2026-10-04 |
| Patch applications and dependencies | ACSC Essential Eight | Dependency updates at pull request, CI scanning, a triage window `[merged: 17 E8-02]` | Dependency scanning in CI | Scan reports; patch SLA record | Engineering Lead | Planned | 0 | 2026-10-04 |
| Backup and restore | ACSC Essential Eight; Production readiness gate | Encrypted automated backups plus a **timed** restore drill measured against the agreed RPO and RTO `[merged: 17 E8-08; 28 §14; 29 §12]` | Backup configuration; restore runbook | Restore drill record; RPO and RTO statement | Head of Platform | OPEN — RPO and RTO unconfirmed | 4 | 2026-10-04 |
| Migration safety | Internal decision | Forward-only, expand-and-contract, RLS policy in the same migration `[merged: 04 Control table]` | Alembic migration standard | Migration run log in Staging; checksum guard | Engineering Lead | Planned | 1 | 2026-10-04 |
| Injection prevention | OWASP A05:2025 | Parameterised queries only, identifier allow-list, a build-breaking lint rule `[merged: 04 Control table]` | Data access layer; lint rule | Lint output in CI | Engineering Lead | Planned | 1 | 2026-10-04 |
| Structured logging with correlation | Internal decision | Mandatory fields per request and propagation across queues and providers `[merged: 29 §12]` | Logger library and middleware | Envelope validator and correlation tests | Engineering Lead | Planned | 1 | 2026-10-04 |
| No sensitive data in logs, metrics, traces or error responses | APP 11; OWASP A09; internal decision; INV-5 | Classification-driven redaction before the sink write; a sentinel value proves it `[merged: 29 §12; 02 §1 control 9; 24 §7]` | Redaction pipeline; error envelope; trace sampling | `backend/tests/security/test_no_phi_in_log_payload.py`; redaction tests | Security Lead | Planned | 1 | 2026-10-04 |
| Detection and alerting | OWASP A09; ACSC guidance | Metrics and alerts with routes and runbooks `[merged: 29 §12; 18 §11]` | Alert catalogue | Alert definitions and test | Security Lead | Planned | 4 | 2026-10-04 |
| Log categories are separate and access-controlled | Internal decision | Five stores with separate access and retention | Log configuration | Store configuration; access review | Engineering Lead | Planned | 4 | 2026-10-04 |
| Log retention supports breach assessment | OAIC NDB guidance | Retention beyond the assessment window `[merged: 29 §12; 17 NDB-04]` | Retention configuration | Retention policy | Security Lead | Planned | 4 | 2026-10-04 |
| Clinical performance target | Internal decision | p95 of 200 ms for the clinical record query | Query design, indexes, caching policy | Latency dashboard; load test | Engineering Lead | Planned | 1 | 2026-10-04 |
| Inbox processing target | Internal decision; clinical operations | Two-minute target from receipt to the verification queue `[merged: 29 §12; 11 Control summary]` | Inbox worker; queue metrics | Processing-time dashboard | Engineering Lead | Planned | 2 | 2026-10-04 |
| Application security baseline | OWASP Top 10:2025; OWASP ASVS 5.0 | Mapping table with a named control per category `[merged: 02 Control table]` | Security architecture mapping | Mapping table; ASVS verification record | Security Lead | Planned | 0 | 2026-10-04 |
| Secure frontend configuration | OWASP ASVS 5.0; internal decision | Eleven release-blocking frontend requirements, including no PHI in browser storage, no token in browser storage, strict CSP and secure headers `[merged: 02 §10; 02 Control table]` | Frontend build configuration and lint | `frontend/tests/security/storage-no-phi.spec.ts`; `backend/tests/security/test_security_headers.py`; CSP assertion test | Frontend Lead | Planned | 1 | 2026-10-04 |
| Content Security Policy compatible with the bundle | OWASP ASVS 5.0 | A strict CSP proven against the built frontend in Staging | Frontend build; response headers | Header assertion test; CSP report monitor | Frontend Lead | OPEN | 1 | 2026-10-04 |
| Abuse and denial-of-service resistance | ACSC Essential Eight; internal decision | Edge, per-endpoint and per-tenant rate limits, plus a breached-credential check at login `[merged: 02 §1 control 10; 02 §11; 02 Control table; 17 SBD-10]` | Rate-limit middleware; edge rules | Per-endpoint rate-limit tests; edge rule export | Security Lead | Planned | 1 | 2026-10-04 |
| Input validation | Internal control 4; OWASP | One Pydantic schema per endpoint, parsed before the handler, unknown fields rejected, size and list limits `[merged: 02 §1 control 4; 17 SBD-04]` | `schemas.py` per module | `backend/tests/security/test_validation_rejects_unknown_field.py` | Engineering Lead | Planned | 1 | 2026-10-04 |
| Output validation | Internal control 5; OWASP | Response serialised through a declared schema; no raw ORM entity returned; field allow-list per role `[merged: 02 §1 control 5; 17 SBD-05]` | Response schemas per module | `backend/tests/security/test_serialisation_omits_restricted_fields.py` | Engineering Lead | Planned | 1 | 2026-10-04 |
| Error handling | OWASP A10:2025; APP 11 | One error envelope, no diagnostics to the client, `request_id` correlation, fail closed `[merged: 02 §1 control 9; 02 Control table; 17 SBD-09]` | Error contract in `main.py`; exception handlers | `backend/tests/security/test_errors_never_leak_internal_detail.py`; fail-closed test | Engineering Lead | Planned | 0–1 | 2026-10-04 |
| Module boundaries are enforced by lint | Internal decision; D-002 | A module does not import another module's models or internals; the worker is a second entrypoint in the same package | Import lint rule; `backend/app/modules/` | Import lint output in CI | CTO | Planned | 1 | 2026-10-04 |

---

## 10. Compliance governance

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| Open and transparent management: practices, procedures, systems, policy, complaints | Privacy Act 1988 (Cth) APP 1; OAIC APP 1 | Policy registry, named Privacy Officer, PIA program, complaints procedure, staff training `[merged: 17 APP-01; 15 §8; 19 §14]` | Policy service; training records | Privacy policy; PIA; control matrix; training log | Privacy Officer | Planned | 4 | 2026-10-04 |
| Automated decision-making transparency from 10 December 2026 | Privacy Act 1988 (Cth) APP 1.7 to 1.9 | An ADM register and policy disclosure for any programmatic decision affecting rights or interests `[merged: 17 APP-02; 15 §8]` | ADM register; no automated clinical decisions | ADM register and policy text | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Privacy impact assessment before handling personal information in a new project | Privacy Act 1988 (Cth); OAIC guidance | A PIA, reviewed on a schedule and on material change `[merged: 15 §8; 19 §14]` | PIA register | Signed PIA | Privacy Officer | Planned | 4 | 2026-10-04 |
| Assess a suspected eligible data breach within the statutory window | Privacy Act 1988 (Cth) s 26WE, s 26WH | Breach playbook with a recorded assessment, severity triage and a clock `[merged: 17 NDB-01; 18 §11; 15 §8; 19 §14; 20 §15]` | Incident response process; incident register | Assessment records; decision log | Security Lead | Planned | 4 | 2026-10-04 |
| Notify the Commissioner and affected individuals if notifiable | Privacy Act 1988 (Cth) s 26WK, s 26WL | Statement generator and notification paths `[merged: 17 NDB-02; 18 §11]` | Incident response toolkit | Statement drafts; notification records | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Record the decision and the rationale even when not notifiable | OAIC NDB guidance | Mandatory decision record with reasons `[merged: 17 NDB-03]` | Incident register | Decision records | Security Lead | Planned | 4 | 2026-10-04 |
| Preserve evidence sufficient to reconstruct an incident | OAIC NDB guidance; ACSC and NIST logging guidance | Append-only audit and access logs retained beyond the assessment window `[merged: 17 NDB-04; 18 §11]` | Audit store; log retention | Access-window reconstruction test; custody records | Security Lead | Planned | 4 | 2026-10-04 |
| Documented incident response lifecycle and runbooks | Internal decision; NDB scheme | Lifecycle from detection to post-incident review, with eight runbooks `[merged: 17 IR-01]` | Source `18-incident-response.md` runbook set | Runbook set; rehearsal records | Security Lead | Planned | 4 | 2026-10-04 |
| Severity levels and response targets | Internal decision | SEV1 to SEV4 with definitions, examples, targets and paging `[merged: 17 IR-02]` | Incident response document | Severity table; paging configuration | Security Lead | Planned | 4 | 2026-10-04 |
| Post-incident review feeds the threat model and this register | Internal decision | Review within a stated window, with control and test updates `[merged: 17 IR-04; 18 §11]` | Post-incident process | Review records; register updates | Security Lead | Planned | 0–4 | 2026-10-04 |
| State health privacy principles per jurisdiction | NSW HRIP Act; Victorian HRA; equivalents | Jurisdiction attribute on tenant and patient; per-jurisdiction configuration with a review date `[merged: 12 §8; 17 STATE-02; 19 §14]` | Configuration and jurisdiction model | Rule table; review record | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Applicability assessment against the asset classes and responsible entity tests | Security of Critical Infrastructure Act 2018 (Cth) | Documented applicability assessment and register entry `[merged: 13 §7; 17 SOCI-01; 19 §14; 20 §15]` | Compliance register | Applicability note | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Intended purpose per module and the device boundary assessed | TGA therapeutic goods framework | Intended-purpose statement per module; no clinical decision claims `[merged: 17 TGA-04]` | Module documentation | Intended-purpose statements | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION | 4 | 2026-10-04 |
| Six-monthly Authorised Prescriber reporting where the pathway requires it | TGA Authorised Prescriber pathway | Reporting extract job with an approval record `[merged: 17 TGA-03; 08 Control summary; 22 §5]` | Reporting job; `reports` module | Extract and submission record | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION | 2 | 2026-10-04 |
| Essential Eight baseline mapped per environment | ACSC Essential Eight | Baseline controls mapped to the gates, with a stated maturity target `[merged: 17 E8-01 to E8-08; 19 §14; 20 §15; 21 §13]` | CI scanning, image policy, access control, backups | Gate records; scan reports | Security Lead | OPEN — the maturity target per environment is unconfirmed (source `17` O3) | 0–4 | 2026-10-04 |
| Compliance evidence: every control names an artefact and an owner | Internal control 12 | This register plus an evidence store keyed by control ID `[merged: 02 §1 control 12; 17 SBD-12; 24 §7]` | [`control-matrix.md`](control-matrix.md); evidence store | Versioned evidence store; signed checklists | Compliance/Auditor | Planned | 0–4 | 2026-10-04 |
| No compliance claim beyond what the evidence shows | Engineering instruction (`00-README.md` rule 6) | Every regulatory statement is a pointer to the instrument, not a conclusion; unresolved items are marked and owned | This register; [`open-questions.md`](open-questions.md) | Register rows with status and owner | Compliance Lead | Planned | 0–4 | 2026-10-04 |
| A control owner is a named person, not a role with no assignee | Internal decision | Control-owner map maintained with the matrix | Owner map | Owner map with a person per row | Compliance/Auditor | OPEN | 0–4 | 2026-10-04 |
| The control register is reviewed on a schedule and a stale row is an open item | Internal evidence discipline | Quarterly review with a review date per row; a stale-row report | Review process | Updated rows; stale-row report | Compliance/Auditor | Planned | 0–4 | 2026-10-04 |
| An incident converts into new or amended register rows | Internal decision | Post-incident review updates the threat model and this register `[merged: 17 IR-04]` | Post-incident process | Review records; register updates | Security Lead | Planned | 0–4 | 2026-10-04 |

---

## 11. The six invariants

The repo's six invariants are carried here as controls, not as prose. Each names the test that proves
it and the phase where that test lands. INV-2 is the clinical safety gate and is specified in full in
the Phase 3 spec. Source: [`docs/reference/build-contract.md` §5](build-contract.md#5-the-six-invariants).

| Requirement | Source (instrument or internal decision) | Control | Implementation | Evidence | Owner role | Status | Phase | Last reviewed |
|---|---|---|---|---|---|---|---|---|
| **INV-1** Tenant isolation holds even when the application forgets a filter | Internal decision (`00-README.md` rule 3); APP 11 | RLS policy with `FORCE` on every tenant table, plus a transaction-scoped tenant setting, plus the policy lint that fails CI for a table without one | Alembic RLS migrations; `core/db.py`; schema lint | `backend/tests/isolation/test_rls_holds_without_app_filter.py` output; schema lint output | Security Lead | Planned | 1 | 2026-10-04 |
| **INV-2** No prescription is dispatched without an `ACTIVE` TGA approval at the approval grain | TGA therapeutic goods framework; Authorised Prescriber pathway | One backend safety gate at the approval grain; no feature flag and no override parameter | `prescribing` module facade; `pharmacy` module | `backend/tests/security/test_dispatch_blocks_without_active_approval.py` output; negative dispatch matrix | Clinical Safety Officer | Planned | 3 | 2026-10-04 |
| **INV-3** Enforcement is backend-only; the frontend hides and warns, never decides | Internal decision (`00-README.md` rule 2) | Every permission recomputed server-side from identity, tenant and resource | `core/security.py` policy layer | `backend/tests/security/test_authz_recomputes_server_side.py` output | Security Lead | Planned | 1 | 2026-10-04 |
| **INV-4** Audit is append-only; the application role cannot `UPDATE` or `DELETE` it | Internal decision; APP 11 | No `UPDATE` or `DELETE` grant to the application role and no update policy on `audit_log` | `audit_log` grants in Alembic; single writer in `core/audit.py` | GRANT inspection test output | Security Lead | Planned | 1 | 2026-10-04 |
| **INV-5** No PHI appears in logs, metrics, traces or error responses | APP 11; OWASP A09 | Classification-driven redaction at the logger boundary, a sentinel value planted in test data, and an error envelope that leaks nothing | Redaction pipeline; error contract | `backend/tests/security/test_no_phi_in_log_payload.py` output; redaction unit tests | Security Lead | Planned | 1 | 2026-10-04 |
| **INV-6** Data stays in Australia; no production data leaves the approved region | Privacy Act 1988 (Cth) APP 8; internal decision | Region pinning, a CI region check on infrastructure code, an approved-region list, and a vendor register entry per flow | Region configuration; CI region check; residency register | Residency policy check output; vendor register rows; SCP listing | CTO + Compliance Lead | `OPEN` — D-004 unresolved; the stack is not yet pinned to a region | 0–4 | 2026-10-04 |

---

## 12. Control test index

The test suites that evidence the highest-consequence rows, and the phase in which each lands.
A row whose test does not exist is a `Planned` row whatever the implementation looks like. Adapted
from source `17-compliance-control-matrix.md` §10.2 and `27-security-testing.md`.

| Controls | Test suite | Runs | Evidence | Phase |
|---|---|---|---|---|
| INV-1, TEN-01…TEN-03 | Cross-tenant isolation suite across API, exports, files, search, caches and workers, asserting absence | CI on every pull request | Test report | 1 |
| INV-1 | `test_rls_holds_without_app_filter`, `test_pool_reuse` | CI | Test report | 1 |
| INV-4, AUD-01…AUD-03 | Audit append-only, tamper-evidence and write-failure alerting | CI plus a scheduled integrity check | Test report; integrity record | 1 and 4 |
| INV-2, RX-01…RX-03 | Prescription safety gate, expired and superseded approval blocks, human confirmation | CI plus a staging scenario run | Gate test report | 3 |
| INV-3 | `test_authz_recomputes_server_side`, permission matrix per role | CI | Test report | 1 |
| INV-5 | `test_no_phi_in_log_payload`, redaction unit tests, frontend storage scan | CI | Test report | 1 |
| INV-6, ENV-01, ENV-02 | Residency policy check, environment separation, de-identification of any extract | CI and a quarterly extract review | Configuration report; extract manifest | 0–4 |
| SEC-01…SEC-03 | Secret scanning, workload identity scope, break-glass expiry | CI and a scheduled access review | Scan output; review record | 0 and 4 |
| DOC-01…DOC-03 | Private bucket, signed-URL scope and expiry, upload validation and scanning | CI and a configuration check | Test and configuration report | 1–2 |
| SBD-01…SBD-12 | Security-by-design control tests | CI security pipeline | Pipeline report | 0–1 |
| APP-04, APP-06, APP-10, APP-12, APP-13 | Privacy control tests: purpose, notice version, validation, retention and correction | CI plus a scheduled review | Test report | 1–4 |
| IR-01…IR-04 | Incident runbook rehearsal and breach assessment record | Tabletop schedule | Exercise records | 4 |

---

## 13. Change control for this register

| Change | Approval |
|---|---|
| A new row | Compliance Lead |
| A change to a security control | CTO + Security Lead |
| A change to a clinical safety control | CTO + Clinical Safety Officer, with a Gate 4 re-run |
| A change to the tenant isolation model | CTO + Security Lead, with a Gate 2 re-run |
| A change to a regulatory position | CTO + legal/regulatory adviser |
| Removal of a row | CTO + Compliance Lead, with a recorded reason — never a silent delete |

Substantive change is a decision record or an update to this register, never an untracked edit. See
[`docs/reference/build-contract.md` §11](build-contract.md#11-change-control).

## Open items and assumptions

| # | Item | Owner role |
|---|---|---|
| O1 | Name a person behind every owner role in this register; a role with no assignee is an open item | Practice Owner |
| O2 | Confirm the phase assignment for each row against the approved phase set; this register maps phases from the phase chart, not from a sprint | Delivery Lead |
| O3 | Confirm the evidence store location, retention period and redaction standard | Compliance Lead |
| O4 | Decide whether a source row may be dropped entirely, and record the reason, for the rows deduplicated here | Compliance Lead |
| O5 | Confirm the evidence artefact for every `REQUIRES LEGAL/REGULATORY VALIDATION` row, per [`open-questions.md`](open-questions.md) | Compliance Lead |
| O6 | Reconcile this register with D-003 and D-004 when those decisions close | CTO |

## Sources

- `clinic-os-secure-by-design/17-compliance-control-matrix.md` — the requirement→control→implementation→evidence→owner→status pattern reproduced here
- `clinic-os-secure-by-design/02-security-architecture.md` §1, §10, Control table
- `clinic-os-secure-by-design/21-technical-design.md` §13
- `clinic-os-secure-by-design/23-sprint-plan.md` §12
- `clinic-os-secure-by-design/24-definition-of-done.md` §7
- `clinic-os-secure-by-design/26-security-gates.md` §10
- `clinic-os-secure-by-design/27-security-testing.md` §11
- `clinic-os-secure-by-design/01`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`, `12`, `13`, `14`, `15`, `16`, `18`, `19`, `20`, `22`, `28`, `29` — module control summaries and control tables
- `clinic-os-secure-by-design/25-adr/` — ADR-001 to ADR-011
- [`docs/reference/build-contract.md`](build-contract.md) — invariants, twelve controls, module map, phase map
- [`docs/reference/gates.md`](gates.md) — gate evidence and approvers
- [`docs/reference/definition-of-done.md`](definition-of-done.md) — the six-part test
