---
doc_id: OZ-REF-TR
title: Source-to-repo traceability map and coverage gaps
owner: CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
source: ../../clinic-os-secure-by-design/00-README.md
---

# Traceability Map

Which source document lands where in this repo, which repo document draws on which source, and what
currently has **no** repo-side home. The source set is read-only and lives outside this repo at
`clinic-os-secure-by-design/`. Links into it are prose references, not repo-relative links, because
the path does not resolve from inside this repo — that is the defect this document exists to resolve
in the other direction.

> **Verified against the source directory.** `clinic-os-secure-by-design/` holds **44 source-contract
> documents**: `00-README.md`, `00-executive-summary.md`, `00-build-prompt-traceability.md`,
> `01`–`24` and `26`–`29` (28 documents — `25` is the ADR directory, not a document),
> `90-owner-brief.md`, and `25-adr/` with `README.md` plus `ADR-001`–`ADR-011`. Those 44 are what this
> map covers. *(The task brief quoted 46 files; the enumeration returns 44.)*
>
> **Re-verified 2026-10-05.** The same directory also contains a **`docs/` subtree of 154 markdown
> files** — `README.md` plus `features/`, `reference/` and `sdlc/` — a working copy of a repo
> documentation tree, including phase-view files that no longer exist in this repo. It is **not** part
> of the 44-document source contract and is excluded from this map. A recursive enumeration therefore
> returns **198** markdown files, not 44. The earlier claim that the directory contained "no other
> subdirectories" was wrong and is corrected here.

---

## 1. Where each source document lands

