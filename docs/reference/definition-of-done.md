---
doc_id: OZ-REF-DOD
title: Definition of Done, Definition of Ready and the endpoint declaration standard
owner: Delivery Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
source: ../../clinic-os-secure-by-design/24-definition-of-done.md
---

# Definition of Done

The Definition of Done is the **six-part test a feature must pass before it is Done**. It is a checklist
a reviewer uses, not a statement of intent.

- Use it at the **start** of a story, not the end — most items change how the story is built.
- The reviewer is a **role, not the author** of the change.
- Evidence is an **artefact**: a test result, a log line, a scan report, a signed note.
- If an item does not apply, **write why** on the story. An unjustified blank is a failed check.

---

## 1. The six-part test

### Part 1 — Functional

- [ ] The feature works as stated in the acceptance criteria, **including every negative case**.
- [ ] Unit tests pass and cover the domain invariants the feature introduces.
- [ ] Integration tests pass against a **real PostgreSQL instance with RLS enabled**.
- [ ] Acceptance criteria are traceable to a requirement ID.
- [ ] Error paths return the standard error envelope and do not leak a stack trace.

### Part 2 — Security

- [ ] Authentication implemented: the endpoint requires the identity it should, and an unauthenticated
      request is refused.
- [ ] Authorisation implemented: the required permission is checked in the **central policy layer**, not
      in a route handler branch.
- [ ] Tenant isolation verified: read and write paths carry tenant context, and the isolation test
      asserts **absence**.
- [ ] Input validation implemented: a strict Pydantic schema rejects unknown fields, and mass assignment
      is not possible.
- [ ] Resource ownership evaluated server-side; the frontend never enforces a decision.
- [ ] Security tests pass for this feature, drawn from the catalogue in
      `clinic-os-secure-by-design/27-security-testing.md` (external source contract).
- [ ] Secrets protected: no secret in source, image, database, log or client bundle; credentials come
      from the secret store.
- [ ] Rate limits and request size limits apply to the route.
- [ ] The step-up requirement is enforced for a high-risk operation.

### Part 3 — Audit

- [ ] Required events logged with the full envelope:
      `event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result,
      reason, source_ip, request_id, correlation_id`.
- [ ] Audit records immutable: written **in the same transaction** as the change, with no `UPDATE` or
      `DELETE` grant.
- [ ] Sensitive payloads excluded: no clinical content, secret, token or full clinical request body.
- [ ] **Denied and failed attempts are audited**, not only successes.
- [ ] A failure to write an audit event for an audited operation **fails the operation**.

### Part 4 — Operations

- [ ] Structured logs with request id, tenant id, service, route, action, latency and error class, and
      **no clinical content**.
- [ ] Metrics exposed for the route: latency, error rate and any business signal the feature produces.
- [ ] Errors observable: a failure produces a distinguishable log and metric, not a silent catch.
- [ ] Alerts defined where necessary, with a threshold, a runbook link and a named owner.
- [ ] The feature degrades in a stated way when a dependency fails, and a timeout becomes an explicit
      state.
- [ ] A dashboard panel shows the feature's health.

### Part 5 — Compliance

- [ ] The applicable requirement is identified **by instrument**, not by assumption.
- [ ] The control is documented in [`control-matrix.md`](control-matrix.md).
- [ ] Evidence is produced as an artefact an auditor would be shown.
- [ ] Open assumptions are documented and marked **REQUIRES LEGAL/REGULATORY VALIDATION**, with an owner.
- [ ] No compliance claim is made beyond what the evidence shows.

### Part 6 — Deployment

- [ ] The container image builds with a multi-stage build, minimal base image, non-root user and pinned
      dependencies.
- [ ] Container, dependency and secret scans pass.
- [ ] The CI pipeline passes in the fixed order:
      `lint → typecheck → unit → integration → security tests → SAST → dependency scan → container scan →
      secret scan → build → deploy`.
- [ ] The migration is backward compatible and follows expand-and-contract.
- [ ] The change is deployed to **Staging and verified there** before any production release.
- [ ] The rollback or forward-fix path is stated.

### Part 7 — Clinical (where applicable)

- [ ] Clinical acceptance by a practising prescriber for any clinical behaviour change.
- [ ] The **Clinical Safety Officer sign-off cannot be waived.**

---

## 2. Artefacts and reviewers

| Part | Artefact produced | Reviewer role |
|---|---|---|
| Functional | Passing unit and integration test output, acceptance criteria mapping | Head of Product |
| Security | Isolation test output, authorisation test output, security test results, secret scan report | Security Lead |
| Audit | Sample event with full envelope, `audit_log` grant listing, audit coverage test output | Security Lead |
| Operations | Log sample, metric and dashboard reference, alert definition, runbook link | Head of Platform |
| Compliance | Requirement-to-control mapping, evidence artefact, assumptions list | Compliance Lead |
| Deployment | CI pipeline run record, image scan report, dependency scan report, migration review | Head of Platform |
| Clinical | Clinical acceptance for a clinical behaviour change | Clinical Safety Officer |

