# D-012: Parchment is reached through the existing dispatch outbox, as one `DispatchTransport` adapter

- **Status:** **Proposed** for the mechanism · 🔴 **OPEN — requires a decision** for the vendor contract, credentials and payload
- **Date:** 2026-11-17
- **Owner:** CTO (mechanism) · Compliance Lead (conformance split) · Privacy Officer (payload) · Security Lead (credentials, webhook) · Clinical Safety Officer (outage fallback)
- **Source contract reference:** `clinic-os-secure-by-design/25-adr/ADR-010-parchment-integration.md`; `10-integration-boundaries.md`. Repo: [FEAT-11](../../features/11-prescribing/01-requirements.md), [FEAT-12](../../features/12-pharmacy-dispatch/01-requirements.md), [FEAT-13](../../features/13-integration-boundaries/03-design.md), `docs3/decisions-needed.md` D7e

## Context

The goal: a signed prescription that has passed the safety gate becomes an Australian electronic
prescription, and the patient receives an **eScript token** (the QR code / link a pharmacy dispenses
from). Parchment is the intended eRx provider.

**What exists today (2026-11-17):**

| Built | Where |
|---|---|
| Prescriptions: draft, safety gate, sign with step-up, edit, cancel, addendum | `backend/app/modules/prescriptions/{service,gate}.py`, [D-010](D-010-prescription-corrections.md) |
| Prescriber readiness gate on signing (AHPRA, prescriber number, agreement, SOPs) | `backend/app/modules/users_roles/onboarding.py` |
| Dispatch outbox: claim `FOR UPDATE SKIP LOCKED`, idempotency key, reconciliation of `REQUIRES_RECONCILIATION` | `backend/app/modules/prescriptions/outbox.py` |
| The transport interface and outcome types (`Confirmed`, `Rejected`, `ExplicitUnknown`, `NotSent`) | `backend/app/modules/prescriptions/transport.py` |
| Practitioner identifier types including HPI-I and eRx ID | `backend/app/modules/users_roles/models.py` |

**Not built:** any transport. `configured_transport()` returns `None` unconditionally, so every
dispatched prescription stays `QUEUED` and the UI says "Queued in ClinicOS. Not sent". There is no
inbound webhook receiver, no `webhook_events` table, no eScript token field, no patient-facing token
delivery, and no HPI-O.

We have **not seen Parchment's API documentation or contract.** Nothing below names a Parchment
endpoint, field or auth scheme; those are filled in from the sandbox docs (open item 1).

## Decision

### 1. One adapter, behind the interface that already exists

`backend/app/modules/prescriptions/transports/parchment.py` implements `DispatchTransport`:

- `send(request, idempotency_key, deadline_seconds)` creates the electronic prescription and returns
  `Confirmed(provider_reference)`, `Rejected(error_class)` on a definitive 4xx, `ExplicitUnknown` on a
  timeout or unparsable body, `NotSent` only when the request provably never left.
- `lookup(idempotency_key, provider_reference)` is the reconciliation read used by the existing drain.
- Timeouts from FEAT-13: connect 3 s, read 15 s, overall 20 s user-facing / 60 s background. At most 4
  attempts, full jitter, transient failures only, the same idempotency key on every attempt. A circuit
  breaker and a bulkhead per provider.
- No bulk method. No other module imports the Parchment client.

`configured_transport()` returns this adapter only when **all** of: the environment is allowed to use
it (production and staging point at different Parchment environments), its credential reference
resolves from the secret store, and the provider host is on the egress allow-list. There is still no
setting that points the outbox at an arbitrary URL.

A `SimulatedParchment` driver with scripted outcomes (confirmed, rejected, unknown, timeout, 5xx,
malformed) is the only transport tests use. No test imports the real client.

### 2. The token is a provider result, stored and delivered under the same controls

- On `Confirmed`, the provider reference and the eScript token reference are written to the dispatch
  attempt in the same transaction as the state change and the audit event.
- The token is `HIGHLY_SENSITIVE`: never logged, never in a URL, never in an error body.
- Who delivers the token to the patient (Parchment by SMS/email, or ClinicOS) is decided with the
  contract. If ClinicOS delivers it, that uses the notification provider (D7a), which is its own data
  flow.

### 3. Minimum-data payload

The request is built from the signed prescription row through an explicit field allow-list, not by
serialising the model. Expected content, to be confirmed against the rail schema: prescriber (name,
HPI-I, prescriber number, practice address, HPI-O), patient (name, DOB, IHI, address, Medicare where
required), medicine, form, strength, dose instruction, quantity, repeats, date, and the TGA approval
reference. Any field the rail does not require is not sent (FEAT-13 R19). The allow-list is a
Privacy Officer decision, recorded with the adapter.

### 4. Inbound webhook

Asynchronous status (accepted, dispensed, cancelled) arrives at a signed receiver built to FEAT-12
R1–R17: signature over the raw body before parsing, 5-minute replay window, dedupe on
`(provider, provider_event_id)`, tenant routed from the verified payload, no regression of a terminal
state, `200` only after commit, quarantine (`202`) for a payload that maps to no tenant. Per
[D-005](D-005-route-path-convention.md) this is the one route outside `/api/v1`.

