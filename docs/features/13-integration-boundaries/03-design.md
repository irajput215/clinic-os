---
doc_id: OZ-FEAT-13-DESIGN
title: "Integration boundaries — design"
owner: Head of Platform + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-13
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md §1–§9
  - clinic-os-secure-by-design/16-vendor-register.md §1–§3
  - clinic-os-secure-by-design/04-database-erd.md §3.12
  - clinic-os-secure-by-design/21-technical-design.md §5, §7
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

## The five-step sequence

Every outbound call that changes clinical or financial state runs in this order; **reversing it is a defect.**

```text
1. Internal validation   schema, state, grain, idempotency, bounds
2. Security check        session, permission, step-up, care relationship, tenant match
3. Domain check          e.g. TGA approval ACTIVE at the grain, window covers the dispatch instant
4. Audit write           commit the intent and the event together, BEFORE the external call
5. External call         adapter with timeout, retry and circuit breaker
```

The audit write precedes the external call, so **a call that never returns must still have a committed
audit event for reconciliation to find** (`10` §1; `07` §5).

## Integration register

Every third party is registered here **and** in the residency register (`13` §3) and the vendor register
(`16` §2). A rail is not enabled without a row. Columns are the Gate 5 data-flow record.

| Provider (`provider_code`) | Direction | What is sent | What is received | Where processed | Credential owner | Region | Sub-processor |
|---|---|---|---|---|---|---|---|
| `parchment` | Outbound request, inbound webhook | Prescription payload in the rail schema, prescriber identifier, patient identifiers as the rail requires, approval reference | Acceptance, rejection, provider reference, status events | To confirm; Australian health rail (`13` DR-04, DR-05) | Compliance/Auditor (`16` V-03) | Australian rail; processing location **UNKNOWN** | List not sighted — **REQUIRES LEGAL/REGULATORY VALIDATION** |
| `tga_mailbox` | Inbound only | None | Approval letters, attachments, correspondence metadata | Mailbox provider; attachments processed `ap-southeast-2` (`13` DR-06) | Compliance/Auditor (`16` V-04) | Australian Government channel | Government channel; terms not sighted |
| `tyro` | Outbound request, inbound webhook | Invoice amount, currency, invoice reference, tenant merchant reference, callback URL | Authorisation, settlement, refund result | To confirm; Australian acquirer (`13` DR-08) | Compliance/Auditor (`16` V-05) | Likely onshore, **UNKNOWN** | List not sighted — **REQUIRES LEGAL/REGULATORY VALIDATION** |
| `oidc_idp` | Outbound authorisation, inbound token and JWKS | User identifier, redirect URI, nonce, PKCE challenge; no patient information | ID token, access token, refresh token, group claims, revocation events | To confirm; may be multi-region (`13` DR-09) | Security Lead (`16` V-02) | **UNKNOWN** | List not sighted — **REQUIRES LEGAL/REGULATORY VALIDATION** |
| `notifications` | Outbound only | Recipient address or number, template identifier, delivery correlation ID | Delivery receipt, bounce, complaint | To confirm (`13` DR-10) | Privacy Officer (`16` V-06) | Australian where available; otherwise flagged | List not sighted — **REQUIRES LEGAL/REGULATORY VALIDATION** |

Terms, residency position and sub-processor list are **REQUIRES LEGAL/REGULATORY VALIDATION**; this document does not assert that any provider is compliant.

## Adapter contract

| Element | Contract |
|---|---|
| Interface and isolation | One interface per provider; no module imports a provider client directly; a provider has no method that accepts a list (no bulk send). Re-expressed from `call(request, idempotencyKey) -> result \| explicit-unknown \| error` as `dispatch(request, idempotency_key, deadline) -> Confirmed \| Rejected \| ExplicitUnknown \| AdapterError` |
| Credentials | Per environment and per tenant where issued; loaded from Secrets Manager by ARN at task start, with a named owner and a rotation procedure; never an environment variable, image layer or repository file |
| Timeout | Connect/read per provider; overall deadline 20 s user-facing, 60 s background. Defaults: Parchment 3/15 s, Tyro 3/10 s, identity provider 2/5 s, notifications 3/10 s, TGA mailbox 10/30 s. A contract limit overrides the default and the override is recorded in adapter configuration with the contract reference |
| Retry and idempotency | ≤4 attempts, full jitter (1 s, 4 s, 16 s, 64 s cap), transient and idempotent operations only; the key is sent on every attempt and request construction is refused without one |
| Circuit breaker and bulkhead | Per provider and operation; opens at 10 failures/30 s or 50% over 20 calls, 30 s open, 3-request half-open probe; separate connection pool and worker concurrency per provider |
| Logging and redaction | Built from an allow-listed field set — correlation ID, provider, operation, outcome class, latency, error class. **Clinical content redacted**; request and response bodies are never log arguments |
| Provider events and health | Extract the provider event identifier for webhook dedupe; expose adapter health for the administrator UI |
| CI driver | A simulated driver implements the same interface, records every call, and returns scripted `Confirmed`, `Rejected`, `ExplicitUnknown`, timeout, 5xx and malformed-body outcomes. No test imports the real client |

