---
doc_id: OZ-FEAT-16-THREAT
title: "Operations and observability — STRIDE threat model"
owner: Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-16
phase: 04-phase-4-pilot-go-live
gate: [6, 7]
source:
  - clinic-os-secure-by-design/29-operations-and-observability.md
  - clinic-os-secure-by-design/18-incident-response.md
  - clinic-os-secure-by-design/12-data-classification.md §1
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Threat model & residual risk register

## Risk-scoring method

`Risk = Likelihood (1–5) × Impact (1–5)`. Bands: **Low ≤ 4**, **Medium 5–9**, **High 10–16**, **Critical ≥ 17**. Residual is scored after the control, with a named human role as owner, never "the dev team". A Critical residual blocks release outright (`26 §7`; `gates.md`).

## STRIDE assessment and residual risk

| ID | STRIDE | Threat and attack path | Inherent | Control / mitigation | Residual (L×I) | Owner | Source |
|---|---|---|---|---|---|---|---|
| **T-16.1** | Information disclosure | A careless logger serialises a prescription, note body or full request body into application or error telemetry | High (4×4=16) | Typed fields only, classification-driven redaction before the sink write, no bypass on error paths; the sentinel test proves the value never lands (`06`) | **Low (2×2=4)** | Security Lead | `29 §2.2, §3`; `12 §1` |
| **T-16.2** | Information disclosure | Metrics or traces become a side channel: a patient or raw actor identifier in a label, or a trace capturing a request body, re-identifies a record | High (3×4=12) | Bounded labels, no patient or raw actor identifier, raw `tenant_id` label excluded from cross-tenant dashboards, sampling without bodies | **Low (2×2=4)** | Engineering Lead | `29 §4, §6`; `21 §10` |
| **T-16.3** | Repudiation | An alert that never fires — disabled, unrouted, ownerless, runbook-less or mis-thresholded — so a breach surfaces only when a clinician reports it | High (3×4=12) | Five-part alert definition (threshold, severity, route, runbook, owner); runbook-anchor test and firing tests in CI (`F6`, `S7`, `A1`) | **Medium (2×3=6)** | Security Lead | `29 §5`; `18 §3` |
| **T-16.4** | Repudiation | A runbook names a role rather than a person, so out of hours no individual is accountable and response stalls | Medium (3×3=9) | Gate 7 requires runbooks naming **people, not roles** with a backup, and a named on-call person for the first two weeks | **Low (2×2=4)** | Head of Platform | `18 §5`; `26 §8`; `23 §11` |
| **T-16.5** | Elevation of privilege | Over-privileged monitoring credentials: standing production access, broad log read or secret read lets an operator read health information or mint a credential | High (4×4=16) | No standing production access; just-in-time, time-boxed, reason-required, audited elevation; least-privilege task roles; quarterly access review | **Low (1×4=4)** | Security Lead | `29 §8.2, §9`; `02 §6` rule 6 |
| **T-16.6** | Tampering | Log or audit tampering to hide an intrusion: delete or edit an audit or security record to remove the trace | Critical (3×5=15) | Append-only by grant (`INSERT, SELECT` only), immutable export with Object Lock, separate stores, hash chain, non-owner application role | **Low (1×4=4)** | Security Lead | `29 §1`; `07 §3, §10`; `04 §9` |
| **T-16.7** | Tampering | A silent catch or default-allow branch swallows a failure, so the error is neither logged nor audited and the operation appears to succeed | High (4×3=12) | No bare `except`/`pass`; `ruff` `S110`/`BLE001` in the lint stage; a failure produces a distinguishable log and metric; fail-closed error contract (`S9`) | **Low (2×2=4)** | Engineering Lead | `02 §8` A10; `definition-of-done.md` §1 Part 4 |
| **T-16.8** | Information disclosure | A secret committed to a branch, tag, fixture, doc example, Dockerfile, image layer or build log is harvested from the repository | Critical (3×5=15) | Secret scanning pre-commit and in CI blocks the build; no-secret-in-image test; a suspected exposure opens `R3` with rotation and a blast-radius review (`S10`) | **Low (2×2=4)** | Security Lead | `29 §8.3`; `02 §6` rules 1, 3 |
| **T-16.9** | Information disclosure | A clinic-role log query returns another tenant's events, or a shared dashboard shows raw tenant content | High (3×4=12) | Tenant-scoped application and audit queries, no cross-tenant log view for a clinic role, dashboards carry no patient identifiers, cross-tenant access returns `404` (`S6`) | **Low (1×4=4)** | Security Lead | `29 §1, §7`; `21 §10` |
| **T-16.10** | Spoofing / tampering | Log injection: newline or control characters in a user-supplied value forge a log line or a metric label, defeating later analysis | Medium (3×3=9) | Typed fields only, no free-text concatenation, allow-listed message templates, envelope validator (`F1`, `F2`) | **Low (2×2=4)** | Engineering Lead | `29 §2` |
| **T-16.11** | Denial of service | Alert flood hides the real signal: a noisy threshold buries the audit-write or cross-tenant page, or a route is silenced without a decision | Medium (3×3=9) | One threshold, severity, route, runbook and owner per alert; enablement gate; alert tests in CI; no silencing without a recorded decision | **Low (2×2=4)** | Security Lead | `29 §5`; `18 §3` |

## Assumptions

- Severity response targets are internal recommendations until validated against any legal clock (`18 §2`).
- The pilot holds real patient data; synthetic data only in non-production.
- Sink, tracing and error-monitor products are undecided while [`D-004`](../../reference/decisions/D-004-deployment-target.md) is open, so the region pin for telemetry is not yet provable.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Severity and runbook anchor for the six `21 §10` page conditions, so T-16.3 can be closed | Security Lead | OPEN |
| Repo-side runbook naming people, not roles, so T-16.4 can be closed | Head of Platform | OPEN |
| Offshore-sink and SIEM position | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Per-jurisdiction log retention and breach-notification window | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Committed root `.env` with default secrets — a live T-16.8 finding | Security Lead | OPEN — Phase 0 exit task |