| Source doc | Repo document(s) that implement or reference it | Status |
|---|---|---|
| `00-README.md` | [`build-contract.md`](build-contract.md) §1, §10 (document-set rules, evidence discipline; cites it by name in Sources) · [`control-matrix.md`](control-matrix.md) §1.1, §1.3 | **Covered** |
| `00-executive-summary.md` | [`build-contract.md`](build-contract.md) §1 (the commercial and risk framing behind the phase set) | Partially covered — the two owner decisions and the commercial case have no repo-side owner document |
| `00-build-prompt-traceability.md` | [`traceability.md`](traceability.md) (this document) | **Covered by this file** — the repo's own source-to-doc map |
| `01-system-architecture.md` | [`build-contract.md`](build-contract.md) §2, §7 · [`D-001`](decisions/D-001-python-fastapi-stack.md) §Source contract reference · [`D-002`](decisions/D-002-repo-layout.md) · [`D-003`](decisions/D-003-identity-model.md) | **Covered** |
| `02-security-architecture.md` | [`build-contract.md`](build-contract.md) §6 (the twelve controls and hard prohibitions; cites it in Sources) · [`gates.md`](gates.md) §Artefact naming · [`control-matrix.md`](control-matrix.md) §1.3, §4, §9 | **Covered** |
| `03-threat-model.md` | The per-feature STRIDE models — `04-threat-model.md` in each of the 17 feature folders, including [`01-tenancy-and-clinics`](../features/01-tenancy-and-clinics/04-threat-model.md), [`05-patients`](../features/05-patients/04-threat-model.md), [`06-clinical-records`](../features/06-clinical-records/04-threat-model.md), [`08-tga-approvals`](../features/08-tga-approvals/04-threat-model.md) and [`10-prescription-safety-gate`](../features/10-prescription-safety-gate/04-threat-model.md) | **Covered** by the per-feature threat models; the consolidated TH-001…TH-nnn register has no home (§3) |
| `04-database-erd.md` | [`docs/features/05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) (cites) · [`docs/features/06-clinical-records/01-requirements.md`](../features/06-clinical-records/01-requirements.md) (cites) · [`control-matrix.md`](control-matrix.md) §3, §6, §9 | **Covered** |
| `05-tenant-isolation.md` | [`docs/features/01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md) (cites) · [`docs/features/01-tenancy-and-clinics/06-test-plan.md`](../features/01-tenancy-and-clinics/06-test-plan.md) (the isolation assertions) · [`control-matrix.md`](control-matrix.md) §3, §11 | **Covered** |
| `06-authentication-rbac.md` | [`docs/features/01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md) (cites) · [`D-003`](decisions/D-003-identity-model.md) | **Covered** |
| `07-audit-architecture.md` | [`docs/features/01-tenancy-and-clinics/05-data-and-audit.md`](../features/01-tenancy-and-clinics/05-data-and-audit.md) · [`control-matrix.md`](control-matrix.md) §5, §11 | **Covered** |
| `08-tga-approval-model.md` | [`docs/features/08-tga-approvals/01-requirements.md`](../features/08-tga-approvals/01-requirements.md) (cites) · [`control-matrix.md`](control-matrix.md) §7 | **Covered** |
| `09-prescription-safety-gate.md` | [`features/10-prescription-safety-gate/01-requirements.md`](../features/10-prescription-safety-gate/01-requirements.md) (the INV-2 specification) · [`features/10-prescription-safety-gate/06-test-plan.md`](../features/10-prescription-safety-gate/06-test-plan.md) · [`features/08-tga-approvals/01-requirements.md`](../features/08-tga-approvals/01-requirements.md) (cites) · [`control-matrix.md`](control-matrix.md) §7, §11 (INV-2) | **Covered** |
| `10-integration-boundaries.md` | [`features/13-integration-boundaries/01-requirements.md`](../features/13-integration-boundaries/01-requirements.md) and its six sibling documents — Parchment, TGA and provider boundaries, webhook security, SSRF, failure modes · [`control-matrix.md`](control-matrix.md) §8 | **Covered** — this row was a gap when the map was drafted; the feature folder now exists (see §3) |
| `11-tga-inbox-pipeline.md` | [`docs/features/08-tga-approvals/01-requirements.md`](../features/08-tga-approvals/01-requirements.md) (cites) · [`control-matrix.md`](control-matrix.md) §7 | **Covered** |
| `12-data-classification.md` | [`docs/features/01-tenancy-and-clinics/05-data-and-audit.md`](../features/01-tenancy-and-clinics/05-data-and-audit.md) · [`docs/features/05-patients/05-data-and-audit.md`](../features/05-patients/05-data-and-audit.md) · [`docs/features/06-clinical-records/05-data-and-audit.md`](../features/06-clinical-records/05-data-and-audit.md) · [`docs/features/08-tga-approvals/05-data-and-audit.md`](../features/08-tga-approvals/05-data-and-audit.md) · [`docs/features/05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) and [`docs/features/06-clinical-records/01-requirements.md`](../features/06-clinical-records/01-requirements.md) (cite) | **Covered** by the per-feature field maps in `05-data-and-audit.md` (one per feature folder, 17); a consolidated classification reference has no home (§3) |
| `13-data-residency.md` | [`control-matrix.md`](control-matrix.md) §6, §11 (INV-6) · [D-004](decisions/D-004-deployment-target.md) | Partially covered — no repo-side residency register; see §3 |
| `14-retention-and-deletion.md` | [`docs/features/05-patients/05-data-and-audit.md`](../features/05-patients/05-data-and-audit.md) · [`docs/features/06-clinical-records/05-data-and-audit.md`](../features/06-clinical-records/05-data-and-audit.md) · [`docs/features/08-tga-approvals/05-data-and-audit.md`](../features/08-tga-approvals/05-data-and-audit.md) · [`docs/features/06-clinical-records/01-requirements.md`](../features/06-clinical-records/01-requirements.md) (cites) · [`control-matrix.md`](control-matrix.md) §6 | **Covered** |
| `15-privacy-impact-assessment.md` | [`gates.md`](gates.md) §Gate 7 (names the PIA as gate evidence) · [`open-questions.md`](open-questions.md) §3.2 · [`control-matrix.md`](control-matrix.md) §10 | Partially covered — the PIA itself has no repo-side home; see §3 |
| `16-vendor-register.md` | [`gates.md`](gates.md) §Gate 5, §Gate 7 (names the vendor register as gate evidence) · [`control-matrix.md`](control-matrix.md) §8 · [`open-questions.md`](open-questions.md) §3.2 | Partially covered — the register itself has no repo-side home; see §3 |
| `17-compliance-control-matrix.md` | [`control-matrix.md`](control-matrix.md) (the whole document reproduces its pattern and consolidates its rows) · [`build-contract.md`](build-contract.md) §10 | **Covered** |
| `18-incident-response.md` | [`gates.md`](gates.md) §Gate 7 (names the incident runbook) · [`control-matrix.md`](control-matrix.md) §10 · [`open-questions.md`](open-questions.md) §3.2 | Partially covered — no repo-side runbook; see §3 |
| `19-project-charter.md` | [`build-contract.md`](build-contract.md) §3 (phase, gate and milestone map) | Partially covered — see §3 |
| `20-product-requirements.md` | [`docs/features/01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md), [`docs/features/05-patients/01-requirements.md`](../features/05-patients/01-requirements.md), [`docs/features/06-clinical-records/01-requirements.md`](../features/06-clinical-records/01-requirements.md), [`docs/features/08-tga-approvals/01-requirements.md`](../features/08-tga-approvals/01-requirements.md) (all cite it) | **Covered** |
| `21-technical-design.md` | [`build-contract.md`](build-contract.md) §2, §7, Sources · [`definition-of-done.md`](definition-of-done.md) §4 (endpoint declaration standard) · [`D-001`](decisions/D-001-python-fastapi-stack.md), [`D-002`](decisions/D-002-repo-layout.md), [`D-004`](decisions/D-004-deployment-target.md) | **Covered** |
| `22-user-stories.md` | [`docs/features/05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) (cites) | Partially covered — no repo-side story set; see §3 |
| `23-sprint-plan.md` | [`build-contract.md`](build-contract.md) §3, Sources · [`gates.md`](gates.md) Sources | **Covered** as the phase chart; the sprint-level plan has no repo-side home |
| `24-definition-of-done.md` | [`definition-of-done.md`](definition-of-done.md) (the six-part test reproduced) · [`build-contract.md`](build-contract.md) §8, Sources | **Covered** |
| `25-adr/README.md` | [`docs/reference/decisions/README.md`](decisions/README.md) (format, status vocabulary, change control) · [`control-matrix.md`](control-matrix.md) §3, §5, §8 | Partially covered — the repo's decision index is a divergence register, not a counterpart |
| `25-adr/ADR-001-postgresql.md` | [`control-matrix.md`](control-matrix.md) §3 (RLS, schema), §9 (migration safety) · [`D-002`](decisions/D-002-repo-layout.md) | Partially covered — no repo-side ADR; the control lands in the register |
| `25-adr/ADR-002-postgresql-rls-tenant-isolation.md` | [`control-matrix.md`](control-matrix.md) §3, §11 (INV-1) · [`docs/features/01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md) | Partially covered — no repo-side ADR |
| `25-adr/ADR-003-aws-sydney-deployment.md` | [`D-004`](decisions/D-004-deployment-target.md) (names it as a source) · [`control-matrix.md`](control-matrix.md) §6, §11 (INV-6) | Partially covered — blocked by D-004 |
| `25-adr/ADR-004-docker.md` | [`D-004`](decisions/D-004-deployment-target.md) (names it as a source) · [`control-matrix.md`](control-matrix.md) §9 | Partially covered — blocked by D-004 |
| `25-adr/ADR-005-modular-monolith.md` | [`D-002`](decisions/D-002-repo-layout.md) (the layout that implements it) · [`control-matrix.md`](control-matrix.md) §9 (module-boundary lint) | **Covered** as a control; no repo-side ADR |
| `25-adr/ADR-006-authentication-architecture.md` | [`D-003`](decisions/D-003-identity-model.md) (the divergence it creates) · [`control-matrix.md`](control-matrix.md) §4 | **Covered** as a divergence decision |
| `25-adr/ADR-007-audit-architecture.md` | [`control-matrix.md`](control-matrix.md) §5, §11 (INV-4) · [`docs/features/01-tenancy-and-clinics/05-data-and-audit.md`](../features/01-tenancy-and-clinics/05-data-and-audit.md) | **Covered** |
| `25-adr/ADR-008-s3-document-storage.md` | [`control-matrix.md`](control-matrix.md) §6 (documents stored privately, signed URLs) | Partially covered — the object store diverges under D-004 |
| `25-adr/ADR-009-tga-ingestion-architecture.md` | [`control-matrix.md`](control-matrix.md) §7 · [`docs/features/08-tga-approvals/01-requirements.md`](../features/08-tga-approvals/01-requirements.md) | **Covered** |
| `25-adr/ADR-010-parchment-integration.md` | [`control-matrix.md`](control-matrix.md) §8 · [`D-004`](decisions/D-004-deployment-target.md) · [`features/13-integration-boundaries/`](../features/13-integration-boundaries/01-requirements.md) | Partially covered — the boundary controls land in the feature folder; the adapter itself is Phase 3 work |
| `25-adr/ADR-011-terraform-adoption.md` | [`D-004`](decisions/D-004-deployment-target.md) (names it as a source) · [`control-matrix.md`](control-matrix.md) §9 (reproducible infrastructure) | Partially covered — blocked by D-004 |
| `26-security-gates.md` | [`gates.md`](gates.md) (Gates 1–7 reproduced) · [`build-contract.md`](build-contract.md) §3, Sources · [`control-matrix.md`](control-matrix.md) §9 | **Covered** |
| `27-security-testing.md` | [`definition-of-done.md`](definition-of-done.md) §6 (names the test catalogue) · [`gates.md`](gates.md) Sources · [`control-matrix.md`](control-matrix.md) §12 | **Covered** |
| `28-aws-network-and-deployment.md` | [`D-004`](decisions/D-004-deployment-target.md) · [`control-matrix.md`](control-matrix.md) §9 | Partially covered — blocked by D-004; see §3 |
| `29-operations-and-observability.md` | [`control-matrix.md`](control-matrix.md) §9 | Partially covered — no repo-side observability spec; see §3 |
| `90-owner-brief.md` | [`open-questions.md`](open-questions.md) §1, §2 (L1–L14 and the two owner decisions) · [`build-contract.md`](build-contract.md) §3 | **Covered** |

### 1.1 The dead links this document resolves

**Eleven of the 17 feature folders** carry a `source:` frontmatter block listing
`clinic-os-secure-by-design/NN-*.md` paths (`00`, `04`, `08`–`16`). Those paths do **not** exist inside
this repo — `docs/` has no `clinic-os-secure-by-design/` directory — so every one of those entries is a
dead link from the repo root, and by the convention recorded in [`build-contract.md`](build-contract.md)
§1 they are deliberately prose references rather than repo-relative links. §1 is the resolution: those
source documents land in the repo documents named in column 2.

**Six folders carry no `source:` block at all** — `01-tenancy-and-clinics`, `02-authentication`,
`03-users-and-roles`, `05-patients`, `06-clinical-records` and `07-documents`. Their source lineage is
mapped from content in §2.3, not declared in frontmatter.

*An earlier revision of this section described a `traceability_docs:` frontmatter block on four
phase-era `spec.md` files. Those files were superseded by the feature folders and no longer exist
(§3.1), and no document under `docs/features/` carries a `traceability_docs:` key today. The four
folders those specs became are listed here because their lineage is still worth tracing:*

| Feature folder (successor to one of the four phase-era specs) | Source paths the superseded spec cited | Resolves to, in this repo |
|---|---|---|
| [`01-tenancy-and-clinics`](../features/01-tenancy-and-clinics/01-requirements.md) — *no `source:` block today* | `05-tenant-isolation.md`, `06-authentication-rbac.md`, `20-product-requirements.md`, `21-technical-design.md` | §3 and §4 of [`control-matrix.md`](control-matrix.md); [`D-003`](decisions/D-003-identity-model.md); §2 of this document |
| [`05-patients`](../features/05-patients/01-requirements.md) — *no `source:` block today* | `04-database-erd.md`, `12-data-classification.md`, `20-product-requirements.md`, `22-user-stories.md` | §3 and §6 of [`control-matrix.md`](control-matrix.md); [`05-patients/05-data-and-audit.md`](../features/05-patients/05-data-and-audit.md); §3 of this document (no story set) |
| [`06-clinical-records`](../features/06-clinical-records/01-requirements.md) — *no `source:` block today* | `04-database-erd.md`, `12-data-classification.md`, `14-retention-and-deletion.md`, `20-product-requirements.md`, `21-technical-design.md` | §6 of [`control-matrix.md`](control-matrix.md); [`06-clinical-records/05-data-and-audit.md`](../features/06-clinical-records/05-data-and-audit.md) |
| [`08-tga-approvals`](../features/08-tga-approvals/01-requirements.md) | `08-tga-approval-model.md`, `09-prescription-safety-gate.md`, `11-tga-inbox-pipeline.md`, `20-product-requirements.md`, `21-technical-design.md` | §7 and §11 of [`control-matrix.md`](control-matrix.md); [`08-tga-approvals/05-data-and-audit.md`](../features/08-tga-approvals/05-data-and-audit.md) |

Every other document in the feature tree is mapped from its content in §2.3 rather than from
frontmatter, so the map is complete.

---

## 2. Reverse map

Repo document → the source documents it draws on. `—` means the document is repo-original and draws
on no single source document.

### 2.1 The spine and the phase directories

| Repo document | Draws on |
|---|---|
| [`build-contract.md`](build-contract.md) | `00-README.md`, `02-security-architecture.md` (the twelve controls; request pipeline; hard prohibitions), `21-technical-design.md` (module map; tenant isolation; API standard), `23-sprint-plan.md` (phase boundaries, exit criteria), `24-definition-of-done.md` (the six-part test), `26-security-gates.md` (Gates 1–7), `01-system-architecture.md` (stack, invariants), `06-authentication-rbac.md` (identity divergence, via D-003), `28-aws-network-and-deployment.md` (deployment divergence, via D-004) |
| [`docs/tasks/00-phase-0-foundation.md`](../tasks/00-phase-0-foundation.md) | **Delivered as a task list.** Draws on `23-sprint-plan.md` §2 (pre-sprint work), `21-technical-design.md` §6–§7, `27-security-testing.md` §4, `ADR-004`, `ADR-011` |
| [`docs/tasks/01-phase-1-foundations.md`](../tasks/01-phase-1-foundations.md) | **Delivered as a task list.** Draws on `04-database-erd.md`, `05-tenant-isolation.md`, `06-authentication-rbac.md`, `07-audit-architecture.md`, `12-data-classification.md` |
| [`docs/tasks/02-phase-2-tga-approval-engine.md`](../tasks/02-phase-2-tga-approval-engine.md) | **Delivered as a task list.** Draws on `08-tga-approval-model.md`, `11-tga-inbox-pipeline.md`, `20-product-requirements.md` §5–§6, `22-user-stories.md` US-15 to US-20 |
| [`docs/tasks/03-phase-3-eprescribing.md`](../tasks/03-phase-3-eprescribing.md) | **Delivered as a task list.** Draws on `09-prescription-safety-gate.md`, `10-integration-boundaries.md`, `20-product-requirements.md` §7–§8 |
| [`docs/tasks/04-phase-4-pilot-go-live.md`](../tasks/04-phase-4-pilot-go-live.md) | **Delivered as a task list.** Draws on `23-sprint-plan.md` §11, `26-security-gates.md` §7–§8, `15-privacy-impact-assessment.md`, `16-vendor-register.md`, `18-incident-response.md`, `28-aws-network-and-deployment.md`, `29-operations-and-observability.md` |
| [`docs/reference/decisions/README.md`](decisions/README.md) | `25-adr/README.md` (the format and the status vocabulary), `00-README.md` (change control), `21-technical-design.md` §6–§8 |

### 2.2 Reference documents

| Repo document | Draws on |
|---|---|
| [`control-matrix.md`](control-matrix.md) | `17-compliance-control-matrix.md` (the pattern and the master rows), `02-security-architecture.md` §1, §10 and Control table, `21-technical-design.md` §13, `23-sprint-plan.md` §12, `24-definition-of-done.md` §7, `26-security-gates.md` §10, `27-security-testing.md` §11, and the control summaries and control tables of `01`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`, `12`, `13`, `14`, `15`, `16`, `18`, `19`, `20`, `22`, `28`, `29`, plus the `25-adr/` set |
| [`open-questions.md`](open-questions.md) | `90-owner-brief.md` §1, §10 (L1–L14 and the two owner decisions), `17-compliance-control-matrix.md` §10, §10.1, the `## Open items and assumptions` section of `00-build-prompt-traceability.md`, `01`–`29` and `25-adr/README.md` and `ADR-001`–`ADR-011`, and the open items of this repo's own spine, gates, DoD and decision records |
| [`traceability.md`](traceability.md) | `00-README.md` (the document index this map is built from), `00-build-prompt-traceability.md` (the precedent for a source-to-document map), `25-adr/README.md` (the ADR index) — plus a direct enumeration of the source directory |
| [`gates.md`](gates.md) | `26-security-gates.md` (Gates 1–7, conditional-pass rules, sign-off template), `23-sprint-plan.md` (gate timing at phase boundaries), `27-security-testing.md` (the named tests and the artefact naming map), `02-security-architecture.md` §10 (frontend requirements) |
| [`definition-of-done.md`](definition-of-done.md) | `24-definition-of-done.md` (the six-part test, exception process, Definition of Ready), `21-technical-design.md` §7 (API design standard and endpoint declarations), `27-security-testing.md` (the security test catalogue) |
| [`decisions/D-001-python-fastapi-stack.md`](decisions/D-001-python-fastapi-stack.md) | `01-system-architecture.md` §8, §9 (technology choices), `21-technical-design.md` §7, §8, `02-security-architecture.md` §1 control 4 |
| [`decisions/D-002-repo-layout.md`](decisions/D-002-repo-layout.md) | `23-sprint-plan.md` §2 (repository architecture), `21-technical-design.md` §8 (module to deployment mapping), `01-system-architecture.md` §5 (module map) |
| [`decisions/D-003-identity-model.md`](decisions/D-003-identity-model.md) | `01-system-architecture.md` §8, §9, `02-security-architecture.md` §1 control 1, §5.1, §10, `26-security-gates.md` §4 (Gate 3), `06-authentication-rbac.md` |
| [`decisions/D-004-deployment-target.md`](decisions/D-004-deployment-target.md) | `21-technical-design.md` §6 (infrastructure), `28-aws-network-and-deployment.md`, `ADR-003`, `ADR-004`, `ADR-011`, `90-owner-brief.md` §1 decision 2 |

### 2.3 Feature documents

**Partial, and stated as such.** The feature tree holds **17 folders (`00`–`16`) × 7 documents = 119
files**. This section maps the 21 documents whose source lineage was verified in the 2026-10-04 pass.
The remaining documents inherit the sources declared by their own folder's `01-requirements.md`.
Eleven folders declare sources in a `source:` block (`00`, `04`, `08`–`16`); the other six declare
none, so their lineage is mapped here from their content.

| Repo document | Draws on |
|---|---|
| [`features/01-tenancy-and-clinics/01-requirements.md`](../features/01-tenancy-and-clinics/01-requirements.md) | `05-tenant-isolation.md`, `06-authentication-rbac.md`, `20-product-requirements.md` §1–§2, `21-technical-design.md` §2, §7 |
| [`features/01-tenancy-and-clinics/04-threat-model.md`](../features/01-tenancy-and-clinics/04-threat-model.md) | `03-threat-model.md` Module 1 (Authentication) and Module 7 (Multi-tenancy), `06-authentication-rbac.md` §6–§7, `05-tenant-isolation.md` §7 |
| [`features/01-tenancy-and-clinics/05-data-and-audit.md`](../features/01-tenancy-and-clinics/05-data-and-audit.md) | `12-data-classification.md` (identity and session fields), `07-audit-architecture.md` §1 (mandatory events), §2 (envelope), `06-authentication-rbac.md` §14 (never logged) |
| [`features/01-tenancy-and-clinics/06-test-plan.md`](../features/01-tenancy-and-clinics/06-test-plan.md) | `05-tenant-isolation.md` §8 (the isolation test list), `24-definition-of-done.md` (the six-part test), `26-security-gates.md` §3–§4 (Gates 2 and 3), `27-security-testing.md` §2.1–§2.2 |
| [`features/05-patients/01-requirements.md`](../features/05-patients/01-requirements.md) | `04-database-erd.md` §3.4 (`patients`), `12-data-classification.md` (patient fields), `20-product-requirements.md` §3, `22-user-stories.md` US-10, US-11, US-14 |
| [`features/05-patients/04-threat-model.md`](../features/05-patients/04-threat-model.md) | `03-threat-model.md` Module 2 (Patient records), `04-database-erd.md` §3.4, §3.13 (`consent_records`), `12-data-classification.md` §3 |
| [`features/05-patients/05-data-and-audit.md`](../features/05-patients/05-data-and-audit.md) | `12-data-classification.md` (patient field map), `14-retention-and-deletion.md` §2 (retention schedule; the 7-year and age-25 rules), `07-audit-architecture.md` |
| [`features/05-patients/06-test-plan.md`](../features/05-patients/06-test-plan.md) | `24-definition-of-done.md`, `04-database-erd.md` §3.4, `05-tenant-isolation.md` §8, `27-security-testing.md` §2.5 (API) |
| [`features/06-clinical-records/01-requirements.md`](../features/06-clinical-records/01-requirements.md) | `04-database-erd.md` §3.5 (`clinical_records`, `clinical_record_versions`), `12-data-classification.md` §3 (clinical note fields), `14-retention-and-deletion.md`, `20-product-requirements.md` §4, `21-technical-design.md` §3 |
| [`features/06-clinical-records/04-threat-model.md`](../features/06-clinical-records/04-threat-model.md) | `03-threat-model.md` Module 2 (Patient records), `04-database-erd.md` §6 (soft delete versus hard delete), §9 (append-only enforcement) |
| [`features/06-clinical-records/05-data-and-audit.md`](../features/06-clinical-records/05-data-and-audit.md) | `12-data-classification.md` (SOAP fields), `14-retention-and-deletion.md` §2, §3.6 (legal hold), `07-audit-architecture.md` §7 (what must never be in an audit payload) |
| [`features/06-clinical-records/06-test-plan.md`](../features/06-clinical-records/06-test-plan.md) | `24-definition-of-done.md`, `04-database-erd.md` §3.5, §9, `08-tga-approval-model.md` §8 (acceptance criteria and tests), `06-authentication-rbac.md` §8 (step-up) |
| [`features/08-tga-approvals/01-requirements.md`](../features/08-tga-approvals/01-requirements.md) | `08-tga-approval-model.md` §1 (the grain), §2–§3 (states, transitions), `09-prescription-safety-gate.md` §2 (the gate pipeline), `11-tga-inbox-pipeline.md` §4 (threshold policy), `20-product-requirements.md` §5–§6, `21-technical-design.md` §9 |
| [`features/08-tga-approvals/04-threat-model.md`](../features/08-tga-approvals/04-threat-model.md) | `03-threat-model.md` Module 3 (Prescription dispatch) and Module 4 (TGA inbox), `08-tga-approval-model.md`, `09-prescription-safety-gate.md` §5 (acceptance scenarios) |
| [`features/08-tga-approvals/05-data-and-audit.md`](../features/08-tga-approvals/05-data-and-audit.md) | `12-data-classification.md` §3 (TGA approval and document fields; inbox metadata and OCR extraction), `14-retention-and-deletion.md` §2, `07-audit-architecture.md` §1 |
| [`features/08-tga-approvals/06-test-plan.md`](../features/08-tga-approvals/06-test-plan.md) | `08-tga-approval-model.md` §1, §8, `09-prescription-safety-gate.md` §5, §11 (safety-gate test matrix), `11-tga-inbox-pipeline.md` §4, `24-definition-of-done.md` |

Five further documents were mapped in the same verification pass as
[`open-questions.md`](open-questions.md) §3.5:

| Repo document | Draws on |
|---|---|
| [`features/README.md`](../features/README.md) | `20-product-requirements.md`, `22-user-stories.md`, `24-definition-of-done.md`, [`build-contract.md`](build-contract.md) (the delivery layer it indexes against) |
| [`features/10-prescription-safety-gate/01-requirements.md`](../features/10-prescription-safety-gate/01-requirements.md) | `09-prescription-safety-gate.md` §1–§11, `08-tga-approval-model.md` (the grain), `10-integration-boundaries.md` §1, §5, §7, `21-technical-design.md` §9, `26-security-gates.md` §5, §7 |
| [`features/10-prescription-safety-gate/04-threat-model.md`](../features/10-prescription-safety-gate/04-threat-model.md) | `03-threat-model.md` Module 3 (Prescription dispatch), `09-prescription-safety-gate.md` §5, §6, `10-integration-boundaries.md` |
| [`features/10-prescription-safety-gate/05-data-and-audit.md`](../features/10-prescription-safety-gate/05-data-and-audit.md) | `12-data-classification.md` §3 (prescription fields), `07-audit-architecture.md` §1 (mandatory events), `09-prescription-safety-gate.md` §9 (audit obligations at each step) |
| [`features/10-prescription-safety-gate/06-test-plan.md`](../features/10-prescription-safety-gate/06-test-plan.md) | `09-prescription-safety-gate.md` §5, §11 (safety-gate test matrix), `27-security-testing.md` §2.3, `24-definition-of-done.md`, `26-security-gates.md` §5, §7 |

### 2.4 The six invariants and where each is proven

The invariants are defined in [`build-contract.md`](build-contract.md) §5, carried as controls in
[`control-matrix.md`](control-matrix.md) §11, and indexed by test in §12 of that register. Earlier
revisions of this map named INV-1, INV-2, INV-4, INV-5 and INV-6 and **never INV-3**; the row below
closes that gap.

| Invariant | Proven by | Repo home |
|---|---|---|
| **INV-1** Tenant isolation holds even when the application forgets a filter | `backend/tests/isolation/test_rls_holds_without_app_filter.py` | [`features/01-tenancy-and-clinics`](../features/01-tenancy-and-clinics/01-requirements.md); [`control-matrix.md`](control-matrix.md) §3, §11 |
| **INV-2** No prescription is dispatched without an `ACTIVE` TGA approval at the approval grain | `backend/tests/security/test_dispatch_blocks_without_active_approval.py` plus the negative dispatch matrix | [`features/10-prescription-safety-gate`](../features/10-prescription-safety-gate/01-requirements.md); [`control-matrix.md`](control-matrix.md) §7, §11 |
| **INV-3** Enforcement is backend-only; the frontend hides and warns, never decides | `backend/tests/security/test_authz_recomputes_server_side.py` | [`features/03-users-and-roles/06-test-plan.md`](../features/03-users-and-roles/06-test-plan.md) (test S1); [`gates.md`](gates.md) artefact-naming map; [`control-matrix.md`](control-matrix.md) §4, §11, §12 |
| **INV-4** Audit is append-only; the application role cannot `UPDATE` or `DELETE` it | GRANT inspection test | [`features/04-audit-log`](../features/04-audit-log/01-requirements.md); [`control-matrix.md`](control-matrix.md) §5, §11 |
| **INV-5** No PHI appears in logs, metrics, traces or error responses | `backend/tests/security/test_no_phi_in_log_payload.py` plus redaction unit tests | [`features/16-operations-and-observability`](../features/16-operations-and-observability/01-requirements.md); [`control-matrix.md`](control-matrix.md) §11 |
| **INV-6** Data stays in Australia; no production data leaves the approved region | Residency policy check plus a vendor register entry per flow | [`features/00-foundations`](../features/00-foundations/01-requirements.md); [`control-matrix.md`](control-matrix.md) §6, §11 — `OPEN`, blocked by [D-004](decisions/D-004-deployment-target.md) |

---

## 3. Coverage gaps

Source material with **no** repo-side document today, with a proposed home. Rows marked **RESOLVED**
have since acquired one and are kept for history. No content is invented for any gap here; the table
maps the gap to the document that should own it.

| Source material | What it contains | Proposed repo home | In scope for this phase set? |
|---|---|---|---|
| `10-integration-boundaries.md` — **RESOLVED** | Parchment, TGA and Tyro as untrusted external boundaries; the cross-cutting integration controls; webhook security; SSRF protections; failure modes; integration tests | [`features/13-integration-boundaries/`](../features/13-integration-boundaries/01-requirements.md) now owns the boundary controls; [`docs/tasks/03-phase-3-eprescribing.md`](../tasks/03-phase-3-eprescribing.md) owns the adapter work | **Yes** — Phase 3 owns Parchment; Phase 2 owns the TGA boundary. The gap this row recorded is closed |
| `13-data-residency.md` §3 | The data residency and cross-border data flow register (DR-01 to DR-15) and the five-condition test results | A repo-side residency register. Nearest proposed home: a Phase 0 or Phase 1 reference document under [`docs/reference/`](.), owned by the Privacy Officer | **Yes** — INV-6 depends on it, and D-004 blocks the answer. Not started |
| `15-privacy-impact-assessment.md` | The PIA, its APP-by-APP assessment, its risks and its sign-off path | A Phase 4 document under [`docs/tasks/04-phase-4-pilot-go-live.md`](../tasks/04-phase-4-pilot-go-live.md), named in the Gate 7 evidence list. `gates.md` Gate 7 already names the PIA as evidence without a home | **Yes** — Gate 7 requires it |
| `16-vendor-register.md` | Every third party that touches data, its tier, its residency position, its evidence status, and the onboarding gate | A Phase 0 or Phase 2 reference document under [`docs/reference/`](.), owned by the Compliance Lead. `gates.md` Gate 5 and Gate 7 name the vendor register as evidence without a home | **Yes** — Gates 5 and 7 require it |
| `18-incident-response.md` | Severity levels, eight runbooks, the notifiable-breach assessment, evidence custody, tabletops | A Phase 4 document under [`docs/tasks/04-phase-4-pilot-go-live.md`](../tasks/04-phase-4-pilot-go-live.md), owned by the Security Lead. `gates.md` Gate 7 requires the incident response runbook to name people, not roles | **Yes** — Gate 7 requires it |
| `19-project-charter.md` | Problem, scope, stakeholders, decision rights, funding, milestones, success criteria, stop triggers | [`build-contract.md`](build-contract.md) §3 covers the phase and milestone map. The charter's governance, funding and stop-or-re-scope triggers have no home; proposed home is a repo-side charter or a §3 expansion | **Partially.** The delivery phases are in scope; governance and funding are not engineering deliverables |
| `28-aws-network-and-deployment.md` | VPC, subnets, security groups, WAF, IAM design, container design, environment separation, Terraform strategy, backup and recovery | [`docs/tasks/04-phase-4-pilot-go-live.md`](../tasks/04-phase-4-pilot-go-live.md) — and the whole question is **blocked by [D-004](decisions/D-004-deployment-target.md)**. Under Option B most of it is replaced, not reproduced | **Deferred** — cannot be scoped until D-004 closes |
| `29-operations-and-observability.md` | The five log categories, the structured logging standard, the redaction pipeline, the metric and alert catalogues, tracing, dashboards, secrets management, backup and DR | [`docs/tasks/04-phase-4-pilot-go-live.md`](../tasks/04-phase-4-pilot-go-live.md) — the operations section, with the logging and redaction standard needed earlier, in Phase 1 | **Yes** — the redaction pipeline and the sentinel tests are INV-5 evidence and land in Phase 1 |
| `25-adr/README.md` | The ADR index, the format, the status vocabulary, the change-control rule and the security-implication one-liner per decision | [`docs/reference/decisions/README.md`](decisions/README.md) — already the repo's ADR index, but scoped to divergences only. Proposed home for the source set is an index mapping | **Partially.** The repo index holds four divergence records, not eleven source decisions |
| `25-adr/ADR-001`–`ADR-011` | Eleven decisions: PostgreSQL, RLS, AWS Sydney, Docker, modular monolith, authentication, audit, S3 document storage, TGA ingestion, Parchment, Terraform | [`docs/reference/decisions/`](decisions/) holds [`D-001`](decisions/D-001-python-fastapi-stack.md)–[`D-004`](decisions/D-004-deployment-target.md), which record only the **divergences** from the source contract. The source's own decisions have no repo-side record; a repo-side mapping from each source ADR to the register row it is normative for is the proposed home. §1 traces all twelve ADR files individually | **Partially.** Every source ADR is normative for a control already carried in [`control-matrix.md`](control-matrix.md). A repo-side re-adoption is only needed where the repo diverges |
| `00-executive-summary.md` | The one-page commercial and risk case, and the two decisions being asked for | [`open-questions.md`](open-questions.md) §1, §2.1 carries the two decisions. The commercial case has no engineering home and does not need one | **No** — commercial, not an engineering deliverable |
| `22-user-stories.md` | 30 persona-mapped stories with security and audit acceptance criteria | Each feature folder carries its own [`02-user-stories.md`](../features/) (17 of them) and one already names US-17. There is no single source-to-story map; proposed home is the relevant feature folder's story document | **Partially.** The stories are upstream of the feature requirements; the acceptance criteria they carry must not be lost |
| `23-sprint-plan.md` §3–§11 | Sprint-level scope, the dependency table between sprints, the estimation approach, ceremonies, the M4 prerequisites | [`build-contract.md`](build-contract.md) §3 carries the phase map. The sprint-level plan and the M4 prerequisites list have no dedicated home; proposed home is a repo-side sprint-plan reference document, or the M4 prerequisites section of [`docs/tasks/04-phase-4-pilot-go-live.md`](../tasks/04-phase-4-pilot-go-live.md) | **Yes** — the phase task lists are the intended owner |
| `03-threat-model.md` §12 | The consolidated threat register (TH-001 to TH-nnn) and the forbidden-failure-mode table | The per-feature [`04-threat-model.md`](../features/) documents (17 folders) cover their own STRIDE rows. No consolidated register exists; proposed home is a repo-side threat register indexed to the feature models | **Partially.** Feature-level coverage exists; the cross-module residual-risk view does not |
| `12-data-classification.md` §3, §4 | The full field-level classification map and the "may this field appear in" decision table | The per-feature [`05-data-and-audit.md`](../features/) documents (17 folders) carry their own field maps. A consolidated classification reference has no home | **Partially.** Per-feature coverage exists |
| `09-prescription-safety-gate.md` §3, §6, §7 | The approval-lookup decision table, the prescription state machine and the idempotency design | [`docs/features/08-tga-approvals/01-requirements.md`](../features/08-tga-approvals/01-requirements.md) and its [`test-plan.md`](../features/08-tga-approvals/06-test-plan.md) cover the grain and the gate. The dispatch state machine and idempotency design belong to the Phase 3 spec | **Yes** — Phase 3 |

### 3.1 The structural gap — RESOLVED, then superseded

**Status: resolved, then superseded.** When this document was drafted, the five phase directories were
empty and the links to their four files each were dead. Those twenty files were written, and the phase
set was then **superseded by design**: the build unit is now the numbered feature folder under
[`docs/features/`](../features/), and only the ordered work breakdown survives from the phase view.

```
docs/tasks/00-phase-0-foundation.md           234 lines   (was sdlc/00-phase-0-foundation/tasks.md)
docs/tasks/01-phase-1-foundations.md          479 lines
docs/tasks/02-phase-2-tga-approval-engine.md  384 lines
docs/tasks/03-phase-3-eprescribing.md         337 lines
docs/tasks/04-phase-4-pilot-go-live.md        340 lines
```

The fifteen `phase.md` / `spec.md` / `plan.md` files (~6,700 lines) were deleted **from this repo**
because the feature folders cover the same ground at a better granularity — see
[`build-contract.md`](build-contract.md) §3 for the phase-to-feature mapping. (A copy of that
superseded phase tree survives outside this repo under `clinic-os-secure-by-design/docs/sdlc/`, and is
not part of the source contract; see the note at the top of this document.) The residual gaps in §1 and
§3 above are still open.

### 3.2 Gaps inside the feature layer

Recorded at the same verification timestamp as [`open-questions.md`](open-questions.md) §3.5.

| Gap | Detail |
|---|---|
| `03-clinical-records/spec.md`, `04-tga-approval-engine/spec.md` — **RESOLVED** | These were the phase-era names for [`06-clinical-records`](../features/06-clinical-records/01-requirements.md) and [`08-tga-approvals`](../features/08-tga-approvals/01-requirements.md). Every one of the 17 feature folders now carries an `## Open items` section in its `01-requirements.md`, so a spec without an owner-facing place to record what it does not know is no longer possible |
| `docs/features/README.md` | States the division of labour between the feature layer and the phase layer — but carries no `source:` block, so it traces no source document |
| `05-prescription-safety-gate/` — **RESOLVED** | The folder is now [`10-prescription-safety-gate`](../features/10-prescription-safety-gate/01-requirements.md), and it is placed: [`features/README.md`](../features/README.md) assigns it to Phase 3 with Gates 4 and 6, and [`build-contract.md`](build-contract.md) §5 defines INV-2 with its named test |

**The feature layer outgrew this map.** After this section was written the `docs/features/` tree grew
from 16 files to 17 folders × 7 documents (**119 files**). The reverse map in §2.3 covers only the 21
documents listed there; the rest inherit the sources declared by their folder's `01-requirements.md`
and must be re-mapped before this document is relied on as a complete trace.

---

## 4. The rule

**If a source document has no repo-side home, that is a coverage gap to record, not a silence to
keep.** Three consequences:

1. **A source doc is not covered because it was read.** It is covered when a repo document references
   it, implements it, or records why it is out of scope. §1 records the status of all 44 source files.
2. **A repo link that does not resolve is a defect.** The `source:` blocks in eleven feature folders
   name `clinic-os-secure-by-design/NN-*.md` paths, and this repo has no
   `clinic-os-secure-by-design/` directory, so those entries never resolve as links. That is
   deliberate — they are prose references, per [`build-contract.md`](build-contract.md) §1 — and is
   recorded in §1.1. A link that is *meant* to resolve and does not is a defect to raise against the
   document carrying it.
3. **A gap with no proposed home is an open item.** Every row in §3 names the document that should own
   the gap. If a row cannot name one, it belongs in [`open-questions.md`](open-questions.md) with a
   named owner instead.

Related rules this map depends on:

- [`build-contract.md` §1](build-contract.md#1-what-is-authoritative) — the resolution order between
  this repo, the decision records and the source contract.
- [`open-questions.md`](open-questions.md) §4 — an open item is closed only by a named person recording
  the answer in the document that owns it.
- [`control-matrix.md`](control-matrix.md) §1.1 — an artefact that does not link to the control it
  proves is not evidence.

## Open items and assumptions

| # | Item | Owner role |
|---|---|---|
| O1 | ~~Write the five phase directories' `phase.md`, `spec.md`, `plan.md` and `tasks.md`~~ **RESOLVED** — all twenty files written; the four-files-per-phase contract in `build-contract.md` §4 is satisfied | Delivery Lead |
| O2 | Decide whether the eleven feature folders' `source:` frontmatter blocks — and the six folders with none — are the intended long-term form (prose source paths, mapped by §2.3), or whether every folder should declare its sources | Frontend Lead + CTO |
| O3 | Confirm the proposed home for each §3 coverage gap before the relevant phase is approved | CTO |
| O4 | Decide whether the source ADR set needs a repo-side counterpart, or whether the four divergence records plus [`control-matrix.md`](control-matrix.md) are sufficient | CTO + Security Lead |
| O5 | Confirm whether `19-project-charter.md`, `00-executive-summary.md` and `22-user-stories.md` are in scope for this repo at all | Head of Product |

## Sources

- The enumerated contents of `clinic-os-secure-by-design/` — **44 source-contract documents**: `00-*` × 3, `01`–`24` and `26`–`29` (28), `90-owner-brief.md`, `25-adr/` × 12. The directory's separate `docs/` working copy is excluded (see the note at the top)
- `clinic-os-secure-by-design/00-README.md` — the document index, the reading paths and the rules the set obeys
- `clinic-os-secure-by-design/00-build-prompt-traceability.md` — the precedent for a source-to-document map
- `clinic-os-secure-by-design/25-adr/README.md` — the ADR index and format
- [`build-contract.md`](build-contract.md) — the phase map, module map and document map
- [`control-matrix.md`](control-matrix.md), [`open-questions.md`](open-questions.md), [`gates.md`](gates.md), [`definition-of-done.md`](definition-of-done.md), [`decisions/`](decisions/README.md)
