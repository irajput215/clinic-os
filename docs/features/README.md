---
doc_id: OZ-FEAT-INDEX
title: Feature set index
owner: CTO (interim: Ishu Rajput)
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
---

# Feature set

Every feature is a self-contained folder of **seven short documents**, in build order. Numbering is the
dependency order: a feature may depend on any lower number, never on a higher one.

| # | Feature | Owns | Gates | Depends on |
|:---:|---|---|:---:|---|
| 00 | [foundations](00-foundations/01-requirements.md) | repo layout, Docker, environments, CI security pipeline | 1 | — |
| 01 | [tenancy-and-clinics](01-tenancy-and-clinics/01-requirements.md) | `tenants`, `clinics`, tenant settings | 1, 2 | 00 |
| 02 | [authentication](02-authentication/01-requirements.md) | identity, sessions, MFA, step-up | 3 | 00, 01 |
| 03 | [users-and-roles](03-users-and-roles/01-requirements.md) | users, roles, permissions, break-glass | 3 | 02 |
| 04 | [audit-log](04-audit-log/01-requirements.md) | append-only `audit_log`, envelope, immutable export | 2 | 01 |
| 05 | [patients](05-patients/01-requirements.md) | patients, identifiers, consent, duplicate detection | 2, 4 | 01, 03 |
| 06 | [clinical-records](06-clinical-records/01-requirements.md) | versioned immutable notes and addenda | 2, 4 | 05 |
| 07 | [documents](07-documents/01-requirements.md) | upload, scan state, presigned URLs | 2, 4 | 05 |
| 08 | [tga-approvals](08-tga-approvals/01-requirements.md) | approval register at the grain | 4, 5 | 05 |
| 09 | [tga-inbox](09-tga-inbox/01-requirements.md) | email ingestion, extraction, human verification | 5 | 08 |
| 10 | [prescription-safety-gate](10-prescription-safety-gate/01-requirements.md) | **INV-2** — the dispatch gate | 4 | 08 |
| 11 | [prescribing](11-prescribing/01-requirements.md) | prescription workflow, signing, dispatch queue | 4, 5 | 10 |
| 12 | [pharmacy-dispatch](12-pharmacy-dispatch/01-requirements.md) | dispatch receipt, webhooks, confirmation | 5 | 11 |
| 13 | [integration-boundaries](13-integration-boundaries/01-requirements.md) | Parchment, TGA, provider contracts, SSRF | 5 | 11 |
| 14 | [reports-and-exports](14-reports-and-exports/01-requirements.md) | periodic reporting, DSAR, bulk export | 4 | 04, 08 |
| 15 | [admin-and-config](15-admin-and-config/01-requirements.md) | feature flags, retention jobs, break-glass | 4 | 03 |
| 16 | [operations-and-observability](16-operations-and-observability/01-requirements.md) | logs, metrics, alerts, incident readiness | 6 | all |

## The seven documents

| File | Answers | Read it to |
|---|---|---|
| `01-requirements.md` | What must this do, and how do we know it works? | Scope R1…Rn with testable acceptance |
| `02-user-stories.md` | Who needs it and why? | Stories grouped by role, each with S: and A: criteria |
| `03-design.md` | How is it built? | Tables, constraints, RLS, endpoints, request path, failure behaviour |
| `04-threat-model.md` | What can go wrong? | STRIDE with residual score and named owner |
| `05-data-and-audit.md` | How is data handled and what is recorded? | Field classification, audit events, retention |
| `06-test-plan.md` | How do we prove it? | F / S / A test tables with exact pytest commands |
| `07-definition-of-done.md` | When is it finished, and who signs? | Six-part checklist, gate governance, blocking open items |

## The audit standard every document follows

A regulated clinical platform must **prove** its controls. Every claim carries a three-part chain:

```
SOURCE ──────────────> SCORE ──────────────────> EVIDENCE
Why the control exists  Likelihood × Impact        The executable proof
```

1. **Source** — cite the upstream document and section, or the instrument by name.
   Never introduce a constraint from nowhere.
2. **Score** — every threat carries inherent risk, the control, residual risk as
   `Likelihood × Impact` with a band (`Low ≤4`, `Medium 5–9`, `High 10–16`, `Critical ≥17`), and a
   named human role as owner — never "the dev team".
3. **Evidence** — an executable artefact: a named pytest path, a
   `information_schema.role_table_grants` extract, a gate sign-off. A test name without its command is
   not evidence.

### Non-negotiable rules

- **Append-only by grant, not by convention.** The application role gets `SELECT, INSERT` and never
  `UPDATE`, `DELETE` or `TRUNCATE` on audit and event tables. Proven by a grant-inspection test.
- **Fail closed.** Any error resolving tenant or authorisation denies. A missing tenant setting matches
  nothing, never everything (`NULLIF(current_setting('app.tenant_id', true), '')`).
- **`404`, not `403`, across a tenant boundary.** Returning `403` confirms existence.
- **Denied and failed attempts are audited** with the same fidelity as successes.
- **No self-approval.** The person who delivered the work never signs its gate.
- **`REQUIRES LEGAL/REGULATORY VALIDATION`** on anything depending on a regulator's view, a contract
  term we have not seen, or a fact we do not have. Never guess, never claim compliance.

## Format

Folder: `NN-<kebab-name>/`. Every file carries **document-governance frontmatter** so the set can be
indexed, reviewed on a cycle, and mapped to its gates and its sources:

```yaml
---
doc_id: OZ-FEAT-<NN>-<DOC>
title: "<Module> — <document type>"
owner: <role>
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-<NN>
phase: <owning phase directory>
gate: [<gate numbers this feature must evidence>]
source:
  - clinic-os-secure-by-design/<doc>.md      # external, never rendered as a link
repo_docs:
  - 01-requirements.md                        # sibling links inside this folder
---
```

Keep files short — roughly 50–150 lines. If a document needs more, it is probably two documents.

## Source of truth

`clinic-os-secure-by-design/` — external, read-only, normative for controls, gates, invariants and
regulatory obligations. Where the source names technology this repo does not use, the control is retained
and the implementation is re-expressed against Python 3.14 / FastAPI / SQLModel / Alembic / Pydantic;
those translations are recorded in `../reference/decisions/`.
