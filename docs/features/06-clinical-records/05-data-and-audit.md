---
doc_id: FEAT-CLIN-05
title: Clinical records, data and audit
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Data and audit

## Field classification

Levels are the **seven** defined by `12-data-classification.md` §1:
`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`, `HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`.
Where doc 04 §3.5 and doc 12 §3 disagree, the **stricter** level applies (README rule).

| Field | Level | In logs | In audit | In analytics | Notes |
| --- | --- | --- | --- | --- | --- |
| `id` (both tables) | INTERNAL | yes | yes | aggregate only | identifiers only |
| `tenant_id` | SENSITIVE | yes | yes | aggregate only | doc 12 §3 sets SENSITIVE; doc 04 §3.5 says INTERNAL — stricter applied |
| `patient_id` | HEALTH_INFORMATION | pseudonymised only | yes | pseudonymised | doc 12 §3 sets HEALTH_INFORMATION; doc 04 §3.5 says INTERNAL — stricter applied |
| `record_type` | HEALTH_INFORMATION | never | action only | never | clinical context once joined to a person |
| `author_id` / `version.author_id` | SENSITIVE | pseudonymised | yes | no | attribution identity; doc 12 §3 `note_author_id` |
| `current_version`, `version`, `supersedes_version` | INTERNAL | yes | yes | count only | lineage |
| `signed_at` | HEALTH_INFORMATION | pseudonymised | yes | never | attribution evidence; stricter than doc 12 §3 (`SENSITIVE`) |
| `deleted_at` | INTERNAL | yes | yes | no | soft-delete clock |
| `body` | **HIGHLY_SENSITIVE** | **never** | **action only** | **never** | narrative; doc 12 §3 `note_body`. See the conflict note below |
| `body_format` | INTERNAL | yes | yes | no | `MARKDOWN` or `PLAIN` |
| `reason` (amendment) | HEALTH_INFORMATION | **never** | action only (code) | **never** | free text may contain clinical content (`12` §5.4) |
| `signature_digest` | SENSITIVE | never | yes | no | **repo-proposed, no source field — OPEN-5** |
| `care_relationship_id`, `purpose` (audit) | SENSITIVE | never | yes | no | authorisation input |

**The narrative is `HIGHLY_SENSITIVE`.** `body`, and the
`subjective` / `objective` / `assessment` / `plan` authoring surface that serialises over it, is
excluded from application logs, analytics pipelines and error telemetry — not in a debug line, not in
a stack trace, not in a crash report (`12` §2, §5.2). The full-text index over `body` exists because
narrative search is a care requirement; the column stays plaintext **under RLS**, encrypted at rest by
KMS (`02` §5.1). Classification conflict: `04` §3.5 calls `body` `HEALTH_INFORMATION`, `12` §3 calls
`note_body` `HIGHLY_SENSITIVE`; this doc applies `HIGHLY_SENSITIVE` (OPEN-1).

## Residency
Australian production region (`ap-southeast-2`), RDS encrypted at rest with KMS, private subnets, no
internet route (`21` §5). All fields stay in region. No third party receives clinical narrative in the
MVP; the narrative is never sent to analytics, telemetry or a support tool. Residency register entry
owner: Compliance Lead. Any future sub-processor touching narrative is OPEN and
**REQUIRES LEGAL/REGULATORY VALIDATION** before it receives any.

## Audit event catalogue

`07-audit-architecture.md` §1 defines the action vocabulary and states: *"No module invents an action
name outside this table without adding it here first."* The events below map the story labels in
`20` §4 and `22` US-11–US-13 onto that vocabulary. **Every label in the right-hand column is absent
from doc 07 §1 and therefore requires registration before build.**