---

## 3. The High and Critical rule

**No feature is Done with an open High or Critical security finding.** This applies whether the finding
came from a scanner, code review, security test or penetration test.

A finding may be closed by fixing it or by a formally accepted risk under section 5. A scanner finding
may **not** be closed by suppression without a recorded justification and an expiry date. A **Critical**
finding also blocks deployment.

```
 open Critical or High finding?
      │
      ├── yes ──> NOT DONE
      │             ├── fix, or
      │             └── accepted risk with named approver, expiry and compensating control
      │
      └── no ───> all six parts signed?
                    ├── yes ──> DONE
                    └── no ───> NOT DONE
```

---

## 4. Endpoint declaration standard

Every endpoint declares **all** of the following. An endpoint without a complete declaration is not
reviewable and does not enter a sprint review.

| Declaration | Meaning here |
|---|---|
| Authentication required | `Yes` / `No`. `No` is permitted for exactly two surfaces, and nothing else: the **public intake surface** and the **platform liveness/readiness probes** — except for `POST` webhook ingress, which is unauthenticated by nature and is instead **signature-verified** (see the cross-cutting rules below). The intake surface still enforces rate limits and input validation; the probes expose no tenant data and no more than a boolean status, and are never routed through the application's tenant-resolution path |
| Required permission | The granular permission checked by the central policy layer |
| Tenant scope | How the tenant is resolved: session, resource, or both |
| Resource ownership rule | The condition under which this actor may act on this resource |
| Input schema | Pydantic model in `schemas.py`; unknown fields rejected |
| Output schema | Pydantic model; sensitive fields excluded per role |
| Audit requirement | The event action emitted, or `none` with a justification |
| Rate limit | Per identity, per tenant and per route |
| Error behaviour | The error codes this endpoint can return, and whether it fails closed |

Use this block verbatim in the phase `spec.md` for each route:

```markdown
#### `METHOD /path`
- Authentication: Yes | No
- Permission: `<permission>`
- Tenant scope: session | resource | both
- Ownership rule: <condition>
- Input schema: `<Module><Thing>Create`
- Output schema: `<Module><Thing>Read`
- Audit: `<EVENT_NAME>` | none — <justification>
- Rate limit: <n>/min per <key>
- Errors: `403`, `404`, `409`, `422`, `429`; fails closed = yes
- Step-up: yes | no
```

### Cross-cutting API rules

- **Error envelope:** every error response uses one shape —
  `{"error": {"code": "...", "message": "...", "request_id": "...", "details": [...]}}`. Codes are stable
  and machine-readable. A message never includes clinical content, a secret or a stack trace. Denials
  return `403` with a reason class, **never `404` where existence would leak** — and conversely, `404`
  rather than `403` where returning `403` would confirm existence across a tenant boundary.
- **Pagination:** cursor-based for every list. `limit` bounded by a server maximum. Cursors opaque and
  signed; a cursor cannot be replayed across tenants.
- **Idempotency:** every client-initiated write accepts an `Idempotency-Key`, stored with the tenant and
  route under a unique constraint; a retry returns the original result.
- **Rate limits:** applied at the edge and in the application. A breach returns `429` with `Retry-After`
  and is logged.
- **Request size limits:** a global maximum, a smaller maximum on clinical write routes, and a separate
  documented maximum for document upload with MIME and content validation.
- **Timeouts:** a request timeout, a database statement timeout, an outbound integration timeout with a
  circuit breaker, and a queue visibility timeout exceeding expected job duration. **A timeout on an
  external write becomes an explicit non-terminal state, never success or failure.**

---

## 5. Exception process

An exception is a deviation from process, an accepted risk, or a deferral of a non-security item. It is
recorded, time-boxed and owned. **An exception without an expiry is invalid.**

| Exception | Approver | Conditions |
|---|---|---|
| Defer an Operations or Compliance item to the next phase | Delivery Lead + Compliance Lead | Evidence gap named, date set, reported at the phase review |
| Accept an open High security finding | CTO + Security Lead | Compensating control recorded, expiry date, risk register entry |
| Accept an open Critical security finding | Practice Owner + CTO | Only for a production incident decision, **never for a feature release**; expiry and incident reference required |
| Deviate from the CI pipeline order | Security Lead + Head of Platform | Never for a missing security stage; only for an infrastructure failure, with a manual equivalent recorded |
| Ship without clinical sign-off where clinical behaviour changed | **Not permitted** | The Clinical Safety Officer sign-off cannot be waived |
| Change the tenant isolation model | **Not an exception** | Requires a decision record and a Gate 2 re-run |

Every exception records: what was deferred, why, the compensating control, the owner, the expiry date and
the approval.

---

## 6. Definition of Ready (companion gate)

A story is ready to enter a phase when:

