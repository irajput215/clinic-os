---
doc_id: OZ-FEAT-13-THREAT
title: "Integration boundaries — threat model"
owner: Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-13
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md §3–§9
  - clinic-os-secure-by-design/16-vendor-register.md §1–§3
  - clinic-os-secure-by-design/02-security-architecture.md §6, §11
  - clinic-os-secure-by-design/26-security-gates.md §6
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Threat model & residual risk register

## Risk assessment methodology (5×5 matrix)

$$\text{Risk Score} = \text{Likelihood (1--5)} \times \text{Impact (1--5)}$$

| Band | Range | Treatment |
| --- | --- | --- |
| **Low** | 1–4 | Acceptable; monitored via standard telemetry |
| **Medium** | 5–9 | Managed; requires automated CI test verification |
| **High** | 10–16 | Must be mitigated before pilot deployment |
| **Critical** | ≥17 | Catastrophic clinical/regulatory risk; blocks release outright |

## STRIDE assessment & residual risk matrix

| ID | STRIDE | Threat & attack path | Inherent risk | Control / mitigation | Residual risk | Owner | Source |
|---|---|---|---|---|---|---|---|
| **T-13.1** | **Elevation of Privilege** | **SSRF via a provider- or tenant-supplied URL:** an application defect or compromised dependency dereferences an attacker URL and reaches a private service or the metadata endpoint | High (4×4=16) | The platform never fetches a tenant-, patient- or provider-supplied URL; egress allow-listed at configuration time; private, loopback, link-local and metadata addresses refused before the request; metadata service restricted; S3 keys resolved server-side; the webhook handler never dereferences a payload URL | **Low (1×4=4)** | Security Lead | `10 §8; 26 §6` |
| **T-13.2** | **Information Disclosure** | **Credential theft from a task definition or image:** a secret in an environment variable, image layer, repository or backup is read by anyone with console, log or registry access | High (3×5=15) | Secrets Manager only, referenced by ARN in `integration_credentials_refs`; no secret in an env var, image or repo; task IAM roles and OIDC instead of long-lived keys; secret scan pre-commit and in CI fails the build | **Medium (1×5=5)** | Security Lead | `02 §6; 10 §4` |
| **T-13.3** | **Tampering** | **Provider writes clinical state without human verification:** an ingestion result or provider callback drives an approval to a gating state | High (3×5=15) | TGA ingestion lands `pending_verification`; no integration path can set `active`; verification is a separate permission and the verifier must differ from the creator; the safety gate consumes human-verified state only | **Medium (1×5=5)** | Clinical Safety Officer | `26 §6 Gate 5; 08 §3` |
| **T-13.4** | **Spoofing** | **Replay of a signed callback:** a captured valid webhook is re-sent to inject a second dispensing or payment event | High (4×4=16) | Signature verified over the raw body before parsing; signed timestamp within 5 minutes; unique `(provider, provider_event_id)` rejects a replay; a duplicate returns `200` with no state change | **Low (1×4=4)** | Security Lead | `10 §7` |
| **T-13.5** | **Denial of Service** | **Unbounded retry storm:** a failing provider is retried without limit, exhausting the pool and queuing threads behind a dead rail | High (3×4=12) | Maximum 4 attempts with full jitter and a 64 s cap; transient and idempotent operations only; circuit breaker per provider and operation; bulkhead pools; `429` respected with `Retry-After` | **Low (1×4=4)** | Head of Platform | `10 §4, §9; 02 §1 control 10` |
| **T-13.6** | **Repudiation** | **Silent timeout treated as success:** an unconfirmed dispatch is reported as sent, so a prescription may never have reached a pharmacy | High (3×5=15) | A timeout or unparsable body becomes `REQUIRES_RECONCILIATION`, never success or failure; audit `result = UNKNOWN`; the reconciliation job resolves by provider reference and idempotency key with `reason = RECONCILED`; unresolved rows escalate at 24 h | **Medium (1×5=5)** | Clinical Safety Officer | `09 §8; 21 §7` |
| **T-13.7** | **Spoofing** | **Stale credential after rotation:** an old secret remains valid after rotation, or rotation breaks the rail and invites a manual workaround | Medium (3×3=9) | Rotation with an overlap window and `status = ROTATING`; a superseded credential is refused and audited; rotation is rehearsed in Staging before Production; a suspected exposure is an incident, not a cleanup | **Low (1×3=3)** | Security Lead | `02 §6 rule 4; 29 §8.2` |
| **T-13.8** | **Information Disclosure** | **Sub-processor receives PHI outside the approved region:** an unlogged onward flow or a new sub-processor moves health information offshore | High (3×4=12) | Residency five-condition test before the first byte; minimum-data rule with a payload allow-list test; vendor onboarding gate requires an executed agreement and a sub-processor list; no row in the residency register is `OFFSHORE-APPROVED`; an unapproved flow cannot be enabled | **Medium (2×4=8)** — contractual and residency positions unconfirmed | Privacy Officer | `13 §3; 16 §1.1, §3` — **REQUIRES LEGAL/REGULATORY VALIDATION** |
| **T-13.9** | **Elevation of Privilege** | **Payload-based tenant wrong-tenant routing:** a valid signature naming tenant B is sent to a path that implies tenant A, and the path is trusted | High (3×4=12) | The endpoint is provider-scoped, not tenant-scoped; tenant is resolved from the verified payload's merchant or organisation reference, never a path parameter or header; a payload mapping to no tenant is quarantined `202` and alerted | **Low (1×4=4)** | Security Lead | `10 §7` |
| **T-13.10** | **Information Disclosure** | **PHI leak into integration logs:** a prescription payload, medicine name or patient identifier is serialised into a log, trace or crash report | High (4×3=12) | The log record is built from an allow-listed field set, never by serialising the request or response; the body is never a log argument at any level; a sentinel scan asserts absence and fails the build | **Low (2×2=4)** | Privacy Officer | `10 §4; 12 §3` |
| **T-13.11** | **Tampering** | **Mass assignment or unknown field on an inbound payload:** a provider change or attacker adds a field that is silently interpreted | Medium (3×3=9) | Strict inbound schema, unknown fields rejected; `application/json` only; 256 KB body cap with `413`; response never echoes the payload | **Low (1×3=3)** | Head of Platform | `10 §4, §7; 21 §7` |
| **T-13.12** | **Elevation of Privilege** | **Cross-tenant credential use:** a compromised per-tenant credential authorises an action for another tenant | High (3×4=12) | Per-tenant credentials in Secrets Manager; unique `(tenant_id, provider_code)`; RLS with `NULLIF` fail-closed; cross-tenant access returns `404` | **Low (1×4=4)** | Security Lead | `10 §6; 05 §5.3` |
| **T-13.13** | **Tampering** | **Duplicate dispatch from a retry without an idempotency key:** a repeated call creates a second prescription event | High (3×4=12) | The adapter refuses to construct a request without a key and refuses a key that does not match its attempt row; `UNIQUE (tenant_id, idempotency_key)`; a retry returns the recorded outcome | **Low (1×4=4)** | CTO | `10 §4, §5; 09 §7` |
| **T-13.14** | **Tampering** | **Stale or out-of-order provider event regresses a terminal state** | Medium (3×3=9) | The handler compares the provider sequence or timestamp, does not regress a terminal state, records the event, and alerts if the stale transition repeats | **Low (1×3=3)** | Head of Platform | `10 §9` |
| **T-13.15** | **Elevation of Privilege** | **Environment crossover:** a Production credential, queue or bucket is reachable from Development | High (3×4=12) | Separate credentials, queues and buckets per environment; no shared provider account where separation is supported; a configuration assertion proves no shared secret, bucket or queue | **Low (1×4=4)** | CTO | `10 §4; 26 §6` |
| **T-13.16** | **Elevation of Privilege** | **Shadow integration:** an unregistered provider is called and bypasses the register, vendor and residency obligations | Medium (2×4=8) | A register-completeness config check fails CI when a provider lacks rows; egress allow-lists only registered endpoints; a call to an unregistered destination fails at the network layer | **Low (1×4=4)** | Head of Platform | `10 §2, §8; 26 §6` |

## Assumptions

- Single database, modular monolith, RLS enabled and forced; the application role is not the table owner.
- Every provider is untrusted, including one under contract or on a private link.
- The platform is a network client and a webhook receiver only; it hosts no provider component and never
  accepts an inbound clinical query from a provider (`10`, assumption).
- Rate limits, timeouts, breaker and retry numbers are engineering defaults until a contract overrides
  them; an override is recorded in adapter configuration with the contract reference.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Whether request signing is supported by each provider, and the exact scheme (`10` Open item 2) | Head of Integrations | OPEN |
| Provider residency and support-access locations — T-13.8 cannot drop below Medium until confirmed | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether any provider requires an interface agreement or conformance register entry not yet in place | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| The exact retry and circuit-breaker settings, once published provider limits are known | Head of Integrations | OPEN |
| `webhook_events.tenant_id NOT NULL` cannot represent quarantine without a resolution (`03-design.md` open item) | Security Lead | OPEN |