| Event label | doc 07 §1 action | Trigger | Key fields (never clinical text) | Label registered in doc 07 §1? |
| --- | --- | --- | --- | --- |
| `CLINICAL_RECORD_VIEWED` | `clinical_record.read` | read of a record, version or timeline | actor, role, `patient_id`, `care_relationship_id`, `purpose`, `result`, `count` | **No** — named in `20` §4, `21` §9, `22` US-11; requires registration |
| `CLINICAL_NOTE_CREATED` | `clinical_record.write` | a version is created unsigned | actor, tenant, `resource_id`, `patient_id`, `version` | **No** — named in `20` §4, `22` US-12; requires registration |
| `CLINICAL_NOTE_SIGNED` | `clinical_record.write` | `signed_at` set on a version | actor, `resource_id`, `version`, `result` | **No** — absent from doc 07 §1, doc 20 §4 and doc 22; repo-proposed, requires registration (OPEN-5) |
| `CLINICAL_NOTE_AMENDED` | `clinical_record.write` | a new version supersedes an earlier one | actor, `resource_id`, `version`, `supersedes_version`, reason **code** | **No** — named in `20` §4, `22` US-13; requires registration |
| read / write refusal | `clinical_record.read` / `clinical_record.write` | permission, tenant or treating-relationship denial | actor, attempted action, `result = DENIED`, `reason` (`AUTHZ_CARE_RELATIONSHIP_DENIED`, `AUTHZ_DENIED`, `AUTHZ_DENIED_CROSS_TENANT`) | action registered; denial uses the same action with `result = DENIED` |

Each event uses the standard envelope from `07` §2: `event_id, timestamp, tenant_id, actor_id,
actor_role, action, resource_type, resource_id, result, reason, source_ip, request_id, correlation_id,
prev_hash, hash`. The audit store is append-only; the app role holds `INSERT` and `SELECT` only, and
**denied and failed attempts are audited with the same fidelity as successes**. The event is written
in the same transaction as the clinical change; a failed audit write fails the action (`07` §5).

## The rule for audit metadata
**The audit metadata never contains clinical text.** Not the narrative, not the
`subjective`/`objective`/`assessment`/`plan` surface, not a diagnosis, not the amendment free text
(`07` §7; `20` §4: *"The audit metadata never contains clinical content"*). The event records that the
action occurred: the record and version identifiers, the author, the result and a controlled reason
code. `metadata` is allow-listed by key in code, so adding a key is a deliberate change with a test.
`reason` on the audit event is a code, never the clinician's typed amendment reason.

## Retention and deletion

| Record | Minimum retention | Clock trigger | Deletion mode | Legal hold behaviour | Source |
| --- | --- | --- | --- | --- | --- |
| Clinical record versions (narrative) | Same as the clinical record: **at least 7 years** for an adult; **until age 25** for a minor (NSW s 25; Victoria HPP 4.2) | Last date of service / last date of entry for that patient | Never deleted while the parent record is retained; then soft delete and purge | Hold suspends purge; content frozen | `14` §2, §3 |
| Parent `clinical_records` row | Same as above | Same | Soft delete (`deleted_at` + reason), purge only under the schedule | Hold suspends purge | `14` §2, §3.1 |
| Audit events about clinical records | 12 months recommended, longer if the log forms part of the clinical record | Event creation | Archive, never delete inside the retention window | Hold suspends expiry; immutable copy retained | `14` §2; `07` §9 |

**Legal hold.** A hold is a deliberate, recorded decision that suspends destruction for named records.
Who may place one: Privacy Officer, Compliance/Auditor or CTO, with a written reason; a blanket hold
needs CTO approval. Scope is a named tenant, patient or record type. It is reviewed every 90 days; an
unreviewed hold escalates to Compliance/Auditor. **A legal hold suspends automated archiving
indefinitely** — the purge job excludes held records and its backups' expiry is suspended, and the job
fails closed if the hold check cannot be evaluated (`14` §3.2, §3.6). The hold register carries hold
ID, scope, reason, owner, start date and review date; placement and release are audit events.

Per-jurisdiction periods are not uniform and the stricter applicable rule governs. Which rule applies
to a patient who moves between jurisdictions, and whether an erasure request can be satisfied against
a record under retention or hold, are **REQUIRES LEGAL/REGULATORY VALIDATION**.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| `body` classified `HEALTH_INFORMATION` in `04` §3.5 vs `HIGHLY_SENSITIVE` in `12` §3; this doc applies the stricter | Privacy Officer | OPEN |
| `tenant_id`, `patient_id`, `author_id`, `signed_at` levels differ between `04` §3.5 and `12` §3; stricter applied throughout | Privacy Officer | OPEN |
| The four story labels need registration in `07` §1; `CLINICAL_NOTE_SIGNED` appears in no source doc | CTO | OPEN |
| Per-jurisdiction retention periods and the clock trigger | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Legal-hold ownership and authority | Privacy Officer + Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Jurisdiction-move and erasure interactions | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether audit events about a clinical record form part of the clinical record | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