### 5. What has to be true before the first live script

1. Parchment sandbox access, API docs and a support path (ADR-010 F1).
2. The conformance responsibility split with the certified party (F3): REQUIRES LEGAL/REGULATORY VALIDATION.
3. A credential owner and rotation procedure; the credential in the secret store, referenced per
   environment, never in `.env` or source (F4).
4. Residency and sub-processor positions on the vendor register (V-03, DR-04).
5. The payload allow-list signed off.
6. The webhook receiver and the reconciliation schedule live (F2).
7. A written outage playbook with the clinical fallback, agreed with the pilot clinic (F5).
8. Patient record holds what an eScript needs: verified IHI and a structured address (`docs3/gap-analysis.md` item 5). HPI-O added to the clinic.

### 6. Build order

| Step | Content | Depends on |
|---|---|---|
| 1 | `SimulatedParchment` driver and adapter skeleton against the interface; tests for every outcome | Nothing |
| 2 | Payload builder with an explicit allow-list (draft), tests that nothing outside it is sent | Rail schema from the sandbox docs |
| 3 | Real HTTP client in the adapter, sandbox only | Item 1, item 3 |
| 4 | Webhook receiver, `webhook_events` table, reconciliation schedule | Schema approval; item 6 |
| 5 | Token storage and display; patient delivery | Contract decision on who delivers |
| 6 | Production enablement | Items 1–8, Gate 5 sign-off |

**Progress (2026-11-21):** steps 1 and 2 are built in
`backend/app/modules/prescriptions/transports/`, tested in `backend/tests/prescriptions/test_parchment.py`:

- `resilience.py`: deadline, at most 4 attempts with full jitter for a `NotSent` that is transient
  only, circuit breaker, bulkhead. An unknown outcome is never retried; reconciliation resolves it.
- `parchment.py`: the adapter, the DRAFT payload allow-list (`PAYLOAD_FIELDS`, pinned by a test), the
  mapping of every provider answer to the outbox's four outcomes, and `SimulatedParchmentWire`.
- `identities.py`: patient (IHI, sex, address, Medicare), prescriber (an `ACTIVE`, unexpired HPI-I and
  prescriber number) and the approval reference, read through each module's facade. Anything missing
  is refused before a payload is built.

The real HTTP wire is **not** written: Parchment's documentation could not be reached from the build
environment and no endpoint or field of theirs is guessed. `configured_transport()` still returns
`None`. Not in the payload yet: the practice's HPI-O and address (no column exists). The eScript token
reference is returned by the wire but not stored (needs a schema change and the delivery decision).

**Reconciliation (2026-11-21):** how the build maps to the Phase 2 and Phase 3 tasks, every deviation and what is owed: [`reconciliation-2026-11-21-tga-inbox-and-erx.md`](../reconciliation-2026-11-21-tga-inbox-and-erx.md).

## Alternatives considered

- **Call Parchment directly from the sign or dispatch route.** Rejected: a timeout would leave the
  prescription in an unknown state with no reconciliation, and a retry could create a second script.
  The outbox already solves this.
- **Drive Parchment from an automation service (Zapier and similar).** Rejected for the reasons in
  [D-011](D-011-tga-inbox-pipeline-architecture.md): offshore transit of the full script and patient
  identity, no same-transaction audit, credentials outside our secret store.
- **A configuration flag that turns on any transport URL.** Rejected: that flag would itself be an
  unregistered third-party data flow (FEAT-13 R1).

## Consequences

- Easier: the outbox, idempotency and reconciliation are already built and tested, so the work is the
  adapter, the payload and the webhook.
- Harder: nothing can go live until the contract and conformance split are settled; until then the
  feature is demonstrable only against the simulated driver and the Parchment sandbox.
- Evidence: adapter tests over every outcome, the payload allow-list test, FEAT-12 webhook tests, and
  a staging run against the sandbox.

## Effect on the gates

- **Gate 5:** the Parchment row in the integration register moves from "to confirm" to a reviewed data
  flow. Production enablement has no conditional pass while F3 is unresolved.
- **Gate 4:** unchanged. The safety gate runs before dispatch and the adapter cannot bypass it.

## Open items

| Item | Owner | Status |
|---|---|---|
| Parchment as the eRx vendor (D7e) and the contract | CTO + Practice Owner | 🔴 OPEN |
| Sandbox access, API docs, support path (ADR-010 F1) | CTO | OPEN |
| Conformance responsibility split (F3) | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Credential owner and rotation (F4) | Security Lead | OPEN |
| Payload allow-list | Privacy Officer | OPEN |
| Webhook path and the no-tenant quarantine design (FEAT-13 open items) | Security Lead + Head of Platform | OPEN |
| Who delivers the eScript token to the patient | Head of Product | OPEN |
| Outage fallback (F5) | Clinical Safety Officer | OPEN |
