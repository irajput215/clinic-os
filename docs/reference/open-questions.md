---
doc_id: OZ-REF-OQ
title: Open questions, blocking decisions and the legal-validation register
owner: Compliance Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
source: ../../clinic-os-secure-by-design/90-owner-brief.md
---

# Open Questions and Legal-Validation Register

Every open item found in the normative source set and in this repo's own document set, in one place,
with an owner role and a status. Nothing here is resolved; nothing here is dropped.

> **Engineering instruction, not legal advice.** An item marked `REQUIRES LEGAL/REGULATORY VALIDATION`
> is a dependency on advice we do not have. It is not a task an engineer can close. A control that
> addresses the *engineering* half of a validation item does not close the item; see §4.

---

## 1. Blocking open decisions

Two decisions are open and each blocks a gate. Neither may be closed silently, and no work that
depends on either may proceed on an assumption.

| ID | Decision | Status | Blocks | Owner |
|---|---|---|---|---|
| [D-003](decisions/D-003-identity-model.md) | Identity model: adopt the source contract's managed OIDC provider (Option A) or harden self-hosted password auth (Option B) | 🔴 **OPEN — requires a decision** | **Gate 3 (Authentication)** cannot be signed. Gate 1 is also blocked if the threat model's authentication section stays unresolved. Partially affects Gate 2: the `users` table shape depends on this, but RLS and isolation evidence do not | CTO + Security Lead |
| [D-004](decisions/D-004-deployment-target.md) | Deployment target: the source contract's AWS shape (Option A), compose on a single Australian host (Option B), or compose for Development/Staging with AWS for Production (Option C) | 🔴 **OPEN — requires a decision** | **Gate 6 (Production)** cannot be signed. **Gate 7** is blocked transitively. Gate 1's environment-separation check **fails** until it is decided. Gates 2, 3, 4 and 5 are not blocked | CTO + Head of Platform |

### 1.1 What D-003 blocks, specifically

| Blocked work | Why it depends on D-003 | Record |
|---|---|---|
| The `users` table and its migration | A `hashed_password` column either exists (Option B) or does not (Option A) | [D-003](decisions/D-003-identity-model.md) |
| The auth module and session/revocation design | Session storage, revocation and token claims differ materially between the options | [D-003](decisions/D-003-identity-model.md) |
| MFA implementation and enrolment flow | Provider-configuration assertions (A) versus code we own forever (B) | [D-003](decisions/D-003-identity-model.md) |
| Account recovery, lockout and step-up | Same divergence | [D-003](decisions/D-003-identity-model.md) |
| Threat-model entries T-01.2 (brute force) and T-01.6 (privilege escalation) | The controls assumed to be bought (A) are built by us (B) | [`docs/features/01-tenancy-and-clinics/04-threat-model.md`](../features/01-tenancy-and-clinics/04-threat-model.md) |
| Gate 3's checklist evidence set | The artefact, the failure modes and the residual risk differ | [`gates.md`](gates.md#gate-3-authentication) |
| Frontend token-handling requirements | Source `02-security-architecture.md` §10 requirements 3 and 11 | [D-003](decisions/D-003-identity-model.md) |

**Not blocked by D-003:** Phase 0; and the tenancy, patient-register, RLS, audit-envelope and CI work
in Phase 1 that does not touch credential storage. The `tenants` table, RLS policies, `audit_log` and
the isolation suite are identity-agnostic.

### 1.2 What D-004 blocks, specifically