## Timeout semantics

**An unknown outcome becomes an explicit non-terminal state, never success or failure.**

| Provider outcome | State | Audit |
|---|---|---|
| 2xx confirmed | `DISPATCHED` / `CONFIRMED` | `prescription.dispatch`, `result = SUCCESS` |
| 4xx rejected | `FAILED`, not retried | `prescription.dispatch_failed`, `result = FAILED` |
| 5xx after retries | `FAILED` | `prescription.dispatch_failed`, `result = FAILED` |
| Timeout / no response | **`REQUIRES_RECONCILIATION`** | `prescription.dispatch_failed`, `result = UNKNOWN` |
| Malformed or unparseable body | **`REQUIRES_RECONCILIATION`** — unknown, not failure | `prescription.dispatch_failed`, `result = UNKNOWN` |
| Connection refused | `FAILED`; the breaker may open | `prescription.dispatch_failed`, `result = FAILED` |
| `429` | Respect `Retry-After`; pause the tenant's queue | `integration.request`, `outcome = THROTTLED` |

The reconciliation job runs every 5 minutes, resolves in both directions by provider reference and
idempotency key, writes `reason = RECONCILED`, and escalates anything unresolved after 24 hours
(`10` §5; `09` §8).

## SSRF protections (`10` §8, in full)

- The platform **never fetches a URL supplied by a tenant, a patient or a provider payload**; a tenant callback URL is allow-listed by hostname at **configuration time**, not request time.
- Egress security groups permit only registered provider endpoints; a call to an unregistered destination fails at the network layer.
- DNS goes through the VPC resolver; a **private, loopback, link-local or metadata** address is refused **before the request is made**.
- The instance metadata service is disabled or restricted to the task role.
- Document retrieval resolves **S3 object keys server-side from the database**; a key from a request body is never dereferenced.
- The webhook handler **never dereferences a URL contained in a webhook payload**.

## Database privileges

The application connects as non-owner role `clinos_app`. The credential-reference table stores an
**ARN, never a secret value** (`04` §3.12; `02` §6 rule 2).

```sql
-- integration_credentials_refs: reference only; no column holds credential material
GRANT SELECT, INSERT, UPDATE ON integration_credentials_refs TO clinos_app;
REVOKE DELETE, TRUNCATE ON integration_credentials_refs FROM clinos_app;

-- webhook_events: append-only; dedupe key is (provider, provider_event_id)
GRANT SELECT, INSERT ON webhook_events TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON webhook_events FROM clinos_app;
```

Hard delete of a credential reference happens only through the offboarding path, after rotation, by a privileged role (`04` §3.12; `16` §5). A secret value found in a column, image, log or bundle is a build failure (secret scan).

## RLS

- `ENABLE` and `FORCE ROW LEVEL SECURITY` on `integration_credentials_refs` and `webhook_events`.
- Policy: `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` — an unset tenant matches **nothing** instead of raising a cast error.
- Tenant is set with `SET LOCAL` inside each transaction, never per pooled connection; the app role is not the table owner and has no `BYPASSRLS` (`05` §5.3, §6).

## Deny-by-default request path

Outbound (`10` §1): (1) authenticate; (2) resolve tenant and `SET LOCAL`; (3) check the granular
permission in the central policy layer; (4) check resource ownership, care relationship and tenant match;
(5) validate against a strict schema, rejecting unknown fields and out-of-bounds values; (6) match the
server-derived idempotency key against its attempt row; (7) run the domain check (TGA approval at the
grain, at `date_of_service`); (8) **commit the audit intent event, then call** — an audit failure fails
the operation.

Inbound webhook (`10` §7): body ≤256 KB and `application/json`; signature verified over the raw body
before parsing; timestamp within 5 minutes; strict schema; tenant from the verified payload, never a path
or header; dedupe on `(provider, provider_event_id)`; state change and audit commit before `200`. An
unverified webhook is dropped with `401`, counted, and alerted on above the burst threshold. A payload
that maps to no tenant is quarantined with `202`.

## Failure behaviour

No call is reported as done that is not confirmed, and nothing is silently lost (`10` §9). Denied and
failed attempts are audited at the same fidelity as successes. Cross-tenant access returns `404`, never
`403`. Errors use the standard envelope and carry no clinical content, secret or stack trace. When a rail
is unavailable the clinic is told so and the manual fallback applies; an identity-provider outage refuses
new logins with `503` and never falls back to a local credential path.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| `webhook_events.tenant_id NOT NULL` cannot express a payload mapping to no tenant, yet `10` §7 requires quarantine (`202`) | Security Lead | OPEN — system tenant or platform-scoped quarantine table |
| Webhook path `/webhooks/:provider` vs `/pharmacy/webhooks/*` (`02` §11) | Head of Platform | OPEN |
| `secret_arn` is classed `SECRET` in `04` §3.12 but `12` §5.1 rule 1 classes a pointer `CONFIDENTIAL` | Privacy Officer | OPEN — this doc applies the stricter label |
| The queue broker is OPEN under D-004; the queue port must not leak the broker type | CTO + Head of Platform | OPEN |
