---
doc_id: OZ-FEAT-11-DATA
title: "Prescribing — data classification and audit events"
owner: Privacy Officer + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-11
phase: 03-phase-3-eprescribing
gate: [4, 5]
source:
  - clinic-os-secure-by-design/12-data-classification.md §1, §3, §5
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2
  - clinic-os-secure-by-design/13-data-residency.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md
repo_docs:
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

## The seven levels

From `12-data-classification.md` §1, the seven levels are `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`,
`SENSITIVE`, `HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`. The ladder is a containment ladder: each
level is a superset of the controls beneath it. `HIGHLY_SENSITIVE` carries a hard prohibition — never in an
application log line, an analytics pipeline, error telemetry, a support ticket or a crash report
(`12 §5.2`).

## Field classification

| Field | Table | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- | --- |
| `prescription_id` | all three | HIGHLY_SENSITIVE | pseudonymous | aggregate only | prescribing-event identifier |
| `medicine_name` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | product plus patient reveals treatment |
| `dosage_form` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | approval grain and clinical decision |
| `dose_instruction` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | directions are clinical content |
| `quantity` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | infers duration and pattern of use |
| `repeats` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | as above |
| `schedule8_flag` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | controlled-medicine status |
| `tga_category` | `prescriptions` | HIGHLY_SENSITIVE | **never** | aggregate only | reveals treatment category (`12 §3`) |
| `prescriber_id` | `prescriptions` | SENSITIVE | pseudonymous | pseudonymous | health-practitioner identifier |
| `state` / `dispatch_status` | `prescriptions` | SENSITIVE | yes | aggregate only | operational state, safe without payload |
| `rail_reference` | `prescriptions` | SENSITIVE | **never** | **never** | external rail reference linking to the script |
| `patient_id` | `prescriptions` | HEALTH_INFORMATION | pseudonymous | pseudonymous | opaque internal identifier |
| `approval_id`, `approval_state` | `prescriptions` | SENSITIVE | pseudonymous | aggregate only | approval lineage at dispatch |
| `idempotency_key` | `prescriptions` | INTERNAL | pseudonymous | no | server-computed; no clinical content |
| `event_type`, `from_state`, `to_state` | events/history | INTERNAL | yes | aggregate only | closed vocabulary |
| `reason_code`, `cancel_reason_code` | all | SENSITIVE | code only | aggregate only | free text never logged (`12 §5.4`) |
| Signature artefact and signing key | — | **SECRET** | **never** | never | secret store only, referenced by ARN |
| `signed_at`, `signed_by`, `service_date`, `version`, `supersedes_id` | `prescriptions` | **OPEN** | not yet assigned | not yet assigned | absent from `12 §3`; interim: no lower than SENSITIVE |

`detail` on `prescription_events` is redacted to the state change and changed field **names**; it never
carries a clinical value. `12 §5.3`: a raw identifier in a log line is a test failure.

## Residency

All fields are stored in the Australian production region (`13-data-residency.md`). No third party receives
them in the MVP; the one outbound flow is the provider rail and is governed by FEAT-13.

## Audit event catalogue

Every event uses the standard envelope from `07-audit-architecture.md` §2:
`event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result, reason,
source_ip, request_id, correlation_id, prev_hash, hash`. `result` is `SUCCESS | DENIED | FAILED | UNKNOWN`.

The canonical action names are the lowercase dot form mandated by `07 §1`. The source's story labels
(`20 §7`, US-21…US-26) are shown for traceability; the `07 §1` column is normative.

| Action (07 §1) | Story label (source) | Trigger | Result | Key fields (no PHI values) |
| --- | --- | --- | --- | --- |
| `prescription.create` | `PRESCRIPTION_STAGED` | draft created | SUCCESS | actor, tenant, `prescription_id`, `patient_id`, `request_id` |
| `prescription.modify` | — | draft modified | SUCCESS | `prescription_id`, changed field **names**, `reason` |
| `prescription.sign` | `PRESCRIPTION_SIGNED` | signature applied with step-up | SUCCESS | `prescriber_id`, `patient_id`, `step_up = true` |
| `prescription.dispatch` | `PRESCRIPTION_DISPATCH_REQUESTED` | gate passed and queued (FEAT-10) | SUCCESS | `approval_id`, `idempotency_key`, `provider` |
| `prescription.dispatch` | `PRESCRIPTION_DISPATCH_CONFIRMED` | provider or webhook confirmed | SUCCESS | `reason = PROVIDER_CONFIRMED / WEBHOOK_CONFIRMED` |
| `prescription.dispatch_blocked` | `PRESCRIPTION_DISPATCH_BLOCKED` | gate refused (FEAT-10) | DENIED | `block_reason`; never suppressed |
| `prescription.dispatch_failed` | — | provider error or unknown outcome | FAILED / UNKNOWN | `error_class`, `outcome_class`; no payload |
| `prescription.reject` | `PRESCRIPTION_CANCELLED` | cancel or reversal | SUCCESS | `reason` code required |
| `auth.step_up_failed` | — | stale or missing step-up | DENIED | attempted operation and resource |

**Names absent from `07 §1`** — do not ship without adding them there first (`07 §1`: no module invents an
action name). Recorded as OPEN, not silently mapped:

| Source label | Where it appears | Gap |
| --- | --- | --- |
| `PRESCRIPTION_RECONCILED` | `20 §7`, US-26 | no `07 §1` action; reconciliation is FEAT-12 |
| `RECONCILIATION_RUN` | US-26 | no `07 §1` action |
| `DISPATCH_WEBHOOK_RECEIVED`, `DISPATCH_WEBHOOK_REJECTED`, `DISPATCH_CONFIRMED` | US-25 | belong to FEAT-12; no `07 §1` action |
| Uppercase story labels generally | `20 §7`, US-21…US-26 | `07 §1` mandates lowercase dot form; the label set must be reconciled |

A blocked dispatch is recorded even when the caller cannot see the approval state, because the pattern of
refusals is the signal (`09 §9`). **Denied and failed attempts are audited with the same fidelity as
successes.**

## Retention

Prescription records are retained with the patient's clinical record and are never deleted by the
application while that record is active (`04 §9`; `REVOKE DELETE`). Audit events are retained for the
period owned by the Compliance Lead. Per-jurisdiction periods, and whether a legal hold suspends
retention, are **REQUIRES LEGAL/REGULATORY VALIDATION**.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Classification of `signed_at`, `signed_by`, `service_date`, `version`, `supersedes_id`, absent from `12 §3` | Privacy Officer | OPEN |
| Action names absent from `07 §1` (`PRESCRIPTION_RECONCILED`, `RECONCILIATION_RUN`, the US-25 webhook labels) | CTO + Clinical Safety Officer | OPEN |
| Reconciliation of the uppercase story labels with the `07 §1` lowercase dot form | Compliance Lead | OPEN |
| Retention period per jurisdiction and legal-hold behaviour | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
