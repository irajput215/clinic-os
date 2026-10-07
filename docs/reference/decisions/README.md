---
doc_id: OZ-DEC-INDEX
title: Decision records index
owner: CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
---

# Decision Records

A decision record exists here for every point where this repo **deliberately diverges** from the
normative source contract in `clinic-os-secure-by-design/` (external, read-only).

The rule this file set obeys: the source contract is normative for **controls, gates, invariants and
regulatory obligations**; these records are normative for **how those are implemented here**. A divergence
is never applied silently. If you find code that diverges from the source contract without a record here,
that is a defect.

| ID | Decision | Status | Blocks a gate? |
|---|---|---|---|
| [D-001](D-001-python-fastapi-stack.md) | Backend is Python 3.14 + FastAPI, not Node + TypeScript | **Accepted** | No — translation only |
| [D-002](D-002-repo-layout.md) | Layout is `backend/` + `frontend/` + `packages/`, not `apps/*` (amended 2026-10-06) | **Accepted** | No — translation only |
| [D-003](D-003-identity-model.md) | Identity is self-hosted password auth, not a managed OIDC provider | **OPEN — requires a decision** | **Yes — Gate 3** |
| [D-004](D-004-deployment-target.md) | Deployment target is unresolved between compose and the source's AWS shape | **OPEN — requires a decision** | **Yes — Gate 6** |
| [D-005](D-005-route-path-convention.md) | Routes carry the `/api/v1` prefix; provider webhooks are the one exception | **Accepted** | No |
| [D-006](D-006-approval-grain-and-validity-boundary.md) | Approval grain enforced by a partial GiST exclusion constraint; `valid_to` boundary is half-open **as an interim fail-safe** | **Accepted** for the mechanism · 🔴 **OPEN** for the boundary | **Gate 2** (mechanism) · **Gate 4 re-run** (boundary) |

Two records resolve contradictions **inside** the source contract rather than divergences from it. They
are recorded here because a contradiction the source cannot settle is the implementer's decision whether
or not anyone writes it down — and D-006 is a clinical safety parameter, which is the worst place to let
a decision go unrecorded.

## Status vocabulary

| Status | Meaning |
|---|---|
| **Proposed** | Written down, not yet agreed |
| **Accepted** | Agreed; the repo builds to it |
| **OPEN — requires a decision** | A blocking unknown. Work that depends on it must not start |
| **Superseded by D-nnn** | Replaced; kept for history |
| **Rejected** | Considered and declined, with the reason recorded |

## When to write one

Write a decision record when any of the following is true:

- A technology, library or hosting choice in the source contract is being met a different way here.
- A control in the source contract cannot be implemented as written and a compensating control is used.
- A tenant-isolation, audit or safety-gate design changes. *(These additionally require a Gate 2 or
  Gate 4 re-run — see [change control](../build-contract.md#11-change-control).)*
- A previously `OPEN` decision is closed.

## Template

```markdown
# D-nnn: <title>

- Status: Proposed | Accepted | OPEN — requires a decision | Superseded by D-nnn | Rejected
- Date: YYYY-MM-DD
- Owner: <role>
- Source contract reference: <which source doc this diverges from>

## Context
What the source contract says, and what this repo actually has.

## Decision
What we are doing instead, stated so it can be built against.

## Consequences
What becomes easier, what becomes harder, and what evidence replaces the source's evidence artefact.

## Effect on the gates
Which gate checks this changes, and whether any gate is blocked.

## Open items
What must be resolved, by whom.
```
