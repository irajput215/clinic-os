---
doc_id: OZ-SDLC-04-TASKS
title: Phase 4 — Pilot go-live tasks
owner: Head of Platform
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
phase: 4
gate: Gate 6 — Production; Gate 7 — Go-Live
source:
  - clinic-os-secure-by-design/26-security-gates.md
  - clinic-os-secure-by-design/23-sprint-plan.md
  - clinic-os-secure-by-design/28-aws-network-and-deployment.md
  - clinic-os-secure-by-design/29-operations-and-observability.md
  - clinic-os-secure-by-design/18-incident-response.md
  - clinic-os-secure-by-design/15-privacy-impact-assessment.md
  - clinic-os-secure-by-design/16-vendor-register.md
  - clinic-os-secure-by-design/17-compliance-control-matrix.md
  - clinic-os-secure-by-design/13-data-residency.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md
  - clinic-os-secure-by-design/27-security-testing.md
  - clinic-os-secure-by-design/90-owner-brief.md
---

> **The phase specification this list was written against has been superseded** by the numbered feature folders under [`../features/`](../features/). Requirements, design, threats, data handling, tests and the Definition of Done now live there, one folder per feature.

# Phase 4 — Pilot go-live tasks

Tasks for M4. `Controls` cites the twelve controls in [`../README.md`](../reference/build-contract.md) §6. `Blocked by`
names D-003, D-004 or none. A task in this list is not started until [`spec.md`](../features/16-operations-and-observability/01-requirements.md) is approved.

---

## A. Blocking decisions and environment separation

- [ ] **T4-1 — Close D-003 by deciding the identity model**
  - Acceptance: D-003 is `Accepted` with Option A (managed OIDC) or Option B (hardened self-hosted password auth) named; if B, the compensating-control statement and threat-model update are recorded.
  - Verify: `docs/reference/decisions/D-003-identity-model.md` status line reads Accepted; `docs/reference/decisions/README.md` no longer lists D-003 as blocking Gate 3.
  - Files: `docs/reference/decisions/D-003-identity-model.md`, `docs/reference/decisions/README.md`, `docs/features/01-tenancy-and-clinics/`
  - Controls: Control 1 (Authentication)
  - Evidence: Accepted decision record with rationale and date
  - Blocked by: none

- [ ] **T4-2 — Close D-004 by choosing the deployment target**
  - Acceptance: Option A, B or C is named and dated; if B or C, the record states which Gate 6 checks are replaced, by what control, with what evidence (D-004 open item 5).
  - Verify: `docs/reference/decisions/D-004-deployment-target.md` status line reads Accepted; the substitution list is attached.
  - Files: `docs/reference/decisions/D-004-deployment-target.md`, `docs/reference/decisions/README.md`
  - Controls: Control 8 (Secrets management), Control 12 (Compliance evidence)
  - Evidence: Accepted decision record with the Gate 6 substitution matrix
  - Blocked by: none

- [ ] **T4-3 — Review the committed root `.env` and rotate any real secret**
  - Acceptance: every value in `.env` is confirmed non-secret or rotated; no secret remains committed; the replacement lives in the D-004 secret store.
  - Verify: `git log -p -- .env` reviewed; `gitleaks`-equivalent secret scan over full history returns zero findings; `.env` contains only non-secret defaults or is removed from tracking.
  - Files: `.env`, `.gitignore`, `compose.yml`, `compose.deploy.yml`, the chosen secret store configuration
  - Controls: Control 8 (Secrets management)
  - Evidence: Secret-scan report (zero findings) and the rotation record
  - Blocked by: D-004

- [ ] **T4-4 — Write the environment separation model**
  - Acceptance: Development, Staging and Production are documented as sharing no database, bucket, secret, key, credential or API key; the model names the production region and how it is enforced.
  - Verify: Artefact review against `clinic-os-secure-by-design/28-aws-network-and-deployment.md` §8; the region is `ap-southeast-2` or the D-004 Option B host is proven Australian.
  - Files: the environment separation model artefact (location recorded in the Gate 6 sign-off record), `compose.yml`, `compose.deploy.yml`
  - Controls: Control 7 (Encryption), Control 8 (Secrets management)
  - Evidence: Environment separation model document
  - Blocked by: D-004

