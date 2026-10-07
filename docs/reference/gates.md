---
doc_id: OZ-REF-GATES
title: Security gates 1-7 — checklists, evidence and approvers
owner: Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
source: ../../clinic-os-secure-by-design/26-security-gates.md
---

# Security Gates 1–7

Seven gates control the path from architecture to a pilot clinic holding real patient data. A gate is a
**stop condition, not a status report**.

- Gate evidence is produced **during** the phase, not assembled on gate day. Reserve the last two days
  of each phase for evidence; it is a deliverable.
- **No self-approval.** The deliverer never signs their own gate.
- **A failed gate stops dependent work.** It is re-run, not carried forward as a background task.
- Conditional passes are limited, named, expiring, and **unavailable for Gate 2 and the prescription
  safety gate in Gate 4**.
- If the evidence is thin, the correct decision is to **fail the gate and re-plan**, not to grant time
  while the risk stays open.

---

## Artefact naming: source contract → this repo

The source contract names TypeScript artefacts. The control is unchanged; the artefact name changes.

| Source contract artefact | This repo's artefact |
|---|---|
| `authz.recomputes_server_side.spec.ts` | `backend/tests/security/test_authz_recomputes_server_side.py` |
| `validation.rejects_unknown_field.spec.ts` | `backend/tests/security/test_validation_rejects_unknown_field.py` |
| `serialisation.omits_restricted_fields.spec.ts` | `backend/tests/security/test_serialisation_omits_restricted_fields.py` |
| `audit.writes_in_same_transaction.spec.ts` | `backend/tests/security/test_audit_writes_in_same_transaction.py` |
| `errors.never_leaks_internal_detail.spec.ts` | `backend/tests/security/test_errors_never_leak_internal_detail.py` |
| `errors.fail_closed.spec.ts` | `backend/tests/security/test_errors_fail_closed.py` |
| `tenant-isolation.pool-reuse` | `backend/tests/isolation/test_pool_reuse.py` |
| `rls.holds_without_app_filter.spec.ts` | `backend/tests/isolation/test_rls_holds_without_app_filter.py` |
| `dispatch.blocks_without_active_approval.spec.ts` | `backend/tests/security/test_dispatch_blocks_without_active_approval.py` |
| `logging.no_phi_in_log_payload.spec.ts` | `backend/tests/security/test_no_phi_in_log_payload.py` |
| `frontend.storage_contains_no_phi.spec.ts` | `frontend/tests/security/storage-no-phi.spec.ts` |
| `security-headers.spec.ts` | `backend/tests/security/test_security_headers.py` |
| Zod schemas | Pydantic v2 models in `backend/app/modules/<module>/schemas.py` |
| ESLint + typecheck pipeline stage | `ruff check` + `mypy --strict` stage |
| Terraform policy tests | compose/deployment configuration review until D-004 is resolved |

---

## Gate 1: Architecture

**Purpose.** Confirm the architecture, threat model and control design exist and cover the pilot scope,
before code hardens around an unexamined design.

**When.** Evidence produced in Phase 0; gate signed at the **Phase 1 boundary**, before Gates 2 and 3.

**Entry criteria.** The architecture is documented; the threat model and decision records exist; the
threat model covers external, internal and integration categories.

**Checks**

- [ ] The threat model is written and names a control and an owner for each identified threat.
- [ ] The tenant isolation model is described, including the connection-pool hazard.
- [ ] The prescription safety gate is described, including the approval grain.
- [ ] The audit envelope and the audited-operation list are defined.
- [ ] The environment separation model is defined for Development, Staging and Production.
- [ ] Data classification exists for every field that carries patient information.
- [ ] The CI security pipeline stages and their order are defined.
- [ ] Residual risks have named owners.

**Evidence.** Threat model, decision records, technical design, data classification, CI pipeline definition.

**Decision maker.** CTO. **Approver.** Security Lead.

**Failure path.** The gate fails; Phase 2 TGA work does not start; gaps are listed with owners and the
gate is re-run at a re-planned date.

**Conditional pass.** Available for evidence completeness only — **not** for a missing threat model or a
missing safety-gate design. Granted by CTO with Security Lead, with a compensating control, an owner and
an expiry no later than the end of Phase 2.

---

## Gate 2: Database

**Purpose.** Prove tenant isolation is enforced **in the database** and the schema can hold the clinical
invariants, before any module depends on it.

**When.** At the Phase 1 boundary, after Gate 1.

