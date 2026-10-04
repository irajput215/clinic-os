---
doc_id: OZ-FEAT-14-STORY
title: "Reports and exports — user stories and acceptance criteria"
owner: Compliance Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-14
phase: 02-phase-2-tga-approval-engine
gate: [4]
source:
  - clinic-os-secure-by-design/22-user-stories.md US-28
  - clinic-os-secure-by-design/08-tga-approval-model.md §6
  - clinic-os-secure-by-design/14-retention-and-deletion.md §1, §4
  - clinic-os-secure-by-design/06-authentication-rbac.md §9
  - Privacy Act 1988 (Cth) APP 12, APP 13
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A).

## Compliance Lead

**US-1** As a Compliance Lead, I want to assemble the prescriber reporting bundle for a period, so
that the reporting obligation is evidenced from stored data rather than a manual spreadsheet.
- Acceptance: the run reconciles to the approval register at the approval grain; it is a drafting aid
  that the prescriber reviews — the platform does not submit (`08 §6`).
- S: `reports:export`; tenant scoped; aggregate output carries no patient-identifying rows.
- A: `report.generated` with period, prescriber and approval identifiers; the name is registration-
  pending per `07 §1`.

**US-2** As a Compliance Lead, I want a versioned report so that a correction is a new version that
references the submitted one, and a submitted report is immutable.
- Acceptance: re-running for the same period creates a new version; the prior version is untouched.
- S: no update path to a submitted report; the app role holds no `DELETE`.
- A: `report.generated` carries `version` and `supersedes_report_run_id`.

**US-3** As a Compliance Lead, I want a missed reporting period surfaced as a dashboard item, so that
an administrative omission is visible without blocking clinical care.
- Acceptance: the item is visible to the Practice Owner and the Compliance/Auditor.
- S: dashboard item respects tenant scope; no hard block on prescribing in the MVP (`08 §6`).
- A: `report.missed` — **registration-pending**, see `05 §Registration`.

## Practice Owner

**US-4** As a Practice Owner, I want to export patient-level data for a stated purpose, so a
legitimate request is met while bulk access stays controlled.
- Acceptance: `export:bulk` without a recent step-up is refused until step-up succeeds and a reason is
  given; the artefact is watermarked, expires, and records the row count and period (`22 §US-28`).
- S: step-up plus a typed reason; tenant scoped; short-lived presigned URL; scheduled expiry and
  deletion of the artefact.
- A: `export.requested`, `export.downloaded`, `export.expired`.

**US-5** As a Practice Owner, I want to see who exported what and why, so that bulk access is
attributable.
- Acceptance: the export list shows requester, reason code, row count and period for the tenant.
- S: `exports:read`; RLS scoped; cross-tenant id returns `404`.
- A: `export.read` — **registration-pending**.

## Privacy Officer

**US-6** As a Privacy Officer, I want to receive, scope and decide an access, correction or deletion
request, so that APP 12 and APP 13 are handled with a recorded outcome.
- Acceptance: the request moves through `RECEIVED → IDENTITY_VERIFICATION → SCOPING → IN_PROGRESS →
  DECISION → FULFILLED | REFUSED → CLOSED` (`14 §4`).
- S: `dsar:manage`; a request never returns another patient's record — cross-patient read returns
  `404`; identity verification is a mandatory state, not a checkbox.
- A: `dsar.received` and `dsar.fulfilled` — both **registration-pending**.

**US-7** As a Privacy Officer, I want a correction request to append a correction or archive the
record, never to hard-delete it.
- Acceptance: the original is not overwritten; the correction is associated as APP 13 requires;
  `deleted_at` is never set by a correction path (`14 §3.1`, §3.5).
- S: the correction path holds no delete privilege; an attempted `DELETE` as `clinos_app` raises
  `42501`.
- A: `dsar.correction_applied` — **registration-pending**.

**US-8** As a Privacy Officer, I want a deletion request inside minimum retention refused with reasons.
- Acceptance: the refusal is recorded with the ground relied on; the response is issued and stored
  (`14 §1`, §4 `REFUSED`).
- S: no record is purged by the request path; only the retention job purges, and it is held-aware.
- A: `dsar.deletion_assessed` with the ground — **registration-pending**.

## DSAR handler

**US-9** As a DSAR handler, I want the access response assembled as a bounded export, so that the
requester receives their own record set and nothing else.
- Acceptance: the export is scoped to one patient in one tenant; the artefact is watermarked and
  expires on the same schedule as any other export.
- S: same reason, step-up, re-authorisation and URL rules as US-4; a request naming another patient
  returns `404` and is audited as denied.
- A: `dsar.fulfilled` on issue and `export.downloaded` on collection.

## Retention job owner

**US-10** As a Privacy Officer, I want the retention job to skip held records and abort when the hold
check cannot be evaluated, so that destruction is never accidental.
- Acceptance: held records are excluded and the exclusion count is reported; an unevaluable hold
  check aborts the run and purges nothing (`14 §3.2`, T6, T15).
- S: the job runs as a dedicated role that may purge clinical tables but never the audit table.
- A: `retention.job_run` with candidates, purged, held, failed and the oldest due-but-unpurged age.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Role names must align to `06-authentication-rbac.md` §9 before build; `dsar:manage` and `retention:run` are not in that matrix (OPEN-5) | CTO | OPEN |
| Is `report:schedule` in MVP scope? No story above evidences scheduled delivery (OPEN-1) | Head of Product | OPEN |
| Response timeframes for an APP 12 access request are set by law and not invented here | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
