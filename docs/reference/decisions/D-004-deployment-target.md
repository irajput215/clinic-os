# D-004: Deployment target is unresolved between compose and the source's AWS shape

- **Status:** 🔴 **OPEN — requires a decision. This blocks Gate 6.**
- **Date:** 2026-10-04
- **Owner:** CTO + Head of Platform
- **Source contract reference:** `21-technical-design.md` §6 "Infrastructure"; `28-aws-network-and-deployment.md`; `ADR-003-aws-sydney-deployment.md`; `ADR-004-docker.md`

## Context

The source contract pins the deployment shape tightly:

- **Region:** `ap-southeast-2` (Sydney) as the **only** production region for clinical data. This is
  decision 2 of the two decisions put to the Practice Owner in `90-owner-brief.md`, and it is what makes
  INV-6 ("data stays in Australia") true.
- **Compute:** ECS Fargate, private application subnets, no public IP, non-root, read-only root filesystem.
- **Edge:** CloudFront + AWS WAF, public ALB, TLS termination.
- **Data:** RDS PostgreSQL 16 Multi-AZ in private data subnets with no internet route; private S3 with
  Object Lock on the audit archive; SQS + DLQ.
- **Secrets:** AWS Secrets Manager, per-environment, injected at task start.
- **IaC:** Terraform (ADR-011).

This repo has:

- `compose.yml`, `compose.override.yml`, `compose.deploy.yml` — a Docker Compose deployment
- `.env` at the repo root (committed — the source contract forbids secrets in the repo; this needs review)
- `backend/Dockerfile`, `frontend/Dockerfile.playwright`
- `.github/workflows/` CI, `.pre-commit-config.yaml`
- **No Terraform, no AWS resource definitions, no region pin anywhere**

The source contract's Gate 6 checks are largely written against the AWS shape: "WAF rules and
blocked-request logging are active", "IAM has no long-lived access keys", "environment separation is
verified: no production database, bucket, secret, key or credential is reachable from development",
"backups run and a restore drill has been performed". Under plain compose these translate to different
controls with different evidence.

**One divergence already needs its own answer regardless of this decision:** the repo has no region pin.
INV-6 is not currently true or false — it is unimplemented. That is a Gate 1 (architecture) gap, not only a
Gate 6 gap.

## Decision

**NOT YET MADE.** Recorded as an open decision so that no phase 4 work, and no control-matrix row claiming
residency, depends on it silently.

### Option A — Target the source contract's AWS shape

- Conforms to the contract, including the Sydney region pin and the residency rule.
- Required work: Terraform (VPC, subnets, ECS, RDS, S3, SQS, KMS, Secrets Manager, WAF, ALB), image
  publishing to ECR with immutable tags, per-environment secret stores, and the Gate 6 evidence set.
- Cost: the largest infrastructure lift in the project, plus an AWS account and the residency/vendor
  obligations that follow.

### Option B — Docker Compose on a single Australian-hosted host

- Matches what exists today.
- Still satisfies INV-6 **if and only if** the host is in Australia and the managed database/storage used
  are also in Australia. Region pinning then lives in the host and database provider choice, not in
  Terraform.
- Required work: a documented environment-separation model, a secret store that is not a committed `.env`,
  TLS termination, rate limiting at the edge (the WAF controls have no direct equivalent), backup and a
  **timed restore drill**, and an explicit statement of which Gate 6 checks are met a different way.
- **Divergence record required:** which Gate 6 checks are replaced, by what control, with what evidence.

### Option C — Compose for Development/Staging, AWS for Production

- Common and pragmatic; it is what the source contract's environment separation implies anyway.
- Requires both workstreams, and requires that Development and Staging never hold production data.

## Consequences

**Blocked until decided:** all of Phase 4's Gate 6 and Gate 7 evidence; the environment separation model in
Gate 1; every control-matrix row asserting residency or infrastructure hardening.

**Not blocked:** Phases 0–3. The application, schema, RLS, audit and safety-gate work is
infrastructure-agnostic — with one exception: the secret store abstraction, which should be written
against an interface in Phase 0 so that moving from `.env` to Secrets Manager later is a configuration
change, not a rewrite.

## Effect on the gates

- **Gate 6 (Production): 🔴 BLOCKED.** Cannot be signed.
- **Gate 7 (Go-Live):** blocked transitively via Gate 6.
- **Gate 1 (Architecture):** the check *"the environment separation model is defined for Development,
  Staging and Production"* **fails** until this is decided. Gate 1 is therefore also blocked.
- **Gate 2, 3, 4, 5:** not blocked.

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | Choose Option A, B or C | CTO + Head of Platform |
| 2 | Confirm the production region and prove it, so INV-6 has evidence rather than an intention | CTO + Compliance Lead |
| 3 | ~~Review the committed root `.env` for any real secret~~ **VERIFIED 2026-10-04:** `.env` **is** tracked in git and holds `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD` and `POSTGRES_PASSWORD`, all at the template default `changethis`. Not a leaked production secret today, but a live violation of control 8, and `SECRET_KEY=changethis` permits JWT forgery if deployed. Fix is a **Phase 0 exit task**: untrack, add to `.gitignore`, ship `.env.example`, rotate every value ever committed | Security Lead |
| 4 | Confirm RPO and RTO, which Gate 6's restore drill is measured against | Practice Owner |
| 5 | Confirm which Gate 6 checks are replaced under Option B, and with what evidence | Security Lead |
| 6 | Decide whether Infrastructure-as-Code is Terraform or compose-only, and record it as its own decision | Head of Platform |
