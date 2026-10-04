---
doc_id: FEAT-FOUND-02
title: Foundations, user stories
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
next_review: 2026-11-04
related: 23-sprint-plan, 26-security-gates, 02-security-architecture
source:
  - clinic-os-secure-by-design/23-sprint-plan.md §2, §8
  - clinic-os-secure-by-design/22-user-stories.md
  - clinic-os-secure-by-design/26-security-gates.md §1, §2
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A). Foundations serves the delivery
roles, not patients, so no story here touches patient data — and none may, because no clinic module
exists yet.

## CTO (delivery owner)

**US-1** As the CTO, I want the repository to build in CI on an empty baseline so that every later
feature starts from a known-green contract.
- Acceptance: a green pipeline run exists, referenced by run id, before Phase 1 starts.
- S: the pipeline requires no production secret to run; test configuration is synthetic only.
- A: `ci.pipeline.completed` with commit, workflow, stage list and result.

**US-2** As the CTO, I want configuration to refuse startup when a required key is missing or holds a
placeholder value so that a misconfigured deployment fails loudly instead of running permissively.
- Acceptance: startup exits non-zero and names the key; the process serves no request.
- S: there is no development escape hatch that downgrades the check to a warning.
- A: `config.validation_failed` with the key **name** — never the value.

## Head of Platform (platform owner)

**US-3** As the Head of Platform, I want three hardened images built from one repository so that the
frontend, API and worker scale and fail independently.
- Acceptance: three images build; each runs as non-root with an explicit `USER` and a health check.
- S: no secret in an image layer, build cache or build argument.
- A: `container.build` with image reference, digest and scan result.

**US-4** As the Head of Platform, I want base images and dependencies pinned so that a rebuild is
reproducible and a scan finding is attributable to a known artefact.
- Acceptance: runtime base reference is a digest; `uv.lock` and `bun.lock` are committed; no floating
  tag in a release image.
- S: a floating tag is a build failure, not a warning.
- A: none beyond the build event — this is a build-time property, not a runtime action.

**US-5** As the Head of Platform, I want the database role to own no table and hold no `BYPASSRLS` so
that the ORM cannot escape tenant isolation.
- Acceptance: a grant-inspection test returns non-owner and `rolbypassrls = false`.
- S: the same inspection proves `REVOKE DELETE, TRUNCATE` on audit and event tables.
- A: `db.grants_inspected` with the observed privilege set.

## Security Lead (gate owner)

**US-6** As the Security Lead, I want the security stages to run on every pull request and block merge
on failure so that a finding cannot be merged "to be fixed later".
- Acceptance: the eleven stages run in the fixed order; branch protection requires them.
- S: removing or reordering a security stage requires Security Lead plus Head of Platform, recorded.
- A: `ci.security_stage.failed` with stage, rule or signature and the blocked commit.

**US-7** As the Security Lead, I want a deliberately vulnerable fixture to be blocked by each stage so
that a green pipeline means the control works, not that the stage is inert.
- Acceptance: planted secret, planted vulnerable dependency and planted type error each block their
  own stage, each with a recorded failed-run id; fixtures reverted before merge.
- S: an inert stage is treated as a failed gate check, not a passing one.
- A: `ci.fixture_blocked` with fixture id, stage and run id.

**US-8** As the Security Lead, I want no secret in git, in an image or in a committed `.env` so that a
leaked credential path does not exist.
- Acceptance: `git ls-files` returns no `.env`; a full-history secret scan is retained as evidence.
- S: a finding in **history** is a leaked-secret incident — rotate first, then remove.
- A: `secret.scan.completed` with scope (working tree or full history) and finding count.

**US-9** As the Security Lead, I want every committed secret value rotated and the incident runbook
followed so that a value that was public is no longer usable.
- Acceptance: rotation record names each secret, its owner and its timestamp; the old value fails.
- S: `SECRET_KEY=changethis` is treated as permitting JWT forgery, not as a lint warning.
- A: `secret.rotated` with secret **name**, owner and reason — never the value.

## Developer

**US-10** As a developer, I want the same checks locally and in CI so that a red pipeline is
predictable rather than surprising.
- Acceptance: `uv run ruff check .`, `uv run mypy app`, `uv run pytest` and the pre-commit hooks are
  the same controls CI enforces.
- S: pre-commit includes secret scanning, so a secret is caught before it is committed.
- A: none — local developer action, not an audited system event.

## Compliance auditor

**US-11** As an auditor, I want pipeline runs and scan reports retained and referenced by run id so
that a control claim can be checked against an artefact.
- Acceptance: each control in 07-definition-of-done.md links to a run id or a report; read-only access.
- S: evidence retention covers the gate cycle; gap in retention is a finding, not an omission.
- A: `evidence.read` with actor, artefact and purpose.

## Privacy Officer

**US-12** As the Privacy Officer, I want to know exactly which secret values were exposed in git so
that I can assess whether the exposure is notifiable.
- Acceptance: the exposure inventory lists secret names, first-commit dates and rotation status.
- S: the assessment is a legal judgement and is marked **REQUIRES LEGAL/REGULATORY VALIDATION**.
- A: `secret.exposure_assessed` with scope and the decision owner.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Role names are the source's roles; confirm they match the RBAC seed before build | CTO | OPEN |
| Is the notifiable-breach assessment for the committed secrets in scope for this feature or handled as an incident? | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Named human for each gate role (the source names roles, not people) | Practice Owner | OPEN |