- [ ] **T4-5 — Provision the production environment and its secret store**
  - Acceptance: a production environment exists per the D-004 outcome; production secrets live in the chosen secret store and are injected at runtime, not read from a committed `.env`.
  - Verify: `docker compose -f compose.yml -f compose.deploy.yml config` resolves with production values; no production credential appears in the repository; secret store references are resolvable.
  - Files: `compose.yml`, `compose.deploy.yml`, secret store configuration, deployment workflow
  - Controls: Control 7 (Encryption), Control 8 (Secrets management)
  - Evidence: Production environment inventory and secret store configuration export
  - Blocked by: D-004

- [ ] **T4-6 — Verify environment separation (Gate 6 check 4)**
  - Acceptance: no production database, bucket, secret, key or credential is reachable from Development; where the check has no compose equivalent, the D-004 substitution record is referenced instead of a claimed pass.
  - Verify: Environment separation checklist executed against the deployed environments; IAM/WAF-dependent rows explicitly annotated "no equivalent, contingent on D-004".
  - Files: the environment separation checklist artefact, `compose.yml`, `compose.deploy.yml`
  - Controls: Control 3 (Tenant isolation), Control 8 (Secrets management)
  - Evidence: Environment separation checklist (Gate 6 bundle item 4)
  - Blocked by: D-004

- [ ] **T4-7 — Confirm the no-production-data-in-non-production position (Gate 6 check 5)**
  - Acceptance: no production data exists in any non-production environment without an approved de-identification manifest signed by the Compliance Lead; non-production is seeded synthetically.
  - Verify: Synthetic-seed policy plus a de-identification manifest for any extract; environment data inventory.
  - Files: test data policy artefact, extract manifest (if any)
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Synthetic-seed policy and extract manifest / approval
  - Blocked by: none

## B. Staging deploy, migration and restore

- [ ] **T4-8 — Deploy the release commit to Staging and verify end to end**
  - Acceptance: the pilot scope works in Staging against the Parchment sandbox with synthetic data; the CI pipeline is green on the release commit in the fixed order; the isolation suite passes and asserts absence.
  - Verify: `docker compose -f compose.yml -f compose.deploy.yml up -d --build`; `cd backend && uv run alembic upgrade head`; `uv run pytest`; `bunx playwright test`; CI run record.
  - Files: `compose.yml`, `compose.deploy.yml`, `.github/workflows/`, `backend/app/alembic/versions/`
  - Controls: Control 11 (Security testing), Control 12 (Compliance evidence)
  - Evidence: Staging deploy record, CI run id, end-to-end test report
  - Blocked by: D-003, D-004

- [ ] **T4-9 — Confirm expand-and-contract migration ordering and zero-downtime capability (Gate 6 check 10)**
  - Acceptance: migrations are backward compatible with the previous application version for the rollback window; a rolling deploy produces no failed request on the health-checked route.
  - Verify: `cd backend && uv run alembic upgrade head` on a fresh DB, then the previous app version runs against the migrated schema; deployment test `deploy.migration-expand-contract` and `deploy.rolling-no-errors` pass.
  - Files: `backend/app/alembic/versions/`, deployment workflow
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Migration review and upgrade output
  - Blocked by: D-004

- [ ] **T4-10 — Perform and time a restore drill (Gate 6 check 6)**
  - Acceptance: a restore completes into a clean instance inside the agreed RTO; later deletion manifests are re-applied so purged records stay purged; keys and secrets are restored as part of the drill.
  - Verify: Deployment test `deploy.backup-restore` passes; timed restore record shows elapsed time against the agreed RTO; retention test T11 passes.
  - Files: restore runbook artefact, backup job configuration, `compose.yml`
  - Controls: Control 7 (Encryption), Control 12 (Compliance evidence)
  - Evidence: Timed restore drill record (Gate 6 bundle item 6)
  - Blocked by: D-004