**Entry criteria.** Migrations apply to a fresh database; every tenant table has `tenant_id NOT NULL`;
every tenant table has an RLS policy with `USING` and `WITH CHECK`; `FORCE ROW LEVEL SECURITY` is set.

**Checks**

- [ ] Isolation tests assert **absence** across list, filter, sort, search, direct id, nested resource,
      export and cache.
- [ ] The connection-pool reuse test passes: no tenant context leaks between consecutive requests on one
      connection.
- [ ] A request with no tenant context reads no rows and is refused.
- [ ] A forged `tenant_id` in a write is refused by `WITH CHECK`.
- [ ] The application role does not own the tables and has no `BYPASSRLS`.
- [ ] An `UPDATE` or `DELETE` against `audit_log` through the application role is refused.
- [ ] The approval grain is enforced by a GiST exclusion constraint on overlapping active intervals.
- [ ] A schema lint check fails CI when a tenant table lacks a policy.

**Evidence.** Isolation test report, pool-reuse test output, grant listing, constraint definition and its
test, schema lint output.

**Decision maker.** Security Lead. **Approver.** CTO.

**Failure path.** The gate fails; **no module may read or write tenant data** until it passes. The
failing test names the defect and the fix is a security fix, not a backlog item.

**Conditional pass. ❌ NOT AVAILABLE.** Tenant isolation is the control the entire multi-tenant model
depends on. A partial pass is a failed gate.

---

## Gate 3: Authentication

**Purpose.** Prove identity, MFA, session lifecycle, lockout and step-up work and are enforced
server-side.

**When.** At the Phase 1 boundary, after Gate 1, alongside Gate 2.

**Entry criteria.** The identity integration is live; roles and permissions seed data exists; the central
policy layer is in place.

**Checks**

- [ ] MFA is enforced for clinical and administrative roles and cannot be bypassed by a direct API call.
- [ ] Short-lived access tokens expire and are refused after expiry.
- [ ] Refresh tokens rotate, and reuse revokes the token family.
- [ ] A revoked session is refused before its token expiry.
- [ ] Lockout triggers after the defined failure count and the account release path is audited.
- [ ] Step-up is enforced server-side for the five named high-risk operations.
- [ ] RBAC tests show a user without a permission receiving `403` on every protected route.
- [ ] Account recovery is logged with login-level fidelity.
- [ ] No shared accounts exist in the test environment.

**Evidence.** Authentication and RBAC test results, session revocation test output, step-up test results,
lockout test result.

**Decision maker.** Security Lead. **Approver.** CTO.

**Failure path.** The gate fails; no user-facing release; the missing control is fixed and the gate re-run.

**Conditional pass.** Available **only** for account-recovery logging if the recovery path is disabled in
the pilot, with an expiry and a compensating control. **MFA and step-up have no conditional pass.**

> **GATE 3 IS BLOCKED BY D-003.** The source contract requires a managed OIDC provider and states
> "we store no password hash"; this repo ships self-hosted password auth (`PyJWT` + `pwdlib[argon2]`).
> Gate 3 cannot be signed until the identity decision is closed. See
> [`decisions/D-003-identity-model.md`](decisions/D-003-identity-model.md).

---

## Gate 4: APIs

**Purpose.** Prove authorisation, input validation, tenant scoping, rate limits and the prescription
safety gate are enforced on **every** endpoint.

**When.** At the Phase 2 boundary for the TGA APIs, and again at the Phase 3 boundary for the
prescribing APIs.

