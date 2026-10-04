# D-003: Identity is self-hosted password auth, not a managed OIDC provider

- **Status:** 🔴 **OPEN — requires a decision. This blocks Gate 3.**
- **Date:** 2026-10-04
- **Owner:** CTO + Security Lead
- **Source contract reference:** `01-system-architecture.md` §8 "Identity"; §9 "What we deliberately do not build"; `02-security-architecture.md` §1 control 1; `26-security-gates.md` §4 Gate 3

## Context

The source contract is unambiguous, and it is a **security control, not a preference**:

> **Identity** | Managed OpenID Connect provider, MFA enforced, short-lived access tokens, rotating refresh tokens
> — `01-system-architecture.md` §8

> **No custom identity provider.** Password storage, MFA, recovery and federation are bought, not built.
> — `01-system-architecture.md` §9

> **Authentication secrets** | Never stored | The identity provider holds credentials. **We store no password hash.**
> — `02-security-architecture.md` §5.1

This repo ships the opposite, inherited from the template:

- `backend/app/core/security.py` — token creation/verification via **PyJWT**
- `backend/pyproject.toml` — **`pwdlib[argon2,bcrypt]>=0.3.1`**, i.e. password hashing is a first-class
  dependency
- `backend/app/api/routes/login.py` — a password login route (`/login/access-token`)
- The existing feature docs at `docs/features/01-tenancy-and-clinics/` already specify `users.hashed_password`
  as **HIGHLY RESTRICTED, Argon2id, never exported**, and name `JWT signing keys` as a protected asset

So there are two coherent but **mutually exclusive** identity architectures on the table, and the existing
repo docs contradict the source contract.

This matters beyond Gate 3. The choice changes: the `users` schema (a `hashed_password` column either
exists or does not), session storage and revocation design, the MFA implementation and its enrolment flow,
account-recovery design, the step-up mechanism, several threat-model entries (T-01.2 brute force, T-01.6
privilege escalation), the Gate 3 checklist, and the frontend's token-handling requirements (source doc 02
§10 requirements 3 and 11).

## Decision

**NOT YET MADE.** Recorded as an open decision so that no work depends on it silently.

### Option A — Adopt the source contract: managed OIDC provider

- Conforms to the source contract, including its explicit "no custom identity system" anti-list.
- Removes password storage, hashing, recovery and breached-credential checking from our attack surface.
- Required work: replace the template login route; delete the `hashed_password` column in favour of an IdP
  subject identifier; implement MFA, step-up (`auth_time` window) and revocation against the IdP; add
  IdP-issued `mfa` and `auth_time` claims to the token contract.
- Cost: an IdP contract and cost, plus a dependency that must satisfy the residency rule (INV-6) and be
  entered in the vendor register with its terms marked, per Gate 5.

### Option B — Keep self-hosted password auth, harden it

- Conforms to the repo as it exists and to the already-written feature docs.
- **Diverges from an explicit source-contract control**, so it requires: this record to move to
  `Accepted`, a compensating-control statement, and a Threat Model update covering the controls the source
  assumed were bought rather than built.
- Required work: Argon2id parameters and rehash-on-login; MFA (TOTP) enrolment, recovery codes and
  enforcement for clinical and administrative roles; account lockout with an audited release path;
  refresh-token rotation with family revocation and a server-side revocation list; breached-credential
  checking; a step-up token with a 5-minute single-purpose window; and the full Gate 3 evidence set.
- Cost: we now own credential storage, MFA, recovery and lockout — the exact responsibilities the source
  contract declined to take on.

### Why this is not a style question

Gate 3 checks "MFA is enforced for clinical and administrative roles and cannot be bypassed by a direct
API call" and "Refresh tokens rotate, and reuse revokes the token family". Under Option A these are
configuration assertions against a provider; under Option B they are code we write, test and own forever.
The evidence artefact, the failure modes and the residual risk differ materially. **Gate 3 cannot be
signed until this is decided.**

## Consequences

**Blocked until decided:** the `users` table and its migration, the auth module, the session/revocation
design, the step-up mechanism, the MFA threat-model entries, and Gate 3.

**Not blocked:** Phase 0 (foundation) and the tenancy, patient-register, RLS, audit-envelope and CI work in
Phase 1 that does not touch credential storage. The `tenants` table, RLS policies, `audit_log` and the
isolation suite are all identity-agnostic.

## Effect on the gates

- **Gate 3 (Authentication): 🔴 BLOCKED.** Cannot be signed.
- **Gate 2 (Database):** partially affected — the `users` table shape depends on this decision, but RLS
  and isolation evidence do not.
- **Gate 1 (Architecture):** the threat model and ADR set must record which option was chosen before
  Gate 1 is signed. Gate 1 is therefore blocked too if the threat model's authentication section is left
  unresolved.

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | Choose Option A or Option B | CTO + Security Lead |
| 2 | If A: candidate IdP, its Australian data-processing position, and its contract terms | CTO + Compliance Lead |
| 3 | If A: whether the IdP's MFA is phishing-resistant (passkey/WebAuthn) at the required assurance level | Security Lead |
| 4 | If B: the Argon2id parameter set and the key-rotation procedure for any signing key | Security Lead |
| 5 | Either way: who holds the signing key material, and how it rotates without invalidating live sessions | Security Lead |
| 6 | Reconcile `docs/features/01-tenancy-and-clinics/` with whichever option is chosen | Security Lead |