- [ ] **T4-11 — Confirm RPO and RTO with the Practice Owner**
  - Acceptance: the Practice Owner signs the RPO and RTO or sets alternatives in writing; the restore drill in T4-10 is measured against the agreed figures, not the 15 min / 4 h proposals.
  - Verify: Signed RPO/RTO statement; the restore record references it by date.
  - Files: RPO/RTO statement (location recorded in the Gate 6 sign-off record)
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Signed RPO and RTO statement
  - Blocked by: none

## C. Monitoring and alerting

- [ ] **T4-12 — Build the alert catalogue with thresholds, routes, runbooks and owners**
  - Acceptance: every enabled alert has a threshold, a route and a runbook anchor; no alert is enabled without all three; every alert names one owner.
  - Verify: Alert catalogue review against `clinic-os-secure-by-design/29-operations-and-observability.md` §5; observability test O13 (every alert resolves to an existing runbook anchor) passes.
  - Files: alert definitions (monitoring configuration), runbook set (`18-incident-response.md` R1–R8)
  - Controls: Control 6 (Audit logging), Control 10 (Abuse protection)
  - Evidence: Alert catalogue export, and the O13 test result
  - Blocked by: D-004

- [ ] **T4-13 — Test the non-terminal-prescription and reconciliation-failure alerts**
  - Acceptance: a prescription left in `REQUIRES_RECONCILIATION` beyond the normal band raises the SEV3 alert; a failed reconciliation run raises its alert and reaches the route.
  - Verify: Induced non-terminal state plus a forced reconciliation failure; both alerts observed; alert-firing test record.
  - Files: monitoring configuration, reconciliation job configuration
  - Controls: Control 6 (Audit logging), Control 11 (Security testing)
  - Evidence: Alert-firing test record for both signals
  - Blocked by: D-004

- [ ] **T4-14 — Test the cross-tenant denial alert**
  - Acceptance: a request with a missing or invalid tenant context fails closed and raises the RLS context failure alert (SEV2); a simulated cross-tenant read raises the SEV1 cross-tenant read signal.
  - Verify: Induced RLS context failure and a simulated cross-tenant response; both alerts observed; observability test O10 passes.
  - Files: monitoring configuration, `backend/tests/isolation/`
  - Controls: Control 3 (Tenant isolation), Control 10 (Abuse protection)
  - Evidence: Alert-firing test record for cross-tenant denial (Gate 6 bundle item 7)
  - Blocked by: none

- [ ] **T4-15 — Test the audit-write-failure alert**
  - Acceptance: an induced audit write failure raises the SEV2 alert and reaches the on-call route; the operation fails closed rather than proceeding without an audit event.
  - Verify: Induced audit write failure; observability test O9 passes; the alert record names the route and the responding owner.
  - Files: monitoring configuration, audit writer
  - Controls: Control 6 (Audit logging)
  - Evidence: Alert-firing test record for audit write failure (Gate 6 bundle item 7)
  - Blocked by: none

- [ ] **T4-16 — Run the sentinel leak tests (no PHI in any sink)**
  - Acceptance: sentinel values for a prescription payload, a clinical note, OCR text, a token and a key never appear in any log sink, error response or client bundle; the redaction block raises its signal.
  - Verify: Observability tests O1–O4 pass; `cd backend && uv run pytest tests/security -q -k "sentinel or no_phi"`; `frontend-features/tests/security/storage-no-phi.spec.ts` passes.
  - Files: `backend/tests/security/`, `frontend-features/tests/security/`, monitoring configuration
  - Controls: Control 6 (Audit logging), Control 9 (Error handling)
  - Evidence: Sentinel leak test report (zero leaks)
  - Blocked by: none

## D. Security testing and penetration test