- The persona, outcome and acceptance criteria are written, **including at least one negative case**.
- The security requirements name the permission, the tenant scope and the ownership rule.
- The audit requirements name the events, or justify `none`.
- The endpoint declaration above is complete.
- Dependencies are available or stubbed with a named owner.
- Test data is **synthetic and classified**.
- The story is estimated by the team that will build it.
- The reviewer roles for the six parts are identified.

The Definition of Ready stops an unready story entering a phase in the first place.

---

## 7. Which parts apply to which change type

| Change type | Functional | Security | Audit | Operations | Compliance | Deployment |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| New API endpoint | Yes | Yes | Yes | Yes | If it touches a regulated field | Yes |
| Change to an existing endpoint | Yes | Yes | If the event or resource changes | Yes | If classification changes | Yes |
| Frontend-only change | Yes | If it shows, hides or labels a decision | If it reads a record | Yes | No | Yes |
| Database migration | Yes | Yes | If audit columns or grants change | Yes | If retention or residency changes | Yes |
| Integration adapter change | Yes | Yes | Yes | Yes | Yes, including the vendor register | Yes |
| Clinical behaviour change | Yes | Yes | Yes | Yes | Yes | Yes, plus CSO sign-off |
| Configuration or feature flag change | Yes | Yes | Yes | Yes | If it alters a control | Yes |
| Documentation-only change | No | No | No | No | Yes | No |

A frontend-only change still passes through Security where it touches a decision the backend owns,
because the frontend must never be the enforcement point.

---

## 8. Evidence storage

- The completed checklist lives in the pull request and is linked from the story.
- Test output, scan reports and pipeline runs are retained by CI and referenced by run identifier.
- Gate evidence is copied into the milestone evidence bundle, so a milestone can be reviewed without
  reconstructing CI history.
- Evidence retention follows the retention schedule owned by the Compliance Lead, and evidence is not
  deleted while a gate or an incident is open.
- **An artefact that does not link to the control it proves is not evidence.**

---

## 9. What Done is not

- Done is **not** "the demo worked". A demo shows the happy path; the checklist requires negative cases.
- Done is **not** "the tests pass" on their own. Security, audit, operations, compliance and deployment
  each produce their own evidence.
- Done is **not** "the ticket is closed" or "the code is merged". A merged change with an open High
  finding is not Done.
- Done is **not** "security will pick it up later". There is no later step that adds the missing control.
- Done is **not** "it works on my machine". The change is verified in Staging before it is complete.

---

## 10. Scope of Done

| Scope | What Done means |
|---|---|
| Story | The six parts pass, and the pull request records the checklist |
| Phase | Every committed story is Done or explicitly de-scoped, and the gate evidence is produced |
| Milestone | The milestone exit gate is signed |
| Release to production | Gates 6 and 7 signed, open Critical and High findings zero or accepted, restore drill current |
| Documentation | The relevant document in this set is updated; a substantive architecture change is a decision record |

---

## Control table

| Requirement | Source | Control | Implementation | Evidence | Owner | Status |
|---|---|---|---|---|---|---|
| Every feature carries a security review | ACSC Essential Eight; internal policy | Six-part checklist with a named reviewer | Pull request template | Signed checklist | Security Lead | Planned |
| No release with an open Critical finding | Internal security baseline | Severity threshold blocks deployment | CI pipeline and release gate | Pipeline record | Security Lead | Planned |
| Audit completeness | Privacy Act 1988 (Cth); state and territory health records legislation | Required events in the same transaction | Audit coverage test | Coverage test output | Compliance Lead | Planned |
| Evidence produced for each control | Internal evidence discipline | Artefact per checklist line | Evidence bundle | Evidence bundle | Compliance Lead | Planned |
| Exceptions recorded and expiring | Internal change control | Exception register with approvers and expiry | Section 5 | Exception register | Delivery Lead | Planned |
| Clinical behaviour changes require clinical acceptance | Clinical governance | Clinical Safety Officer sign-off | Review record | Sign-off | Clinical Safety Officer | Planned |

## Open items and assumptions

| # | Item | Owner role |
|---|---|---|
| O1 | Confirm the pull request template embeds the six-part checklist | Delivery Lead |
| O2 | Confirm the exception register location and review cadence | Compliance Lead |
| O3 | Confirm the compensating-control standard for accepted High findings | Security Lead |
| O4 | Confirm who signs clinical acceptance when the Clinical Safety Officer is unavailable | Clinical Safety Officer |
| O5 | Confirm the evidence bundle retention period | Compliance Lead |

## Sources

- `clinic-os-secure-by-design/24-definition-of-done.md` — the six-part test, exception process, DoR
- `clinic-os-secure-by-design/21-technical-design.md` §7 — API design standard and endpoint declarations
- `clinic-os-secure-by-design/27-security-testing.md` — the security test catalogue
- Instruments named: Privacy Act 1988 (Cth) and the Australian Privacy Principles; state and territory
  health records legislation; ACSC Essential Eight.
