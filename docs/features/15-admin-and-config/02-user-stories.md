---
doc_id: OZ-FEAT-15-STORY
title: "Administration and configuration — user stories"
owner: Head of Product
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-15
phase: 04-phase-4-pilot-go-live
gate: [4]
source:
  - clinic-os-secure-by-design/22-user-stories.md US-01, US-03, US-09
  - clinic-os-secure-by-design/06-authentication-rbac.md §8, §11
  - clinic-os-secure-by-design/20-product-requirements.md §12
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
---

# User stories

Each story carries a security criterion (S) and an audit criterion (A). Every mutating story is
re-authorised server-side; a frontend flag or hidden button is never a control (`06 §11`).

## Practice Owner
**US-1** As a Practice Owner I want to change a tenant security policy so that the clinic's risk position
matches its obligations.
- Acceptance: the change is applied, versioned with actor and timestamp, and refused without step-up.
- S: `tenant:configure` plus step-up with a passkey or hardware key, 5 minutes, single use; TOTP excluded
  for a security-configuration change.
- A: `tenant.security_config_change` with `changed_fields` (names only) and `auth.step_up`.

**US-2** As a Practice Owner I want to see the effective configuration, its version and its history
before I change it.
- Acceptance: current values, versions and prior versions are listed; no secret value is returned.
- S: `admin:read`, tenant-scoped by RLS; the response schema is an allow-list.
- A: read audited; no payload carries a secret.

**US-3** As a Practice Owner I want to set the TGA inbox confidence threshold with clinical sign-off so
that a low-confidence record is never auto-associated.
- Acceptance: the value is stored with a CSO sign-off reference; a change without one is refused.
- S: `tenant:configure` plus step-up; below-threshold records always route to human verification.
- A: `tenant_policy.changed` carrying `policy_key`, from/to values and `cso_signoff_reference`.

## CTO / Platform
**US-4** As a platform engineer I want to toggle a feature flag so that I can roll a change out or back
without a deploy.
- Acceptance: the flag is versioned; a safety-gate flag requires an approval reference.
- S: `admin:feature_flag` plus step-up; strict schema; unknown fields rejected.
- A: `feature_flag.changed` with `flag_key`, `from`, `to`, `version`, `approval_reference`.

**US-5** As a platform engineer I must not be able to turn the safety gate off, even by mistake.
- Acceptance: a disable attempt on a reserved safety-gate flag is refused with `422`.
- S: the disabled state is unrepresentable; a trigger raises `SAFETY_GATE_FLAG_IMMUTABLE`.
- A: `feature_flag.changed` with `result = DENIED` and the refusal reason.

**US-6** As a platform operator I want time-boxed break-glass access with a reason so that emergency
support is possible and always visible.
- Acceptance: granted for a bounded window against a ticket reference; refused without a reason.
- S: no standing access; scoped to named resources; step-up with a passkey or hardware key.
- A: `AUTH_BREAK_GLASS_GRANTED` (source name) on grant, with `ticket_reference`, `expires_at`, `step_up`,
  and a dual notification to the practice owner and the Security Lead.

**US-7** As a platform operator I want break-glass to expire and be reviewed so that an emergency path
never becomes routine.
- Acceptance: access ends automatically at `expires_at`; no renewal silently extends it.
- S: expiry is enforced server-side on every request; an interrupted session is re-checked.
- A: `BREAK_GLASS_EXPIRED` (source name) plus a retrospective review record naming the reviewer.

**US-8** As a platform operator I want to run a retention job safely so that overdue records are purged
without destroying records under hold.
- Acceptance: a dry run reports a count and a manifest and deletes nothing; a live run requires an
  approved dry run; a held record is excluded and counted.
- S: an approver who is not the requester plus step-up; the hold check runs before every delete; the run
  aborts if the hold check cannot be evaluated.
- A: `retention.job_run` with rule ID and counts, and a deletion certificate carrying no deleted content.

## Clinical Safety Officer
**US-9** As a Clinical Safety Officer I want to sign off a clinical safety parameter so that a threshold
is a recorded clinical decision, not a default.
- Acceptance: the sign-off reference is required for a clinical safety parameter and cannot be blanked.
- S: the parameter is writable only by a role holding `tenant:configure`; the safety gate can never be
  disabled by a parameter.
- A: `tenant_policy.changed` with the sign-off reference and the CSO actor identifier.

## Auditor
**US-10** As an auditor I want read-only access to flag and configuration history so that I can prove who
changed what, when and under which approval.
- Acceptance: I can list and view versions; I cannot change anything.
- S: write endpoints return `403` and are audited; the history source is append-only by grant.
- A: every auditor read is logged; no secret value appears in the export.

**US-11** As an auditor I want the hold register and the retention dry-run manifest so that I can confirm a
purge did not run against a legal hold.
- Acceptance: the manifest and the hold exclusions are visible before a live run.
- S: read-only, tenant-scoped; the hold register is written only through the hold workflow.
- A: read audited; the live-run certificate is retained.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| `admin:*` codes are candidates in feature 03 OPEN-1, not granted permissions | CTO + Security Lead | OPEN |
| Whether platform-scope administration is a distinct role (`20 §12`) | CTO | OPEN |
| Dual-notification recipients and the retrospective review cadence for break-glass | Compliance Lead | OPEN |
| Legal-hold register ownership and the auditor's write path to it | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