- [ ] **T4-17 — Complete the five security test categories**
  - Acceptance: Authentication, Authorisation, Prescription safety gate, Documents and API categories all pass with the named tests executed; the isolation suite is 100% pass; the negative dispatch matrix blocks every case with no provider call.
  - Verify: `cd backend && uv run pytest`; security test report for the five categories; isolation suite pass rate 100%.
  - Files: `backend/tests/security/`, `backend/tests/isolation/`
  - Controls: Control 11 (Security testing)
  - Evidence: Security test report (Gate 6 bundle item 1)
  - Blocked by: D-003

- [ ] **T4-18 — Make SAST, dependency, container and secret scans clean of Critical**
  - Acceptance: the CI pipeline runs the fixed order `lint → typecheck → unit → integration → security tests → SAST → dependency → container → secret → build → deploy`; all four scans are clean of Critical on the release commit.
  - Verify: CI pipeline definition review; scan reports attached to the pipeline run; a deliberately planted finding is blocked.
  - Files: `.github/workflows/`, `.pre-commit-config.yaml`, scanner configuration
  - Controls: Control 8 (Secrets management), Control 11 (Security testing)
  - Evidence: SAST, dependency, container and secret scan reports (Gate 6 bundle item 2)
  - Blocked by: none

- [ ] **T4-19 — Book the independent penetration test with a date before go-live**
  - Acceptance: an independent health-sector tester is engaged under a contract covering the test environment, data handling and disclosure; the scope covers authentication, session handling, tenant isolation, the prescription safety gate, TGA inbox ingestion, document handling, bulk export, the audit console and the API surface; the booking date is before go-live and the test runs against synthetic data only.
  - Verify: Booking confirmation with a dated engagement letter and the agreed scope; no production patient data in the test environment.
  - Files: penetration test scope and engagement artefact (location recorded in the Gate 6 sign-off record)
  - Controls: Control 11 (Security testing)
  - Evidence: Booking confirmation with a date before go-live (Gate 6 bundle item 3)
  - Blocked by: none

- [ ] **T4-20 — Track penetration test findings to closure or acceptance**
  - Acceptance: the complete report exists; every Critical and High finding is closed with a retest and a regression test, or formally accepted with a compensating control and an expiry; no Critical finding remains open.
  - Verify: Finding register by severity; retest evidence; regression tests added; zero open Critical and zero open High.
  - Files: finding register, `backend/tests/security/` (new regression tests)
  - Controls: Control 11 (Security testing)
  - Evidence: Penetration test report, retest evidence and the finding register (Gate 7 bundle item 1)
  - Blocked by: none

## E. Privacy, retention, residency and vendor readiness

- [ ] **T4-21 — Complete and sign the privacy impact assessment**
  - Acceptance: the PIA is signed by each role in `15-privacy-impact-assessment.md` §7; every APP-by-APP row has a status and no row reads "compliant"; every risk has an owner and a residual position.
  - Verify: Signed PIA artefact; unsigned rows are an open item and block Gate 7 check 3.
  - Files: PIA artefact (location recorded in the Gate 7 sign-off record)
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Signed PIA (Gate 7 bundle item 3)
  - Blocked by: none

- [ ] **T4-22 — Reconcile the data-flow map and the cross-border register**
  - Acceptance: every data flow in the PIA maps to a register row (DR-01 … DR-16); no row is `OFFSHORE-APPROVED`; every `UNKNOWN` or not-passed row has a named owner and stays marked **REQUIRES LEGAL/REGULATORY VALIDATION**.
  - Verify: Register reconciliation against each vendor's actual hosting and sub-processor list.
  - Files: `docs/reference/` cross-border register artefact, vendor evidence store
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Reconciled cross-border register with owners
  - Blocked by: none