| Blocked work | Why it depends on D-004 | Record |
|---|---|---|
| All Phase 4 Gate 6 evidence | The source Gate 6 checks are written against the AWS shape (WAF, IAM, environment separation, restore drill) | [D-004](decisions/D-004-deployment-target.md) |
| Gate 7 evidence, transitively | Gate 6 is an entry criterion for Gate 7 | [`gates.md`](gates.md#gate-7-go-live) |
| The environment-separation model in Gate 1 | The check *"the environment separation model is defined for Development, Staging and Production"* fails until this is decided | [`gates.md`](gates.md#gate-1-architecture) |
| Every control-matrix row asserting residency or infrastructure hardening | INV-6 is currently unimplemented, not true | [`control-matrix.md`](control-matrix.md) |
| The worker entrypoint's process model | Separate container versus same container is a deployment-target question | [D-002](decisions/D-002-repo-layout.md) open item 2 |
| The secret-store abstraction | Written against an interface in Phase 0 so the move from `.env` to a managed store is configuration, not a rewrite | [D-004](decisions/D-004-deployment-target.md) |

**Not blocked by D-004:** Phases 0–3. The application, schema, RLS, audit and safety-gate work is
infrastructure-agnostic.

### 1.3 The third dependency

Naming the legal and privacy adviser who answers §2 is a **dependency, not a decision**. The 14
questions stay open and marked until someone with authority answers them. Owner: **Practice Owner**.
Source: `clinic-os-secure-by-design/90-owner-brief.md` §1.

### 1.4 Operational decisions raised by delivery

Not gate-blocking, but each one is the owner's to make and nothing changes until it is made.

| ID | Decision | Interim position (fail-safe) | Owner | Raised |
|---|---|---|---|---|
| **O-1** | FastAPI's native OpenTelemetry (`fastapi[standard]` 0.143 and later) can export request spans, metrics and logs over OTLP when the environment sets `FASTAPI_OTEL_AUTO_CONFIGURE=true` and an endpoint. Spans carry the request path (record ids) and the query string. Enabling it is a new data flow to the telemetry collector (INV-5, L3) | **Off.** `app/main.py` passes `NATIVE_TELEMETRY_OFF` (every signal off, environment auto-configuration refused); `tests/security/test_no_native_telemetry.py` holds it off | CTO + Privacy Officer | 2026-10-08, dependency update |

---

## 2. Legal and regulatory validation register

Every `L` item from `clinic-os-secure-by-design/90-owner-brief.md` §10, expanded with the decision
needed from `17-compliance-control-matrix.md` §10. **None of these may be closed by an engineer's
opinion.** Owner roles are the source's; where the source names two forms, both are recorded.

| ID | Question | What is needed | Owner role | Status |
|---|---|---|---|---|
| **L1** | Is ClinicOS an APP entity, an intermediary or a contracted service provider, and who notifies in a breach? | Entity and accountability allocation per customer | DPO / legal (Data Protection Officer, if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L2** | Retention periods per state and territory, and which applies to a patient who moves | The operative retention period per state and territory for private providers | Compliance (Compliance/Auditor) | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L3** | Cross-border position (APP 8) for every non-onshore flow | Does APP 8 apply, is there an exception, and is effective control retained? | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L4** | Is My Health Record in scope, and does the offshore-holding restriction apply? | My Health Record scope and the offshore-holding position | DPO / legal | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L5** | Is any module a medical device, and is the decision-support exemption available? | TGA device boundary per module | Compliance (Compliance/Auditor) | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L6** | Authorised Prescriber reporting fields, cadence and format | The exact reporting fields, cadence, format and evidence | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L7** | E-prescribing conformance: which register, which party, sunset dates | E-prescribing conformance and the conformant party | CTO | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L8** | Schedule 8 and real-time prescription monitoring mandatory checks per jurisdiction | The mandatory-check matrix per jurisdiction | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L9** | SOCI Act applicability and what flows down | Is ClinicOS or any customer a responsible entity, and what flows down? | Compliance (Compliance/Auditor) | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L10** | Programmatic-decision scope and what policy must disclose | Automated decision-making scope for December 2026 | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L11** | Minor capacity and guardian access rules per jurisdiction | The age of control and the access rules per jurisdiction | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L12** | Vendor contract terms: residency, breach notice, sub-processors, exit | Residency, breach notification, sub-processor flow-down and exit terms per vendor | Compliance (Compliance/Auditor) | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L13** | Cyber and professional indemnity cover, and customer contract risk allocation | Insurance cover and the customer contract terms | Practice Owner | REQUIRES LEGAL/REGULATORY VALIDATION |
| **L14** | Written Australian legal opinion covering privacy, retention, cross-border and contracts | Australian legal review of the whole position | Practice Owner | REQUIRES LEGAL/REGULATORY VALIDATION |

### 2.1 The two owner decisions that are not L items

| ID | Decision | Owner | Status |
|---|---|---|---|
| Owner decision 1 | Adopt secure-by-design as the build method, with seven enforced security gates | Practice Owner + CTO | OPEN |
| Owner decision 2 | Approve AWS Sydney (`ap-southeast-2`) as the only production region for clinical data, plus the residency register | Practice Owner | OPEN |

Source: `clinic-os-secure-by-design/90-owner-brief.md` §1. Decision 2 is the substance behind
[D-004](decisions/D-004-deployment-target.md) and INV-6.

---

## 3. Open items by source document

Every `## Open items and assumptions` row found in the source set, transcribed with its own number,
wording (abbreviated only where noted), owner role and status. `REQUIRES LEGAL/REGULATORY VALIDATION`
in the Status column is the source's own marker. `Open` means the source left it open without the
legal marker. `Planned` and blank-status rows are included because the source recorded them as open
items; a blank status means the source row carried no marker and this register does not invent one.

**Raw rows transcribed: 329.**

| Group | Tables | Raw rows |
|---|:---:|:---:|
| Source `00-build-prompt-traceability.md` | 1 | 4 |
| Source `01`–`29` (28 documents with an open-items section) | 28 | 195 |
| Source `25-adr/` (12 files: 11 ADRs plus the index) | 12 | 51 |
| This repo's reference documents (§3.4) | 8 | 39 |
| This repo's feature specifications (§3.5) | 3 | 26 |
| This document's own meta-items | — | 2 |
| **Total** | **52** | **329** |

The raw count is the number a reviewer can reconcile: **271** rows in the source set, **56** in this
repo's documents, plus this document's 2 meta-items. It is deliberately the raw count. A deduplicated
headline would hide which rows were judged to restate another, and that judgement is a review
decision, not a documentation one.

What overlaps, and where it is recorded:

| Overlap | Rows | Recorded at |
|---|:---:|---|
| Source-internal: nine ADR follow-up rows restating a numbered-document open item | 9 | §3.6 rows 1–9 |
| Source ↔ repo: source `24-definition-of-done.md` O1–O5 and repo [`definition-of-done.md`](definition-of-done.md) O1–O5 | 5 | §3.6 row 10 |
| Source ↔ repo: feature [`01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md) item 2 (source `06` §6), item 9 (source `06` O2), item 10 (source `05` O6) | 3 | §3.6 row 11 |
| Source ↔ repo: feature [`05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) O5 (source `04` O5), O6 (source `06` O5), O9 (source `04` O8), O10 (D-003 item 1) | 4 | §3.6 row 11 |
| Source ↔ repo: feature [`10-prescription-safety-gate/01-requirements.md`](../features/10-prescription-safety-gate/01-requirements.md) O1 (L7), O2 (L8) | 2 | §3.6 row 11 |
| Repo-internal: `sdlc/README.md` O1/O2 restate D-003/D-004 item 1; `gates.md` O1–O3 restate source `26`/`13` items already carried | 5 | §3.6 row 12 |
| **Distinct after the above** | **329 − 28 = 301** | |

**No row is dropped from its own table.** Each is listed where it was found, so a reviewer comparing
this register against the source — or against the feature specs — receives the same rows back.

Counts by document, for reconciliation against the source:

| Group | Documents | Raw rows per document |
|---|---|---|
| `00-*` | `00-build-prompt-traceability.md` | 4 |
| `01`–`29` | `01` 8 · `02` 8 · `03` 9 · `04` 8 · `05` 8 · `06` 7 · `07` 6 · `08` 7 · `09` 7 · `10` 8 · `11` 8 · `12` 8 · `13` 9 · `14` 9 · `15` 12 · `16` 10 · `17` 8 · `18` 10 · `19` 6 · `20` 7 · `21` 6 · `22` 6 · `23` 6 · `24` 5 · `26` 5 · `27` 6 · `28` 7 · `29` 10 | 195 |
| `25-adr/` | `README` 3 · `ADR-001` 4 · `ADR-002` 4 · `ADR-003` 4 · `ADR-004` 4 · `ADR-005` 4 · `ADR-006` 5 · `ADR-007` 5 · `ADR-008` 5 · `ADR-009` 5 · `ADR-010` 5 · `ADR-011` 5 | 51 |
| This repo, reference | `sdlc/README.md` 6 · `gates.md` 6 · `definition-of-done.md` 5 · `D-001` 2 · `D-002` 2 · `D-003` 6 · `D-004` 6 · `control-matrix.md` 6 | 39 |
| This repo, feature specs *(phase-era names)* | `01-tenancy-and-clinics/01-requirements.md` 10 · `05-patients/01-requirements.md` 10 · `10-prescription-safety-gate/01-requirements.md` 6 | 26 |
| This document | its own two meta-items | 2 |

The 26 feature-spec items are captured in §3.5 at the verification timestamp named there.

---

### 3.2 Source documents

#### `00-build-prompt-traceability.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| — | Every `REQUIRES LEGAL/REGULATORY VALIDATION` marker across the set, consolidated | Privacy Officer + legal adviser | Open |
| — | Contract terms for Parchment, OCR provider, notification provider (residency, breach notice, sub-processors) | Practice Owner | Open |
| — | Which state and territory health records regimes apply per pilot clinic | Legal adviser | Open |
| — | Confirmation that no master-prompt point beyond the four additions has been quietly re-scoped | CTO | Open |

#### `01-system-architecture.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Whether the platform is a regulated medical device for any current function, given intended purpose | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 2 | Whether we are a responsible entity, or a supply-chain dependency of one, under the Security of Critical Infrastructure Act 2018 (Cth) | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | My Health Record connection scope, and whether it is in this release | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 4 | RPO and RTO values, and the clinic's manual fallback for the outage interval | Practice Owner + CTO | Open |
| 5 | Peak concurrent staff and prescription volume, to size ECS and RDS | Engineering Lead | Open |
| 6 | Whether any tenant contract requires dedicated infrastructure or customer-managed keys | Commercial Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 7 | State and territory health records legislation applicable per tenant | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 8 | Exact terms of the identity provider contract, including support access to data | CTO + legal adviser | REQUIRES LEGAL/REGULATORY VALIDATION |

#### `02-security-architecture.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Whether MFA must be phishing-resistant (passkey or WebAuthn) for all clinical roles or only privileged roles, and what the identity provider supports at the required assurance level | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 2 | Whether APP 11 or a customer contract requires a specific encryption standard or FIPS-validated modules | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | Retention period for authentication and access logs, per jurisdiction | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 4 | Whether field-level encryption must extend to clinical narrative, which would remove full-text search | Clinical Safety Officer + Security Lead | Open |
| 5 | Identity provider contract terms, including support access to personal information | CTO + legal adviser | REQUIRES LEGAL/REGULATORY VALIDATION |
| 6 | Third-party penetration test scope, timing and remediation window before Production | Security Lead | Open |
| 7 | Whether any tenant contract imposes a stricter breach notification window than the Notifiable Data Breaches scheme | Commercial Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 8 | Content Security Policy compatibility with the current frontend bundle, to be proven in Staging | Frontend Lead | Open |

#### `03-threat-model.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Whether any current function makes the platform a regulated medical device, which would add a device-grade risk process to these modules | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 2 | The disclosure basis for each field sent to each third-party provider | Privacy Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | Whether a customer contract imposes breach notification timing or forensic obligations beyond the Notifiable Data Breaches scheme | Commercial Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 4 | Treatment decision for TH-017 (provider over-disclosure) at High residual risk | Privacy Lead + CTO | Open |
| 5 | Treatment decision for TH-022 (legacy `/api/state` over-return) until the endpoint is removed | Engineering Lead | Open |
| 6 | Treatment decision for TH-009 (retention job error) and the legal-hold model | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 7 | Endpoint security responsibilities that sit with the customer, and what the contract states | Practice Owner + legal adviser | REQUIRES LEGAL/REGULATORY VALIDATION |
| 8 | Independent penetration test scope and whether it covers the tenant isolation suite | Security Lead | Open |
| 9 | Whether insider-risk monitoring of staff access is required by a tenant contract, and its privacy basis | Privacy Lead | REQUIRES LEGAL/REGULATORY VALIDATION |

#### `04-database-erd.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | The statutory response clock and refusal grounds for access, correction and erasure requests in each jurisdiction | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 2 | Which record classes must be retained for which period, per state and territory, and whether audit logs form part of the clinical record | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | Whether an erasure request can be satisfied at all for a record under a retention obligation, and what is disclosed to the requester | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 4 | Whether field-level encryption must extend to clinical narrative, which would remove full-text search | Clinical Safety Officer + Security Lead | Open |
| 5 | Final decision on blind index key custody and rotation for `medicare_number` and `ihi` | Security Lead | Open |
| 6 | Whether partitioning of `clinical_record_versions` is needed at launch volume | Engineering Lead | Open |
| 7 | Whether consent model granularity matches the applicable state and territory requirements | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 8 | Whether patient merges must be reversible after a clinical event, and for how long | Clinical Safety Officer | Open |

#### `05-tenant-isolation.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Whether any current or pipeline customer contract requires schema or database separation, which would trigger the section 10 move | Commercial Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 2 | Whether a contractual term requires per-tenant encryption keys rather than a shared CMK domain | Commercial Lead + Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | Confirmation of the pooler configuration in each environment, including `server_reset_query`, before I-015 is treated as evidence | Cloud Lead | Open |
| 4 | Whether a practitioner working across two clinics is modelled as two user rows or one identity with two tenant memberships, and the isolation consequences | Engineering Lead + Clinical Safety Officer | Open |
| 5 | Whether platform-level audit events with a null tenant satisfy the applicable access-logging expectations | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 6 | Notification content and timing when a cross-tenant denial alert fires | Security Lead + legal adviser | REQUIRES LEGAL/REGULATORY VALIDATION |
| 7 | Whether the canary tenant approach is acceptable in a production-shaped Staging environment | Security Lead | Open |
| 8 | Whether My Health Record or another national rail imposes a stricter isolation or audit requirement on connected systems | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |

#### `06-authentication-rbac.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Which OIDC provider is contracted, and whether it offers Australian residency for identity data | CTO | Open |
| 2 | Whether a tenant contract mandates a specific authenticator class for Compliance/Auditor | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | The break-glass elevation path and its retrospective review process | Security Lead | Planned |
| 4 | Whether identity data (email, name, phone) is in scope of the residency register for every provider under consideration | Privacy Officer | Open |
| 5 | The `care_relationships` source of truth, and who maintains it when a patient changes clinic | Clinical Safety Officer | Open |
| 6 | Whether a patient-facing access path is ever in scope, and how an APP 12 access request would be authenticated | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| 7 | Alert routing and on-call ownership for the anomaly signals in section 7 | Security Lead | Planned |
| — | Assumption: the modular monolith serves authentication from the same service as the rest of the API, with no separate identity service | — | Assumption (unresolved) |

#### `07-audit-architecture.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | The retention period per audit event class and per jurisdiction | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| 2 | Whether S3 Object Lock `COMPLIANCE` mode is acceptable to the first enterprise customer | CTO | Open |
| 3 | The break-glass procedure for platform staff to read a tenant audit trail, and who approves it | Security Lead | Planned |
| 4 | The signed verification report format and where the signing key lives | Security Lead | Planned |
| 5 | Whether an audit-read purpose code is required for every filter, not only exports | Privacy Officer | Open |
| 6 | Partition granularity at expected audit volume, which depends on the unanswered volume questions | CTO | Open |
| — | Assumption: the audit writer runs as a worker in the same service family, consuming one queue | — | Assumption (unresolved) |

#### `08-tga-approval-model.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Whether the approval attaches to patient plus category plus dosage form, or is product-specific for some products | Head of Legal and Regulatory Affairs | REQUIRES LEGAL/REGULATORY VALIDATION |
| 2 | The authorised approval-number format and whether it is stable across pathways | TGA Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | The exact Authorised Prescriber reporting cycle, content and submission channel | TGA Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| 4 | The controlled vocabulary for `tga_category` and `dosage_form`, and who owns its maintenance | Clinical Safety Officer | Planned |
| 5 | Whether a missing reporting period must block prescribing for that prescriber | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| 6 | Whether approval records for a patient who transfers between tenants are re-created or migrated | Privacy Officer | Open |
| 7 | Whether the two-year window is fixed by the pathway or set by the approval instrument | TGA Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| — | Assumption: the two-year validity window is a property of the approval, not of a prescription episode | — | Assumption (unresolved) |

#### `09-prescription-safety-gate.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | The controlled vocabulary mapping a medicine to a TGA category and a dosage form, and its owner | Clinical Safety Officer | Open |
| 2 | Whether any pathway requires the approval to be checked at sign as well as at dispatch, and whether a sign-time block is clinically acceptable | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | The jurisdiction matrix for real-time prescription monitoring mandatory checks in gate 9 | Head of Legal and Regulatory Affairs | REQUIRES LEGAL/REGULATORY VALIDATION |
| 4 | The duplicate-dispatch window (the period within which a near-duplicate requires a reason) | Clinical Safety Officer | Planned |
| 5 | The reconciliation threshold before escalation, and the on-call owner of unresolved non-terminal prescriptions | CTO | Planned |
| 6 | Whether a pharmacist-initiated dispatch path is in scope for the first release | Product Owner | Open |
| 7 | Whether blocking prescribing on a missing Authorised Prescriber report is required, which would add a gate 9 rule | TGA Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| — | Assumption: the platform does not mint eScript barcodes, does not choose therapy, and does not assume medical liability | — | Assumption (unresolved) |

#### `10-integration-boundaries.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | The Parchment contract terms, including rate limits, processing location and liability allocation | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| 2 | Whether request signing is supported by Parchment, Tyro and the notification provider, and the exact scheme | Head of Integrations | Open |
| 3 | The Tyro acquiring agreement and whether the platform is in scope for the payment card industry standard, and at what level | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| 4 | The residency of each provider's processing and support access | Privacy Officer | Open |
| 5 | Whether the notification provider can be constrained to an Australian region | Head of Integrations | Open |
| 6 | The manual fallback procedure when the eScript rail is unavailable, and who owns it clinically | Clinical Safety Officer | Planned |
| 7 | Whether any provider requires an interface agreement or a conformance register entry that is not yet in place | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| 8 | The exact retry and circuit breaker settings, once the provider's published limits are known | Head of Integrations | Planned |
| — | Assumption: the platform is a network client and webhook receiver only; it never hosts a provider component | — | Assumption (unresolved) |

#### `11-tga-inbox-pipeline.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | The confidence threshold values, with clinical sign-off and a documented rationale | Clinical Safety Officer | Open |
| 2 | Whether a regulator prescribes an extraction or verification standard for approval correspondence | Head of Legal and Regulatory Affairs | REQUIRES LEGAL/REGULATORY VALIDATION |
| 3 | Whether content disarm and reconstruction is safe for the PDFs these clinics rely on | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| 4 | The mailbox provider, its processing location and its retention of inbound mail | Privacy Officer | Open |
| 5 | Whether the tenant expects to forward TGA mail from its own address, which changes the sender allow-list design | Head of Integrations | Open |
| 6 | The suite of document layouts the extraction must handle, and the maintenance owner when a layout changes | Head of Integrations | Planned |
| 7 | Whether the review queue is staffed by the clinic or by a shared service, which changes the alert routing | Clinical Safety Officer | Open |
| 8 | Whether automatic creation of a `PENDING` record above a higher threshold should ever be enabled | Clinical Safety Officer | Open |
| — | Assumption: the pipeline creates and verifies approval records; it never dispatches a prescription or merges a patient | — | Assumption (unresolved) |

#### `12-data-classification.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the legal characterisation of each field as personal information, sensitive information or neither, per clinic and per jurisdiction | Data Protection Officer (if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION |
| O2 | Confirm whether the de-identification method satisfies the Privacy Act 1988 (Cth) definition of de-identified for each approved extract | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Confirm whether `gender_identity`, `reproductive_health_note` and `substance_use_note` require a level above HIGHLY_SENSITIVE or an additional access control | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O4 | Decide the retention period for de-identified extracts used in Staging. Recommendation: 30 days with key deletion | Engineering Lead | Open |
| O5 | Decide whether per-tenant KMS keys are required for HIGHLY_SENSITIVE fields at launch or deferred with a written risk | CTO | Open |
| O6 | Confirm the audit-event treatment of `reason` free text where it duplicates clinical content | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O7 | Confirm that no error-monitoring or session-replay tool receives HIGHLY_SENSITIVE content, and record the vendor configuration as evidence | Security Lead | Open |
| O8 | Assign the named role that owns the classification lint and its quarterly review | Engineering Lead | Open |

#### `13-data-residency.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Obtain and record the hosting region, sub-processor list and residency commitment for Parchment, Tyro, the identity provider, the notification provider, the OCR service, error monitoring and support tooling | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| O2 | Confirm whether the Parchment to pharmacy leg involves a cross-border disclosure by ClinicOS or by Parchment | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Confirm whether any My Health Record data is in scope and, if so, whether the offshore-holding restriction applies | Data Protection Officer (if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION |
| O4 | Confirm the APP 8 "use versus disclosure" characterisation for each offshore processor, including whether effective control is retained | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O5 | Define and version the approved region list, including the narrow exceptions service control policies must permit | CTO | Open |
| O6 | Confirm the retention applied to notification delivery logs and error monitoring data at each vendor. Recommendation: 90 days and 30 days | Privacy Officer | Open |
| O7 | Confirm whether support engineers or support tooling may be offshore, and the controls that would be required | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| O8 | Confirm whether cross-region backup replication is ever permitted, and under which approval | CTO | Open |
| O9 | Confirm the state transborder grounds that apply to Victorian and other jurisdiction patients whose data is processed in `ap-southeast-2` | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |

#### `14-retention-and-deletion.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the retention rule per jurisdiction for private providers, including the states where the research did not verify primary legislation | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| O2 | Confirm which jurisdiction's rule applies to a patient who moves, and who must prove destruction, the clinic or the platform | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Confirm whether a backup containing a deleted record must be purged or can be put beyond use | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O4 | Confirm how a deletion request interacts with the append-only audit obligation and with the correction workflow | Data Protection Officer (if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION |
| O5 | Confirm the response timeframe and the permitted refusal grounds for an access request in each jurisdiction | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O6 | Adopt or amend the recommended periods in the schedule: 12 months for authentication and access logs, 90 days for integration logs, 30 days for OCR artefacts, 7 years for DSAR records | Privacy Officer | Open |
| O7 | Confirm whether controlled medicine records carry a longer state retention requirement than the clinical record | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O8 | Confirm the transfer-note requirements when a practice closes or a patient transfers, and who generates them | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| O9 | Decide whether the purge job requires dual approval at launch or a single named approver with a report | CTO | Open |

#### `15-privacy-impact-assessment.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm whether ClinicOS is an APP entity, an intermediary or a contracted service provider for each customer, and who notifies in a breach | Data Protection Officer (if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION |
| O2 | Confirm the consent and collection basis for health information per jurisdiction, including the permitted health situations | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Confirm whether any My Health Record integration is in scope and whether the offshore-holding restriction applies | Data Protection Officer (if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION |
| O4 | Confirm the secondary-use basis for analytics, benchmarking and product improvement on health data | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O5 | Confirm the age at which a minor controls their own record in each jurisdiction and the guardian access rules | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O6 | Confirm the APP 9 basis for each use of a Medicare number or IHI | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O7 | Confirm the access request response timeframe and permitted refusal grounds | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O8 | Build the automated decision-making register before December 2026 and confirm which features are in scope | Privacy Officer | Open |
| O9 | Confirm whether the Children's Online Privacy Code applies to any patient-facing surface | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O10 | Confirm the state transborder grounds for each jurisdiction whose patients are served from `ap-southeast-2` | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| O11 | Draft the privacy policy, collection notices and the per-tenant policy generation | Privacy Officer | Open |
| O12 | Confirm the data breach response plan and rehearse it with named people, not roles | Security Lead | Open |

#### `16-vendor-register.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Sight and record the executed contract, data processing terms, breach notification terms and sub-processor list for every vendor | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| O2 | Record the hosting region and support locations for the identity provider, Parchment, OCR, notification, error monitoring, logging, source control and support tooling | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Confirm whether Parchment's onward disclosure to a dispensing pharmacy is a ClinicOS disclosure or Parchment's own | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O4 | Confirm the TGA correspondence channel's transport, retention and handling obligations | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| O5 | Confirm the OCR vendor's no-training commitment and its deletion of documents and derived text | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| O6 | Confirm PCI scope allocation with Tyro and that no card data enters ClinicOS | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| O7 | Select a managed logging, SIEM or analytics service if retained, and add it as its own vendor row | Engineering Lead | Open |
| O8 | File the AWS compliance reports and the data processing addendum in the evidence store | Security Lead | Open |
| O9 | Define the minimum data set per vendor in writing, and test that the integration sends no more | Privacy Officer | Open |
| O10 | Confirm the retention of support tickets and whether ticket text may ever contain patient content | Privacy Officer | Open |

#### `17-compliance-control-matrix.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Every row currently marked Planned or In progress needs an evidence artefact before the pilot gate | Compliance/Auditor | Open |
| O2 | Confirm the legal and regulatory items L1 to L14 before production | Practice Owner | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Confirm the maturity target for the Essential Eight mapping per environment | Security Lead | Open |
| O4 | Confirm whether an ISM or IRAP assessment is required by any customer contract | CTO | Open |
| O5 | Confirm the control-owner map so every row has one accountable person, not a role with no assignee | Compliance/Auditor | Open |
| O6 | Confirm the evidence-store retention period and the redaction standard for evidence containing personal information | Privacy Officer | Open |
| O7 | Confirm the process that converts an incident into new or amended matrix rows | Security Lead | Open |
| O8 | Confirm whether any customer requires a control matrix against ISO/IEC 27001 or SOC 2 as well as this one | Practice Owner | Open |

#### `18-incident-response.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the statutory breach assessment window, the notification timeframes and the serious harm test as they apply to ClinicOS | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O2 | Confirm who notifies when a breach affects several clinics and the platform | Data Protection Officer (if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Name individuals in the contact tree and the on-call rota, with a backup for each | Security Lead | Open |
| O4 | Confirm the response targets and agree them with the Practice Owner, and check them against any customer contract | CTO | Open |
| O5 | Select and contract an incident response retainer and confirm the cyber-insurance notification path | Practice Owner | Open |
| O6 | Confirm the legal privilege position for incident artefacts and communications | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| O7 | Confirm whether any ransomware payment reporting obligation applies | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
| O8 | Confirm the My Health Record breach notification path if that integration is built | Data Protection Officer (if appointed) | REQUIRES LEGAL/REGULATORY VALIDATION |
| O9 | Schedule the first tabletop exercises before launch and record the outcomes | Security Lead | Open |
| O10 | Confirm the internal clock that starts the assessment and how it is recorded in the incident register | Security Lead | Open |

#### `19-project-charter.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the conformance register and the conformant party for the eRx rail | Compliance Lead | Open |
| O2 | Confirm whether the platform is captured by the Security of Critical Infrastructure Act 2018 (Cth) | Compliance Lead | Open |
| O3 | Confirm the residency position for the pilot, including any My Health Record dimension | Legal / regulatory adviser | Open |
| O4 | Confirm the six-monthly reporting fields and the accepted evidence format | Clinical Safety Officer | Open |
| O5 | Confirm the funded envelope for penetration testing, legal advice and vendor fees | Practice Owner | Open |
| O6 | Confirm the pilot clinic staffing model for the human verification step | Head of Product | Open |

#### `20-product-requirements.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the six-monthly report fields and the accepted evidence format | Clinical Safety Officer | Open |
| O2 | Confirm RPO and RTO with the business before M4 | Practice Owner | Open |
| O3 | Confirm the residency position and any My Health Record dimension | Legal / regulatory adviser | Open |
| O4 | Confirm the treating-relationship rule per role and per clinic model | Clinical Safety Officer | Open |
| O5 | Confirm the confidence thresholds for auto-verify versus human review | Head of Product | Open |
| O6 | Confirm the retention schedule per record type and jurisdiction | Compliance Lead | Open |
| O7 | Confirm whether notifications may carry a patient name on any channel | Compliance Lead | Open |

#### `21-technical-design.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the transaction-mode pooling configuration of the chosen driver and prove reset behaviour | Head of Platform | Open |
| O2 | Confirm the removal observation window for `/api/state` | CTO | Open |
| O3 | Confirm the OCR or extraction component and its data-processing position | Head of Product | Open |
| O4 | Confirm the RPO and RTO feeding the backup and Multi-AZ design | Practice Owner | Open |
| O5 | Confirm the residency position before production data is held | Legal / regulatory adviser | Open |
| O6 | Confirm the audit retention period per jurisdiction | Compliance Lead | Open |

#### `22-user-stories.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm velocity after Sprint 1 and re-plan Sprints 2 and 3 | Delivery Lead | Open |
| O2 | Confirm the six-monthly report fields with the clinical adviser | Clinical Safety Officer | Open |
| O3 | Confirm the confidence threshold values used in US-17 | Head of Product | Open |
| O4 | Confirm the retention period applied to export artefacts | Compliance Lead | Open |
| O5 | Confirm the treating-relationship rule for each persona | Clinical Safety Officer | Open |
| O6 | Confirm whether a pharmacy identity may read any field beyond the dispatched prescription | Compliance Lead | Open |

#### `23-sprint-plan.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm measured velocity after Sprint 1 | Delivery Lead | Open |
| O2 | Confirm Parchment sandbox availability from week 0 | CTO | Open |
| O3 | Confirm the golden set of approval letters and its labelling owner | Clinical Safety Officer | Open |
| O4 | Confirm RPO and RTO before the M4 restore drill | Practice Owner | Open |
| O5 | Confirm penetration test booking before the end of Sprint 3 | Security Lead | Open |
| O6 | Confirm the pilot clinic training schedule for the verification step | Head of Product | Open |

#### `24-definition-of-done.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the pull request template embeds the six-part checklist | Delivery Lead | Open |
| O2 | Confirm the exception register location and review cadence | Compliance Lead | Open |
| O3 | Confirm the compensating-control standard for accepted High findings | Security Lead | Open |
| O4 | Confirm who signs the clinical acceptance when the Clinical Safety Officer is unavailable | Clinical Safety Officer | Open |
| O5 | Confirm the evidence bundle retention period | Compliance Lead | Open |

> Duplicate of this repo's [`definition-of-done.md`](definition-of-done.md) open items O1–O5, which are
> the same five items restated. Counted once towards the headline total.

#### `26-security-gates.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the penetration test booking date before Gate 6 | Security Lead | Open |
| O2 | Confirm the RPO and RTO that the restore drill is measured against | Practice Owner | Open |
| O3 | Confirm the interim position for each item marked REQUIRES LEGAL/REGULATORY VALIDATION before Gate 7 | Compliance Lead | Open |
| O4 | Confirm the on-call rota and the named on-call person for the pilot | Head of Platform | Open |
| O5 | Confirm the risk acceptance register format and storage | Compliance Lead | Open |

> Duplicate of this repo's [`gates.md`](gates.md) open items O1–O5, which are the same five items
> restated. Counted once towards the headline total.

#### `27-security-testing.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the penetration test provider, scope and booking date | Security Lead | Open |
| O2 | Confirm the remediation SLA values with the Practice Owner before the pilot | Practice Owner | Open |
| O3 | Confirm the DAST tool and its authenticated session handling | Security Lead | Open |
| O4 | Confirm the golden set storage location and access control | Clinical Safety Officer | Open |
| O5 | Confirm the sentinel value inventory and its leak-test integration | Head of Platform | Open |
| O6 | Confirm the retention period for scan reports and test evidence | Compliance Lead | Open |

#### `28-aws-network-and-deployment.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the RPO and RTO with the business before they are relied on | Practice Owner | Open |
| O2 | Confirm the AWS account structure and the region guardrail mechanism | Head of Platform | Open |
| O3 | Confirm the third availability zone decision before address space is reused | Head of Platform | Open |
| O4 | Confirm the audit and log retention periods per jurisdiction | Compliance Lead | Open |
| O5 | Confirm the geo restriction decision with the pilot clinic | Security Lead | Open |
| O6 | Confirm the disaster recovery runbook and its named roles | Head of Platform | Open |
| O7 | Confirm the monthly budget alarm threshold | Practice Owner | Open |

#### `29-operations-and-observability.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Agree the availability target and the RPO and RTO with the Practice Owner; no figure is assumed here | CTO | Open |
| O2 | Confirm whether any log sink, trace backend, error monitor or SIEM is offshore, and add the register row | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Confirm the log retention per category against the breach assessment window and the retention schedule | Privacy Officer | Open |
| O4 | Confirm the rotation cadence per secret class against provider policy and key-management guidance | Security Lead | Open |
| O5 | Confirm the session-recording capability for production access and the privacy position for recorded sessions | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O6 | Assign the on-call rota and the alert routes to named people, with a backup | Engineering Lead | Open |
| O7 | Confirm the sampling rate for tracing and that no trace backend captures request bodies | Engineering Lead | Open |
| O8 | Confirm the clinical fallback when the platform or a provider is unavailable | Clinical Safety Officer | Open |
| O9 | Confirm whether cross-region replication is ever permitted for recovery, and the residency position if it is | CTO | REQUIRES LEGAL/REGULATORY VALIDATION |
| O10 | Confirm the latency budget for the clinical record query end to end, including the browser, against the 200 ms p95 server target | Engineering Lead | Open |

---

### 3.3 Source ADR set

#### `25-adr/README.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm that ADR-001 to ADR-011 are accepted at the first architecture review | CTO | Open |
| O2 | Confirm the residency position underpinning ADR-003 and ADR-008 | Legal / regulatory adviser | Open |
| O3 | Confirm the Terraform adoption trigger date against the staging milestone | Head of Platform | Open |

#### `25-adr/ADR-001-postgresql.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the RDS instance class, storage and Multi-AZ shape for production | Head of Platform | Open |
| F2 | Confirm the backup retention period against the retention schedule | Compliance Lead | Open |
| F3 | Confirm the partitioning threshold for `audit_log` | Head of Platform | Open |
| F4 | Confirm the migration and rollback standard for production | CTO | Open |

#### `25-adr/ADR-002-postgresql-rls-tenant-isolation.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the pool mode and prove reset behaviour with `tenant-isolation.pool-reuse` | Head of Platform | Open |
| F2 | Add the schema lint rule that fails CI when a tenant table lacks a policy | CTO | Open |
| F3 | Confirm the alert threshold for cross-tenant authorisation denials | Security Lead | Open |
| F4 | Confirm the administrative role used for migrations and its audit | Head of Platform | Open |

#### `25-adr/ADR-003-aws-sydney-deployment.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the account structure and the region guardrail mechanism | Head of Platform | Open |
| F2 | Confirm the residency position with an Australian legal adviser | Legal / regulatory adviser | REQUIRES LEGAL/REGULATORY VALIDATION |
| F3 | Complete vendor region assessments for observability, email, SMS and extraction providers | Compliance Lead | Open |
| F4 | Confirm the manual clinical fallback with the pilot clinic | Clinical Safety Officer | Open |

#### `25-adr/ADR-004-docker.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the base image choice per service and record the digest pinning policy | Head of Platform | Open |
| F2 | Confirm the read-only filesystem exception list | Head of Platform | Open |
| F3 | Confirm the base image update cadence and owner | Security Lead | Open |
| F4 | Confirm the ECR tag immutability and retention policy | Head of Platform | Open |

#### `25-adr/ADR-005-modular-monolith.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Define the module ownership map and the lint rule that enforces it | CTO | Open |
| F2 | Confirm the separate task definitions and scaling policy for backend and worker | Head of Platform | Open |
| F3 | Identify the first extraction candidate and the metric that would justify it | CTO | Open |
| F4 | Confirm that the prescribing path remains in one transaction through the pilot | Clinical Safety Officer | Open |

#### `25-adr/ADR-006-authentication-architecture.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the OIDC provider and its residency and sub-processor status | Security Lead | Open |
| F2 | Confirm the access token lifetime, refresh lifetime, idle and absolute session timeouts | Security Lead | Open |
| F3 | Confirm the lockout threshold and the account release procedure | Security Lead | Open |
| F4 | Confirm the step-up validity window with the clinical adviser | Clinical Safety Officer | Open |
| F5 | Confirm the identity provider outage degradation behaviour | Head of Platform | Open |

#### `25-adr/ADR-007-audit-architecture.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the audit retention period per jurisdiction | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| F2 | Confirm the Object Lock mode and retention duration | Security Lead | Open |
| F3 | Confirm the partition and lifecycle schedule for `audit_log` | Head of Platform | Open |
| F4 | Maintain the high-risk operation list used by the coverage test | Head of Product | Open |
| F5 | Confirm the buffering and alert behaviour for a stream outage | Head of Platform | Open |

#### `25-adr/ADR-008-s3-document-storage.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the presigned URL lifetime and its review trigger | Security Lead | Open |
| F2 | Confirm the lifecycle and expiry rules per bucket | Head of Platform | Open |
| F3 | Confirm the retention period per document class | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| F4 | Confirm the backup and restore procedure for objects and keys | Head of Platform | Open |
| F5 | Confirm the key policy per environment and the separation from the audit archive key | Security Lead | Open |

#### `25-adr/ADR-009-tga-ingestion-architecture.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the golden set size, labelling owner and storage location | Clinical Safety Officer | Open |
| F2 | Confirm the confidence thresholds per field and the review trigger | Head of Product | Open |
| F3 | Confirm the OCR or extraction component and its data-processing position | Compliance Lead | Open |
| F4 | Confirm the false-approval rate metric and its alert threshold | Clinical Safety Officer | Open |
| F5 | Confirm the filing reversal procedure and its approval path | Clinical Safety Officer | Open |

#### `25-adr/ADR-010-parchment-integration.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm sandbox access, credentials and the contract support path | CTO | Open |
| F2 | Confirm the non-terminal alert threshold and the reconciliation cadence | Head of Platform | Open |
| F3 | Confirm the conformance responsibility split with the certified party | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| F4 | Confirm the provider credential owner and rotation procedure | Security Lead | Open |
| F5 | Confirm the provider-outage clinical fallback with the pilot clinic | Clinical Safety Officer | Open |

#### `25-adr/ADR-011-terraform-adoption.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| F1 | Confirm the remote backend, locking mechanism and state encryption | Head of Platform | Open |
| F2 | Confirm the module structure and the environment layout | Head of Platform | Open |
| F3 | Confirm the drift detection schedule and its owner | Security Lead | Open |
| F4 | Confirm the pipeline identity permissions and its separation per environment | Security Lead | Open |
| F5 | Record the pre-adoption manual Development gap in the risk register with an expiry | Delivery Lead | Open |

### 3.4 This repo's documents

#### `docs/reference/build-contract.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm whether identity stays self-hosted or moves to a managed OIDC provider (D-003) | CTO + Security Lead | OPEN |
| O2 | Confirm the deployment target: compose on a single host, or the source contract's ECS/RDS/S3/SQS (D-004) | CTO + Head of Platform | OPEN |
| O3 | ~~Confirm whether `/api/state` exists in this codebase or only in the source's predecessor prototype~~ **RESOLVED 2026-10-04:** it does **not** exist in this repo. The source's strangler migration is out of scope unless a legacy client is found, and the Phase 1 "state synchronisation" workstream is de-scoped pending confirmation | Head of Product | **Resolved** — the one resolved item in this register, recorded with its answer rather than deleted |
| O4 | Confirm measured velocity after Phase 1; the source's 40 points/sprint is an assumption, not a measurement | Delivery Lead | Open |
| O5 | Name the legal and privacy adviser who answers this register | Practice Owner | Open |
| O6 | Confirm the region decision (the stack is not yet pinned to `ap-southeast-2`) | CTO + Compliance Lead | Open |

#### `docs/reference/gates.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the penetration test booking date before Gate 6 | Security Lead | Open |
| O2 | Confirm the RPO and RTO the restore drill is measured against | Practice Owner | Open |
| O3 | Confirm the interim position for each `REQUIRES LEGAL/REGULATORY VALIDATION` item before Gate 7 | Compliance Lead | Open |
| O4 | Confirm the on-call rota and named on-call person for the pilot | Head of Platform | Open |
| O5 | Confirm the risk acceptance register format and storage | Compliance Lead | Open |
| O6 | Confirm the approver when the named approver role is unfilled (single-person team) | Practice Owner | Open |

#### `docs/reference/definition-of-done.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Confirm the pull request template embeds the six-part checklist | Delivery Lead | Open |
| O2 | Confirm the exception register location and review cadence | Compliance Lead | Open |
| O3 | Confirm the compensating-control standard for accepted High findings | Security Lead | Open |
| O4 | Confirm who signs clinical acceptance when the Clinical Safety Officer is unavailable | Clinical Safety Officer | Open |
| O5 | Confirm the evidence bundle retention period | Compliance Lead | Open |

#### `docs/reference/decisions/D-001-python-fastapi-stack.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Confirm that OpenAPI-generated client types are treated as a release artefact, with the parity test required by frontend security requirement 6 | Frontend Lead | Open |
| 2 | Confirm `mypy --strict` covers `modules/**` and that `alembic/` stays excluded | CTO | Open |

#### `docs/reference/decisions/D-002-repo-layout.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Confirm whether `packages/shared/` is needed at all, given types are generated from OpenAPI | Frontend Lead + CTO | Open |
| 2 | Confirm the worker entrypoint's process model once D-004 is closed | Head of Platform | Open |

#### `docs/reference/decisions/D-003-identity-model.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Choose Option A or Option B | CTO + Security Lead | OPEN |
| 2 | If A: candidate IdP, its Australian data-processing position, and its contract terms | CTO + Compliance Lead | OPEN |
| 3 | If A: whether the IdP's MFA is phishing-resistant (passkey/WebAuthn) at the required assurance level | Security Lead | OPEN |
| 4 | If B: the Argon2id parameter set and the key-rotation procedure for any signing key | Security Lead | OPEN |
| 5 | Either way: who holds the signing key material, and how it rotates without invalidating live sessions | Security Lead | OPEN |
| 6 | Reconcile `docs/features/01-tenancy-and-clinics/` with whichever option is chosen | Security Lead | OPEN |

#### `docs/reference/decisions/D-004-deployment-target.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Choose Option A, B or C | CTO + Head of Platform | OPEN |
| 2 | Confirm the production region and prove it, so INV-6 has evidence rather than an intention | CTO + Compliance Lead | OPEN |
| 3 | Review the committed root `.env` for any real secret and rotate if found. **VERIFIED 2026-10-04 by the security review:** `.env` **is** tracked in git (`git ls-files .env` returns it) and holds `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD` and `POSTGRES_PASSWORD`, all at the template default `changethis`. Not a leaked production secret today, but a live violation of source control 8, and `SECRET_KEY=changethis` permits JWT forgery if deployed. Recorded as a **Phase 0 exit task**: untrack, add to `.gitignore`, ship `.env.example`, rotate every value ever committed. **2026-10-07:** untracked by #11; the repository is public, so the committed template defaults (`changethis`) are public; production secrets were never committed and live in GitHub secrets and the FastAPI Cloud environment, reported set by the owner; full-history gitleaks clean apart from three upstream-template false positives | Security Lead | **Untracked; rotation reported done by the owner (2026-10-07); evidence of rotation still to be attached** |
| 4 | Confirm RPO and RTO, which Gate 6's restore drill is measured against | Practice Owner | OPEN |
| 5 | Confirm which Gate 6 checks are replaced under Option B, and with what evidence | Security Lead | OPEN |
| 6 | Decide whether Infrastructure-as-Code is Terraform or compose-only, and record it as its own decision | Head of Platform | OPEN |

#### `docs/reference/control-matrix.md`

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | Name a person behind every owner role in the register; a role with no assignee is an open item | Practice Owner | Open |
| O2 | Confirm the phase assignment for each row against the approved phase set | Delivery Lead | Open |
| O3 | Confirm the evidence store location, retention period and redaction standard | Compliance Lead | Open |
| O4 | Decide whether a deduplicated source row may be dropped entirely, and record the reason | Compliance Lead | Open |
| O5 | Confirm the evidence artefact for every validation row | Compliance Lead | Open |
| O6 | Reconcile the register with D-003 and D-004 when those decisions close | CTO | Open |

### 3.5 Feature specifications under construction

The feature specification layer at [`docs/features/`](../features/) was being written concurrently with
this register. The items below were captured at **2026-10-04**, which is the verification
timestamp for this subsection. At that timestamp the phase-era specs `03-clinical-records/spec.md` and
`04-tga-approval-engine/spec.md` carried no open-items section, and `05-prescription-safety-gate/spec.md`
was still being added. Those phase-era files have since been superseded by the numbered feature folders
— all 17 of which now carry an `## Open items` section — so the names above are historical; see
[`traceability.md`](traceability.md) §3.2.
Each feature spec owns its own open items — those tables are the system of record, and this subsection
is a checkpoint, not a second register.

#### `docs/features/01-tenancy-and-clinics/01-requirements.md` (§6.3)

| # | Item | Owner role | Status |
|---|---|---|---|
| 1 | Close D-003 (Option A or B); reconcile this spec with the chosen branch | CTO + Security Lead | OPEN |
| 2 | Reconcile the lockout threshold: 5 (PRD) versus 10 in 15 minutes (source `06` §6) | Security Lead | OPEN |
| 3 | Reconcile the access-token lifetime: 10 minutes (source `06` §3) versus 15 minutes (source `02` §1; repo README) | CTO + Security Lead | OPEN |
| 4 | Reconcile the two permission vocabularies and the ERD's "20 permissions" versus the 19 listed | CTO | OPEN |
| 5 | Reconcile the error-envelope shapes: nested (source `21` §7; repo DoD §4) versus flat (source `02` §7) | Security Lead | OPEN |
| 6 | Specify the `clinics` table columns and classification | Head of Platform + Privacy Officer | OPEN |
| 7 | Confirm whether the `sessions`, `mfa_enrolments`, `login_attempts` and `account_lockouts` tables named by PRD §2 replace or supplement `refresh_tokens` | Engineering Lead | OPEN |
| 8 | Confirm the route prefix `/api/v1/clinics` versus the PRD's `/admin/clinics` | Head of Platform | OPEN |
| 9 | Confirm whether a tenant contract mandates a specific authenticator class for Compliance/Auditor | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| 10 | Confirm the breach-notification path and timing when a cross-tenant denial alert fires | Security Lead + legal adviser | REQUIRES LEGAL/REGULATORY VALIDATION |

#### `docs/features/05-patients/01-requirements.md` (§7)

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | The search term sits in the query string (`GET /api/v1/patients/search?q=`) while source `02` §10 requirement 10 forbids search terms in URLs. Decide: POST search, an opaque token, or a documented exception | Security Lead + Head of Product | OPEN |
| O2 | Confirm the Medicare check-digit algorithm, the IRN rule and the IHI format against the issuing authority. The source contract does not specify them; only the redaction patterns `\d{10}` and `800360\d{10}` are cited | Head of Product + Privacy Officer | OPEN / REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | Ratify the minimum search query length. ≥ 3 characters is the draft's engineering floor, not a source requirement | Head of Product | OPEN |
| O4 | Reconcile `patient_identifiers` (named in the PRD and module map) with the ERD, which holds identifiers on `patients` | CTO + Head of Product | OPEN |
| O5 | Blind-index key custody and rotation for `medicare_number` and `ihi` | Security Lead | OPEN (source `04` open item 5) |
| O6 | `care_relationships` is read by the authorisation layer but has no ERD table definition and no named owner | Clinical Safety Officer | OPEN (source `06` §11 open item 5) |
| O7 | Per-jurisdiction retention periods and the minor-capacity/guardian rules | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O8 | The APP 9 permitted basis for each use of a Medicare number or IHI | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O9 | Whether patient merges must be reversible after a clinical event, and for how long | Clinical Safety Officer | OPEN (source `04` open item 8) |
| O10 | Identity mechanism (self-hosted versus managed OIDC) gates the whole delivery | CTO + Security Lead | OPEN — blocks Gate 3 ([D-003](decisions/D-003-identity-model.md)) |

#### `docs/features/10-prescription-safety-gate/01-requirements.md` (§Open questions)

| # | Item | Owner role | Status |
|---|---|---|---|
| O1 | E-prescribing conformance: which register, which certified party, which sunset dates | CTO | REQUIRES LEGAL/REGULATORY VALIDATION |
| O2 | Schedule 8 and real-time prescription monitoring mandatory checks per jurisdiction | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| O3 | The duplicate-dispatch "configured period" for gate 9 | Clinical Safety Officer | OPEN |
| O4 | The reconciliation threshold (default 15 minutes) and the 24-hour escalation | Clinical Safety Officer | OPEN |
| O5 | Whether a pharmacist-initiated dispatch path is in pilot scope | Head of Product | OPEN |
| O6 | Identity of the signing key holder once D-003 is decided | CTO + Security Lead | OPEN — blocked by [D-003](decisions/D-003-identity-model.md) |

> Items O1 and O2 above are the repo-side restatement of legal-validation items L7 and L8 in §2. They
> are counted in this subsection as feature-doc rows and not re-counted against §2.

### 3.6 Deduplication notes

Nine source-side overlaps, one source-to-repo overlap, nine feature-spec restatements and two
repo-internal overlaps are recorded here. **Every row stays in its own table.** These notes exist so
a reviewer can see which rows were judged to restate another and disagree with that judgement.

The nine source-side overlaps. Each pair is the same open item recorded twice in the source set:

| # | Rows that are the same item | Why |
|---|---|---|
| 1 | `ADR-002` F1 and `05-tenant-isolation.md` O3 | Both ask for the pool mode and the proven reset behaviour before the pool-reuse test is evidence |
| 2 | `ADR-001` F3 and `07-audit-architecture.md` O6 | Both ask for the `audit_log` partition granularity |
| 3 | `ADR-007` F1 and `07-audit-architecture.md` O1 | Both ask for the audit retention period per jurisdiction |
| 4 | `ADR-007` F2 and `07-audit-architecture.md` O2 | Both ask for the Object Lock mode and duration |
| 5 | `ADR-006` F1 and `06-authentication-rbac.md` O1 | Both ask which OIDC provider, with its residency |
| 6 | `ADR-008` F3 and `14-retention-and-deletion.md` O7 | Both ask the retention period for a document or record class |
| 7 | `ADR-009` F1 and `11-tga-inbox-pipeline.md` O3 | Both ask for the golden set and its labelling owner |
| 8 | `ADR-009` F2 and `11-tga-inbox-pipeline.md` O1 | Both ask for the confidence thresholds |
| 9 | `ADR-003` F2 and `19-project-charter.md` O3 | Both ask for the residency position from an Australian legal adviser |

One cross-set duplicate:

| # | Rows that are the same item | Why |
|---|---|---|
| 10 | Source `24-definition-of-done.md` O1–O5 and repo [`definition-of-done.md`](definition-of-done.md) O1–O5 | The repo document reproduces the source's five items; every repo row has a source counterpart |

Feature-spec rows that restate a source or decision-record item. These are counted as feature rows in
§3.5 and are **not** removed from the feature table, because the feature spec owns its own list:

| # | Rows that are the same item | Why |
|---|---|---|
| 11a | [`01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md) item 2 and source `06-authentication-rbac.md` §6 | The same lockout-threshold reconciliation |
| 11b | [`01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md) item 9 and source `06` O2 | The same authenticator-class question |
| 11c | [`01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md) item 10 and source `05-tenant-isolation.md` O6 | The same cross-tenant-denial notification question |
| 11d | [`05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) O5 and source `04-database-erd.md` O5 | The same blind-index key custody question |
| 11e | [`05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) O6 and source `06` §11 O5 | The same `care_relationships` ownership question |
| 11f | [`05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) O9 and source `04` O8 | The same merge-reversibility question |
| 11g | [`05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) O10 and repo [`D-003`](decisions/D-003-identity-model.md) item 1 | The same identity decision |
| 11h | [`10-prescription-safety-gate/01-requirements.md`](../features/10-prescription-safety-gate/01-requirements.md) O1 and legal item L7 | The same e-prescribing-conformance question |
| 11i | [`10-prescription-safety-gate/01-requirements.md`](../features/10-prescription-safety-gate/01-requirements.md) O2 and legal item L8 | The same Schedule 8 and monitoring question |

Repo-internal near-duplicates that remain in their own tables:

| # | Rows that overlap | Why they stay separate |
|---|---|---|
| 12a | Repo `sdlc/README.md` O1, O2 and `D-003`/`D-004` open item 1 | `O1` and `O2` restate the decisions; the D-003/D-004 tables carry the option detail |
| 12b | Repo [`gates.md`](gates.md) O1–O3 and source `26-security-gates.md` O1–O3 | The repo table reproduces the source's rows and adds `O6`, which appears nowhere in the source |

Pairs deliberately **not** treated as duplicates, because the scope differs:

| Rows | Why they stay separate |
|---|---|
| `17-compliance-control-matrix.md` L1–L14 and `90-owner-brief.md` §10 L1–L14 | The same 14 questions, different owner wording. §2 consolidates them into one table of 14 rows; the two source tables are not listed separately in §3 |
| Source `12-data-classification.md` O1–O3 and `15-privacy-impact-assessment.md` O2, O6 | 12 characterises fields; 15 asks for the consent and APP 9 basis. Different questions |
| Source `13-data-residency.md` O1 and `16-vendor-register.md` O2 | Overlapping register rows with different owners and different scope |
| Source `01-system-architecture.md` O1 and `03-threat-model.md` O1 | The same device-boundary question, but the threat-model row is scoped to adding a device-grade risk process |
| ADR `F1`–`F5` registers generally | Distinct per ADR apart from the nine pairs above |

---

## 4. The rule

**An open item is closed only by a named person recording the answer in the document that owns it.**
It is never closed by silence, by a meeting, or by a status change in another system. The closure
record names the person, the date and the artefact.

**An item marked `REQUIRES LEGAL/REGULATORY VALIDATION` is never closed by an engineer's opinion.**
It closes when a named person with authority — a legal or regulatory adviser, a Privacy Officer on
advice, or the Practice Owner where the item is a commercial decision — records the advice in the
owning document. An engineering control that addresses the engineering half of the item does not close
the item; it changes the item's compensating-control statement only.

Three consequences follow, and they are not negotiable:

1. **No item is closed by implementing a control.** The control is evidence that we engineered
   carefully. It is not proof of legal compliance.
2. **A closure without a citation is invalid.** State the instrument, the contract clause, or the
   written advice, and where it is filed.
3. **An item that stays open past its gate is a residual risk, not a backlog entry.** It is accepted in
   writing by the owner named in the row, with a compensating control and an expiry, or it blocks the
   gate — see [`definition-of-done.md` §5](definition-of-done.md#5-exception-process) and
   [`gates.md`](gates.md).

Related rules this register depends on:

- [`docs/reference/build-contract.md` §10](build-contract.md#10-evidence-discipline) — evidence discipline: an
  artefact that does not link to the control it proves is not evidence.
- [`docs/reference/build-contract.md` §11](build-contract.md#11-change-control) — a change to a regulatory position
  needs CTO + legal/regulatory adviser.
- [`control-matrix.md`](control-matrix.md) — where a closure is recorded against the control row it
  affects.
- [`definition-of-done.md` §5](definition-of-done.md#5-exception-process) — **an exception without an
  expiry is invalid.**

## 5. Source-internal contradictions

These are not open questions in the usual sense. They are places where two documents in the source
contract state incompatible things, so **one of them cannot be implemented as written**. The source
cannot settle them, which means the implementer settles them — and an unrecorded settlement is how a
control quietly becomes whatever the first line of code happened to do.

Two of these are clinical safety parameters and are escalated accordingly.

| # | Contradiction | Documents | Position taken | Status |
|:---:|---|---|---|---|
| C1 | **How the one-live-approval-per-grain rule is enforced.** Doc 08 §4 defines a `UNIQUE` at the grain and says verbatim *"an exclusion constraint is deliberately not used"*; docs 04 §3.6, 20 §5, 23 §4 and Gate 2 all require a GiST exclusion on overlapping `ACTIVE` intervals. A unique-at-grain constraint is **structurally incompatible** with the supersede chain doc 08 itself defines | 08 §4 vs 04 §3.6, 20 §5, 23 §4, 26 Gate 2 | Partial **GiST exclusion** (`WHERE state = 'ACTIVE'`, `btree_gist`). Doc 08 §4 must be corrected | **Resolved — [D-006](decisions/D-006-approval-grain-and-validity-boundary.md)** |
| C2 | **Whether `valid_to` is inside the window.** Doc 08 §5 reads `valid_from <= d <= valid_to` (inclusive, "the whole of `valid_to`"); doc 04 §3.6 uses `tstzrange(..., '[)')` (exclusive). A **one-day difference in whether a prescription may be dispensed** | 08 §5 vs 04 §3.6 | Half-open `[valid_from, valid_to)` **as an interim fail-safe only** — refusing the final day is an inconvenience, dispensing outside an approval is a statutory breach | 🔴 **OPEN — Clinical Safety Officer.** Gate 4 re-run on any change |
| C3 | **The permission catalogue is not closed.** Doc 04 §3.3 says "20 permissions" and lists 19; 06 §9–§10 defines the same 19; but 20 §1–§5 and user stories name ~19 further codes (`tenant:read`, `clinic:manage`, `session:revoke`, `patient:merge`, `clinical_record:amend`, …) | 04 §3.3, 06 §9–§10 vs 20, 22 | No permission invented. RBAC seed content and endpoint permission values are blocked | OPEN — CTO. Blocks task T1-09 |
| C4 | **Account lockout threshold.** Doc 06 §6 = 10 failures in 15 minutes (progressive to 60); doc 20 §2 and US-04 = 5 | 06 §6 vs 20 §2, US-04 | Test parameterised; enforcement follows 06 until closed | OPEN — Security Lead |
| C5 | **Audit action naming.** Doc 07 §1 uses lowercase dotted actions (`patient.read`); docs 04, 20 and the user stories use `UPPER_SNAKE` (`PATIENT_READ`, `CLINICAL_NOTE_SIGNED`) | 07 §1 vs 04 §3.10, 20, 22 | Doc 07 treated as canonical; story labels carried as aliases. New actions must be registered in 07 before use | OPEN — CTO |
| C6 | **`result` vocabulary.** Doc 04 = `SUCCESS/DENIED/ERROR`; docs 07 and 21 = `SUCCESS/DENIED/FAILED/UNKNOWN` | 04 §3.11 vs 07, 21 §4 | Doc 07 superset adopted — `UNKNOWN` is required for the reconciliation outcome | OPEN — CTO |
| C7 | **Error envelope shape.** Doc 02 §7 is flat (`{error, request_id, code}`); doc 21 §7 and this repo's DoD §4 are nested (`{error:{code,message,request_id,details}}`) | 02 §7 vs 21 §7 | **Nested** (repo rank-2 convention, and Gate 4 checks against it) | Divergence recorded in [`definition-of-done.md`](definition-of-done.md) §4 |
| C8 | **Session storage.** Doc 06 §3 defines `sessions(...)`; doc 04 §3.11 defines `refresh_tokens(...)` with different columns | 06 §3 vs 04 §3.11 | Reconciled onto one table; the merged shape is open | OPEN — Security Lead |
| C9 | **Points accounting.** Sprint 1: doc 23 §3 workstreams sum to 92, doc 22 §4 sizes the same stories at 78. Sprint 2: 76 committed against an **assumed** 40-point velocity | 23 §3–§4 vs 22 §4 | Both figures recorded; the velocity is an assumption, not a measurement | OPEN — Delivery Lead |
| C10 | **Step-up operation count.** Gate 3, the PRD and US-09 name **five** high-risk operations; doc 06 §8 lists a **sixth** route family (break-glass / MFA reset) | 26 Gate 3, 20 §2 vs 06 §8 | Five gate-named operations implemented; the sixth presented as required | OPEN — Security Lead |
| C11 | **`clinics` is required but undefined.** Named by doc 23 §3 and doc 20 §1, tenant-scoped, but doc 04 (the schema contract) defines no columns for it and no module owns it | 23 §3, 20 §1 vs 04 | No columns invented | OPEN — CTO |
| C12 | **`patient_identifiers` divergence.** Doc 23 §3 and doc 20 §3 require the table; doc 04 §3.4 inlines `medicare_number`/`ihi` with blind indexes on `patients` and defines no such table | 23 §3, 20 §3 vs 04 §3.4 | Both carried; needs a decision record | OPEN — CTO |
| C13 | **`care_relationships` is required but undefined.** Read by the central policy layer in doc 06 §10 and needed by US-11, but absent from doc 23 §3 and from doc 04; doc 06's own open item 5 leaves the source of truth open | 06 §10, US-11 vs 04, 23 §3 | Treated as blocked rather than designed | OPEN — Security Lead. Blocks task T1-34 |
| C14 | **PHI in a URL, forbidden by the source's own rule.** Doc 20 §5 names `GET /tga-approvals/match?patient_id=…`, and the patient search route puts the term in the query string — both violate doc 02 §10 requirement 10 (no search terms or identifiers in URLs) | 20 §5 vs 02 §10 req 10 | Re-expressed as `POST` with a body | OPEN — Security Lead + Head of Product |
| C15 | **Webhook mount point.** Doc 10 §7 mounts provider callbacks at `/webhooks/:provider` (provider-scoped); doc 02 §11 rates `/pharmacy/webhooks/*` | 10 §7 vs 02 §11 | Module-scoped path used; prefix question settled by [D-005](decisions/D-005-route-path-convention.md) | OPEN — O5, Security Lead |
| C16 | **A Gate 2 check targets a Phase 2 table.** Gate 2's approval-grain check inspects `tga_approvals`, which Phase 1 does not create | 26 Gate 2 vs 23 §3–§4 | Recorded **N/A to the Phase 1 schema and deferred to Phase 2** with a named owner, rather than silently dropped | Resolved by deferral |
| C17 | **Classification-level count.** Several drafts (and an early instruction) said "six levels"; doc 12 §1 states and lists **seven** | 12 §1 vs the drafts | **Seven** adopted: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`, `HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET` | Resolved |
| C18 | **Sign-time vs dispatch-time approval check.** Doc 08 §5 asserts the check happens at signing; doc 09's open item 2 marks the sign-time position **REQUIRES LEGAL/REGULATORY VALIDATION** | 08 §5 vs 09 open item 2 | **Dispatch time is the enforcing control.** A sign-time check, if required, is additional | OPEN — Clinical Safety Officer |
| C19 | **Requirements attributed to the source that the source does not contain.** "Medicare Modulus-10 / Luhn validation", "minimum search query length 3", a DVA file number, and "biannual (January/July)" TGA reporting all appear in this repo's original feature drafts but **nowhere in the source contract** | repo drafts vs the source set | Marked **REQUIRES LEGAL/REGULATORY VALIDATION** or `OPEN`; none asserted as a source requirement | Resolved by correction |

**C1, C2 and C18 are clinical safety parameters.** They are not engineering judgement calls, and none of
them may be closed by an engineer's opinion.

## Open items and assumptions

This document is itself a register; its own open items are the items it lists. Two meta-items remain:

| # | Item | Owner role |
|---|---|---|
| O1 | Confirm the review cadence and the trigger that forces a re-read of the source set | Compliance Lead |
| O2 | Confirm an interim position and an owner for every validation item before Gate 7, per `26-security-gates.md` O3 | Compliance Lead |

## Sources

- `clinic-os-secure-by-design/90-owner-brief.md` §1, §10 — the two owner decisions and L1–L14
- `clinic-os-secure-by-design/17-compliance-control-matrix.md` §10 — the L1–L14 decision text and §10.1 residual risk
- `clinic-os-secure-by-design/00-README.md` — rule 6: "unknown is a status, not a gap to be papered over"
- `clinic-os-secure-by-design/00-build-prompt-traceability.md`
- The `## Open items and assumptions` section of `01`–`29` and `25-adr/ADR-001`–`ADR-011`
- [`docs/reference/build-contract.md`](build-contract.md), [`gates.md`](gates.md), [`definition-of-done.md`](definition-of-done.md)
- [`D-001`](decisions/D-001-python-fastapi-stack.md), [`D-002`](decisions/D-002-repo-layout.md), [`D-003`](decisions/D-003-identity-model.md), [`D-004`](decisions/D-004-deployment-target.md)