**Entry criteria.** Every endpoint has a complete declaration (see the endpoint declaration standard in
[`definition-of-done.md`](definition-of-done.md#4-endpoint-declaration-standard)).

**Checks**

- [ ] Every endpoint declares authentication, permission, tenant scope, ownership rule, input schema,
      output schema, audit event, rate limit and error behaviour.
- [ ] Horizontal privilege escalation tests fail to access another user's resource at the same role.
- [ ] Vertical privilege escalation tests fail to reach a higher-privilege route.
- [ ] Cross-tenant access tests fail through every route, including nested resources and exports.
- [ ] Input validation rejects unknown fields and prevents mass assignment.
- [ ] Injection tests (SQL, command, template) pass.
- [ ] SSRF tests fail to reach an internal endpoint through a supplied URL.
- [ ] Rate-limit bypass tests fail, including distributed and header-spoofing attempts.
- [ ] Broken object-level authorisation tests fail to reach an object by changing its identifier.
- [ ] **The prescription safety gate blocks every negative case and no frontend or request field can
      bypass it.**
- [ ] Error responses use the standard envelope and leak no stack trace.

**Evidence.** The security test report for the five categories, the endpoint declaration inventory, the
negative dispatch matrix.

**Decision maker.** Security Lead. **Approver.** CTO, plus the Clinical Safety Officer for the safety gate.

**Failure path.** The gate fails; deployment stops. A failing authorisation or gate test is a **Critical**
finding until fixed.

**Conditional pass.** Available for a non-clinical endpoint with a documented compensating control, at
the CTO's discretion with the Security Lead. **❌ NOT AVAILABLE for the prescription safety gate.**

---

## Gate 5: Integrations

**Purpose.** Confirm every third-party data flow is documented, authenticated, bounded and reconciled,
and that **no integration can write clinical state without a human decision**.

**When.** At the Phase 2 boundary for the TGA ingestion boundary, and at the Phase 3 boundary for
Parchment and pharmacy dispatch.

**Entry criteria.** The adapter interface exists; credentials are in the secret store; a data-flow entry
exists for the provider.

**Checks**

- [ ] Every provider has a written data-flow record: what is sent, what is received, where it is
      processed, and who holds the credential.
- [ ] Provider credentials are per environment, stored in the secret store, with a named owner and a
      rotation procedure.
- [ ] Webhook signatures are verified; replay is rejected; events are deduplicated on the provider
      identifier.
- [ ] Every outbound write carries an idempotency key and duplicates are suppressed.
- [ ] Timeouts become explicit non-terminal states, and a reconciliation job resolves them.
- [ ] The provider-outage playbook names an owner and a clinical fallback.
- [ ] A sandbox integration test passes end to end.
- [ ] Vendor terms, region and sub-processor status are recorded in the vendor register.
- [ ] **TGA ingestion cannot write a gating state without a human verification.**

**Evidence.** Data-flow records, sandbox test report, vendor register entries, outage playbooks,
reconciliation test output.

**Decision maker.** Security Lead. **Approver.** CTO, plus the Compliance Lead for the vendor position.

**Failure path.** The gate fails; the integration is not enabled in production.

**Conditional pass.** Available for a provider whose data-flow record is complete but whose contractual
terms are still under review, marked **REQUIRES LEGAL/REGULATORY VALIDATION**, with an expiry and **no
production enablement**.

---

## Gate 6: Production

**Purpose.** Confirm the security testing programme is complete and the production environment meets the
design **before production holds real data**.

**When.** In Phase 4, after Phase 3, before the pilot release decision.

**Entry criteria.** Gates 1–5 passed for the pilot scope; the production environment exists; the CI
pipeline is green on the release commit.

**Checks**

- [ ] The five security test categories pass, with the named tests executed.
- [ ] SAST, dependency scan, container scan and secret scan are clean of **Critical** findings.
- [ ] The penetration test is complete, or booked with a date before go-live, and findings are tracked.
- [ ] Environment separation is verified: no production database, bucket, secret, key or credential is
      reachable from development.
- [ ] No production data was used in a non-production environment without approved de-identification.
- [ ] Backups run, and a **restore drill has been performed and timed** inside the agreed RPO and RTO.
- [ ] Monitoring and alerting cover the business signals and the security alerts.
- [ ] IAM has no long-lived access keys and no wildcard on sensitive actions.
- [ ] WAF rules and blocked-request logging are active.
- [ ] Database migration ordering follows expand-and-contract and the release is zero-downtime capable.

**Evidence.** Security test report, scan reports, environment separation checklist, restore drill record,
IAM review, WAF configuration export.

**Decision maker.** CTO. **Approver.** Security Lead, plus the Head of Platform.

**Failure path.** Production is not released. A Critical finding blocks the release outright.

**Conditional pass.** Available for a **High** finding with a documented compensating control, accepted by
CTO + Security Lead, with an expiry and a steering committee record. **❌ NOT available for any Critical
finding.**

---

## Gate 7: Go-Live

**Purpose.** Confirm the residual risk position is explicit, accepted by the right owner, and small
enough to start the pilot.

**When.** Immediately before the pilot clinic goes live, after Gate 6.

**Entry criteria.** Gate 6 passed; the M4 prerequisites are met; the clinic is trained.

**Checks**

- [ ] Open Critical findings and open High findings are **zero**.
- [ ] Every unresolved risk has documented acceptance by the appropriate owner, with a compensating
      control and an expiry.
- [ ] The privacy impact assessment, data-flow map, collection notices and retention schedule are in
      place.
- [ ] The vendor register and integration contracts name the credential owner and the outage playbook.
- [ ] The incident response runbook names **people, not roles**, and the notifiable-breach assessment
      path is understood.
- [ ] The clinic has practised its **manual fallback**.
- [ ] A named person is on call for the first two weeks of the pilot.
- [ ] The clinical safety hazard log is current and reviewed.
- [ ] The access-review baseline is recorded.
- [ ] Any item still marked **REQUIRES LEGAL/REGULATORY VALIDATION** has a documented interim position
      and an owner.

**Evidence.** Risk acceptance register, PIA, training record, on-call rota, hazard log, access baseline.

**Decision maker.** Practice Owner + CTO. **Approver.** Clinical Safety Officer + Compliance Lead.

**Failure path.** Go-live is delayed; the pilot does not start.

**Conditional pass.** Available only for a non-clinical, non-security item with a named acceptance by the
appropriate owner and a date. **Not available for an open Critical or High finding**, which by definition
fails this gate.

---

## Gate sign-off record template

```
GATE SIGN-OFF RECORD

  Gate number and name        : ................................................
  Date                        : ................................................
  Milestone                   : ................................................
  Scope of this pass          : ................................................
  Entry criteria met          : yes / no  (if no, the gate does not proceed)
  Checks performed            : .... of .... (list attached: yes / no)
  Evidence location           : ................................................
  Open Critical findings      : ....   (must be 0)
  Open High findings          : ....   (must be 0 or accepted)

  Decision                    : PASS / FAIL / CONDITIONAL PASS
  Conditional items           : ................................................
  Compensating control        : ................................................
  Conditional expiry          : ................................................
  Conditional granted by      : ................................................
  Approver (role, name)       : ........................................

  Delivered by (role, name)   : ................................................
  Decision maker (role, name) : ................................................
  Risk register references    : ................................................

  Dependent work released     : yes / no
  If no, what is stopped      : ................................................
```

---

## Control table

| Requirement | Source | Control | Implementation | Evidence | Owner | Status |
|---|---|---|---|---|---|---|
| Technical controls assessed before release | ACSC Essential Eight; internal policy | Seven gates with named approvers | This document | Signed gate records | Security Lead | Planned |
| No self-approval of a gate | Internal change control | Deliverer and approver are different roles | Sign-off template | Signed records | CTO | Planned |
| Tenant isolation is proven | Privacy Act 1988 (Cth); APPs | Gate 2 with no conditional pass | Isolation and pool-reuse tests | Test report | Security Lead | Planned |
| No dispatch without an active approval | TGA therapeutic goods framework; Authorised Prescriber pathway | Gate 4 safety-gate checks, no conditional pass | Negative dispatch matrix | Test report | Clinical Safety Officer | Planned |
| A Critical finding blocks deployment | Internal security baseline | Gate 6 and the CI severity threshold | Pipeline and release gate | Scan reports | Security Lead | Planned |
| Residual risk accepted by the right owner | Internal risk management | Gate 7 with documented acceptance | Risk acceptance register | Signed acceptances | Practice Owner | Planned |

## Open items and assumptions

| # | Item | Owner role |
|---|---|---|
| O1 | Confirm the penetration test booking date before Gate 6 | Security Lead |
| O2 | Confirm the RPO and RTO the restore drill is measured against | Practice Owner |
| O3 | Confirm the interim position for each `REQUIRES LEGAL/REGULATORY VALIDATION` item before Gate 7 | Compliance Lead |
| O4 | Confirm the on-call rota and named on-call person for the pilot | Head of Platform |
| O5 | Confirm the risk acceptance register format and storage | Compliance Lead |
| O6 | Confirm the approver when the named approver role is unfilled (single-person team) | Practice Owner |

## Sources

- `clinic-os-secure-by-design/26-security-gates.md` — Gates 1–7, conditional-pass rules, sign-off template
- `clinic-os-secure-by-design/23-sprint-plan.md` — gate timing at phase boundaries
- `clinic-os-secure-by-design/27-security-testing.md` — the named security tests
- Instruments named: Privacy Act 1988 (Cth) and the Australian Privacy Principles; Notifiable Data
  Breaches scheme; TGA therapeutic goods framework and the Authorised Prescriber pathway; ACSC Essential
  Eight.