- [ ] **T4-23 — Put the retention schedule and purge path in place**
  - Acceptance: a retention schedule exists per record type with trigger and deletion mode; the purge job writes a deletion certificate per run with the rule, approver and count and no deleted content; legal hold blocks purge; a restore re-applies deletion manifests.
  - Verify: Retention tests T1–T15 pass, including T5 (inside-minimum never selected), T6 (hold blocks purge), T8 (certificate), T11 (restore re-applies deletion) and T15 (fail closed).
  - Files: retention schedule artefact, purge job code and migration, `backend/tests/`
  - Controls: Control 6 (Audit logging), Control 12 (Compliance evidence)
  - Evidence: Retention schedule, purge run record and deletion certificate sample
  - Blocked by: none

- [ ] **T4-24 — Complete vendor register readiness for Gate 7**
  - Acceptance: every rail's vendor row names a credential owner and an outage playbook; every Tier 1 vendor holds an executed data processing agreement or is recorded as an open item; no vendor receives health information before the onboarding gate passes.
  - Verify: Vendor register review (`16-vendor-register.md` §2, §3); each row's credential owner and outage playbook columns populated.
  - Files: vendor register artefact, vendor evidence store
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Vendor register rows with credential owner and outage playbook (Gate 7 bundle item 4)
  - Blocked by: none

## F. Clinical readiness and access baseline

- [ ] **T4-25 — Record pilot clinic training**
  - Acceptance: pilot staff are trained on the human verification step and the manual fallback; the record names participants, date and content.
  - Verify: Training record review; a trainee can state when to invoke the fallback and why a blocked dispatch is not a workaround.
  - Files: training record artefact, training material
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Training record (Gate 7 bundle item 6)
  - Blocked by: none

- [ ] **T4-26 — Perform the manual clinical fallback drill**
  - Acceptance: the clinic exercises the manual path end to end, including the trigger, the offline prescribing and record-keeping path, and the back-capture when the platform returns; the drill record names participants, date, duration, what failed and actions with owners.
  - Verify: Drill record review against `28-aws-network-and-deployment.md` §10; the provider-outage playbook per rail is walked through.
  - Files: fallback drill record artefact, provider outage playbooks
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Manual fallback drill record (Gate 7 bundle item 6)
  - Blocked by: none

- [ ] **T4-27 — Record the access-review baseline**
  - Acceptance: every privileged principal is recorded with the environment they reach, the access path (standing or just-in-time) and the review date; no standing production access; offboarding revokes credentials, sessions, tokens and integration access.
  - Verify: Access baseline review against `29-operations-and-observability.md` §9; the just-in-time elevation records exist.
  - Files: access baseline artefact, IAM/access configuration
  - Controls: Control 2 (Authorisation), Control 8 (Secrets management)
  - Evidence: Access-review baseline (Gate 7 bundle item 9)
  - Blocked by: D-004

- [ ] **T4-28 — Name people, not roles, in the incident runbooks and on-call rota**
  - Acceptance: the contact tree names individuals with a backup; a named person is on call for the first two weeks; the notifiable-breach assessment path is understood and a decision is recorded even when not notifiable.
  - Verify: Contact tree and on-call rota review; a tabletop walkthrough of the R1 and NDB paths confirms names and routes.
  - Files: contact tree artefact, on-call rota artefact, runbook set R1–R8
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Contact tree and on-call rota (Gate 7 bundle item 5)
  - Blocked by: none

- [ ] **T4-29 — Confirm the clinical safety hazard log is current and reviewed**
  - Acceptance: the hazard log has a review date inside the review window and a named reviewer; every open hazard has an owner and a date.
  - Verify: Hazard log review; Clinical Safety Officer confirmation.
  - Files: hazard log artefact
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Hazard log with review date (Gate 7 bundle item 8)
  - Blocked by: none

## G. Gate evidence, review and go-live

- [ ] **T4-30 — Assemble the Gate 6 evidence bundle**
  - Acceptance: all ten Gate 6 artefacts in [`plan.md`](../features/16-operations-and-observability/01-requirements.md) §3.1 are present and each links to the control it proves; IAM and WAF checks carry the D-004 substitution record or an explicit "no equivalent" note; open Critical findings = 0.
  - Verify: Bundle index review against the Gate 6 check list; the signed record uses the template in `clinic-os-secure-by-design/26-security-gates.md` §9.
  - Files: Gate 6 evidence bundle (location recorded in the sign-off record)
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Gate 6 evidence bundle + signed Gate 6 record
  - Blocked by: D-003, D-004

