---
doc_id: OZ-DOCS-INDEX
title: ozbrands documentation index
owner: CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
---

# ozbrands Documentation

This is the entry point for the ozbrands (ClinicOS) document set. It answers one question for every part
of the platform: **how must this be built so that it is secure, auditable and defensible from day one, not
retrofitted later?**

The normative build contract lives outside this repository, in `clinic-os-secure-by-design/`. This
repository's documents are the **implementation contract** for that source: same controls, same gates,
same invariants, expressed against the stack this codebase actually uses.

> **Engineering instruction, not legal advice.** Every regulatory statement here is a pointer to the cited
> instrument, not a legal conclusion. Items that depend on a regulator's view, a contract term we have not
> seen, or a fact we do not have are marked **REQUIRES LEGAL/REGULATORY VALIDATION** and carry a named
> owner.

---

## The layers

```
docs/
├── features/      → the build unit: 17 numbered folders, seven documents each
├── tasks/         → the ordered work breakdown: 186 tasks, one file per delivery phase
├── reference/     → the shared contract: build contract, gates, definition of done,
│                     control matrix, open questions, traceability, decision records,
│                     the business flow
└── progress.md    → what is actually built today, and what this set now gets wrong
```

| Layer | Entry point | Answers |
|---|---|---|
| **Status** | [`progress.md`](progress.md) | What is built and verified, and where this set is now wrong |
| **Business flow** | [`reference/business-flow.md`](reference/business-flow.md) | Who does what, from a clinic signing up to a pharmacy dispensing |
| **Delivery** | [`reference/build-contract.md`](reference/build-contract.md) | Invariants, controls, stack and the verified baseline |
| **Requirements** | [`features/README.md`](features/README.md) | What must each feature do, for whom, and how is it proven? |
| **Work breakdown** | [`tasks/`](tasks/) | In what order, with what dependencies, and blocked by what? |
| **Shared contract** | [`reference/build-contract.md`](reference/build-contract.md), [`reference/gates.md`](reference/gates.md) | What must be true before work may proceed? |

**Which wins on a conflict:** the *feature* document is normative for requirements, invariants,
classification and audit events. The *phase* document is normative for delivery order, sequencing and gate
evidence. The *reference* layer is normative for gates and the Definition of Done. A conflict between
layers is a defect to raise, not a judgement call to make silently.

---

## Start here, depending on who you are

| You are | Read first | Then |
|---|---|---|
| **Asking what is done** | [`progress.md`](progress.md) | its §4, where this set has fallen out of date |
| **Approving the build** | [`reference/build-contract.md` §3](reference/build-contract.md) — the phase/gate map | [`reference/gates.md`](reference/gates.md), then [`reference/open-questions.md`](reference/open-questions.md) |
| **Implementing a feature** | [`features/README.md`](features/README.md) | that feature's seven documents, then [`tasks/`](tasks/) |
| **Picking up the next task** | [`tasks/`](tasks/) | that phase's task list, and the task's `Blocked by:` |
| **Building a feature** | the feature's `01-requirements.md` | `02-user-stories.md` → `03-design.md` → `04-threat-model.md` → `05-data-and-audit.md` → `06-test-plan.md` → `07-definition-of-done.md` |
| **Reviewing a pull request** | [`reference/definition-of-done.md`](reference/definition-of-done.md) | the six-part checklist, plus the endpoint declaration standard |
| **Security or compliance review** | [`reference/control-matrix.md`](reference/control-matrix.md) | [`reference/gates.md`](reference/gates.md), [`reference/open-questions.md`](reference/open-questions.md) |
| **Auditing completeness** | [`reference/traceability.md`](reference/traceability.md) | the coverage-gap table at the end of it |

---

## Current status

**Everything in this set is `DRAFT — for review`, and most of it is not yet built.** [`progress.md`](progress.md)
records what actually exists, what is verified, and where this set has fallen out of date.

The ClinicOS domain does not exist in code: the backend is a FastAPI template plus the first tenancy
slice, and serves no domain endpoint. Phases 1–4 are greenfield.
[`reference/build-contract.md` §12](reference/build-contract.md) holds the baseline as verified on
2026-10-04; `progress.md` §4 lists what has changed since.

### Two open decisions block gates

| Decision | Blocks | Status |
|---|---|---|
| [**D-003**](reference/decisions/D-003-identity-model.md) — identity: managed OIDC (source contract) vs self-hosted password auth (this repo) | **Gate 3**, and Gate 1's threat model | 🔴 OPEN |
| [**D-004**](reference/decisions/D-004-deployment-target.md) — deployment: compose on an Australian host vs the source's ECS/RDS/S3/SQS shape | **Gate 6**, **Gate 7**, and Gate 1's environment-separation check | 🔴 OPEN on paper; settled in practice by the FastAPI Cloud + Neon deployment, which needs its own record |

Work that does not depend on these may proceed: tenancy, schema, RLS, audit envelope, patient register,
CI security pipeline. Work that does depend on them is marked `Blocked by:` in each phase's `tasks.md`.

### Security findings

1. ~~**The root `.env` is tracked in git** and holds `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD` and
   `POSTGRES_PASSWORD`, all at the template default `changethis`. `SECRET_KEY=changethis` signs JWTs.~~
   **CLOSED 2026-10-05 (#11):** `.env` is untracked, ignored and replaced by `.env.example`. The values
   themselves remain in git history, so rotation is still outstanding.
2. **CI has no security scanning** — no SAST, SCA, container or secret scanning across all 15 workflows.
   Still open, and Dependabot alerts are disabled on the repository.

Both were Phase 0 exit tasks. The first is done; the second is not.

---

## The rules this whole set obeys

1. **Deny by default.** `DENY → EXPLICITLY AUTHORISE → AUDIT → VALIDATE → EXECUTE`. Never
   `ACCEPT → PROCESS → TRY TO SECURE LATER`.
2. **The backend is the only security boundary.** The frontend hides, disables and warns. It never
   enforces.
3. **Tenant identity is resolved, never supplied.** It comes from the session and the resource — never
   from a request body, header or query parameter.
4. **Every sensitive field has a declared classification, and the classification drives the control.**
5. **Audit is append-only and outlives the application.**
6. **Unknown is a status, not a gap to paper over.** Where we do not know, we write
   `REQUIRES LEGAL/REGULATORY VALIDATION` or `OPEN` with a named owner. We do not invent a requirement and
   we do not claim compliance.
7. **No premature architecture.** Modular monolith, one API, one worker, one frontend, one PostgreSQL
   database, one private document store. Earn complexity: name the force that requires it.

These are the source contract's rules, unchanged and untranslated — they are not stack-dependent.

---

## Evidence discipline

Every substantive row in this set carries:

```text
Requirement      what must be true
Source           the primary instrument or the internal decision
Control          the engineering or operational control
Implementation   where it lives in the build
Evidence         what an auditor or a customer's security team would be shown
Owner            the single named accountable role
Status           implemented / in progress / planned / open
Last reviewed    date
```

**An artefact that does not link to the control it proves is not evidence.** A test name without its
output does not satisfy this. Where an item is not implemented, the status says so — that honesty is the
point of the set.