- [ ] **T4-31 — Assemble the Gate 7 evidence bundle**
  - Acceptance: all ten Gate 7 artefacts in [`plan.md`](../features/16-operations-and-observability/01-requirements.md) §3.2 are present; open Critical findings = 0 and open High findings = 0; every unresolved risk has a documented acceptance with a compensating control and an expiry; every **REQUIRES LEGAL/REGULATORY VALIDATION** item has an interim position and an owner.
  - Verify: Bundle index review against the Gate 7 check list; signed record uses the §9 template; severity counts read zero.
  - Files: Gate 7 evidence bundle (location recorded in the sign-off record)
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Gate 7 evidence bundle + signed Gate 7 record
  - Blocked by: D-003, D-004

- [ ] **T4-32 — Record interim positions for L1–L14**
  - Acceptance: each of the 14 legal questions has a documented interim position, a named owner and a review date; none is closed by an engineering opinion.
  - Verify: Interim position register review against `90-owner-brief.md` §10; every row still marked **REQUIRES LEGAL/REGULATORY VALIDATION** is represented.
  - Files: interim position register artefact
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Interim position register (Gate 7 bundle item 10)
  - Blocked by: none

- [ ] **T4-33 — Hold the go-live readiness review and open M4**
  - Acceptance: the review in [`phase.md`](../features/16-operations-and-observability/01-requirements.md) §9 is held; every M4 prerequisite in §5 is true; Gate 6 and Gate 7 records are signed; the on-call person is named and reachable.
  - Verify: Signed Gate 6 and Gate 7 records; the M4 prerequisite checklist fully checked; the readiness review minutes.
  - Files: readiness review minutes, signed gate records
  - Controls: Control 12 (Compliance evidence)
  - Evidence: Go-live readiness review minutes and the M4 entry record
  - Blocked by: D-003, D-004

---

## Task counts

| Section | Tasks |
|---|---|
| A. Blocking decisions and environment separation | T4-1 … T4-7 |
| B. Staging deploy, migration and restore | T4-8 … T4-11 |
| C. Monitoring and alerting | T4-12 … T4-16 |
| D. Security testing and penetration test | T4-17 … T4-20 |
| E. Privacy, retention, residency and vendor readiness | T4-21 … T4-24 |
| F. Clinical readiness and access baseline | T4-25 … T4-29 |
| G. Gate evidence, review and go-live | T4-30 … T4-33 |

**D-003-blocked:** T4-8, T4-17, T4-30, T4-31, T4-33.
**D-004-blocked:** T4-3, T4-4, T4-5, T4-6, T4-8, T4-9, T4-10, T4-12, T4-13, T4-27, T4-30, T4-31, T4-33.
**Unblocked now:** T4-1, T4-2, T4-7, T4-11, T4-14, T4-15, T4-16, T4-18, T4-19, T4-20, T4-21, T4-22, T4-23, T4-24, T4-25, T4-26, T4-28, T4-29, T4-32.

## Sources

- `clinic-os-secure-by-design/26-security-gates.md` §7, §8, §9
- `clinic-os-secure-by-design/23-sprint-plan.md` §10, §11
- `clinic-os-secure-by-design/28-aws-network-and-deployment.md` §8, §10, §13
- `clinic-os-secure-by-design/29-operations-and-observability.md` §5, §9, §11
- `clinic-os-secure-by-design/27-security-testing.md` §2, §4, §6, §8, §9
- `clinic-os-secure-by-design/18-incident-response.md` §2, §3, §5, §6
- `clinic-os-secure-by-design/14-retention-and-deletion.md`, `15-privacy-impact-assessment.md`, `16-vendor-register.md`, `13-data-residency.md`
- `clinic-os-secure-by-design/90-owner-brief.md` §10
