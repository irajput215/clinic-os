# Threat Model: Tenancy and Authentication

## 1. Scope & Assets
- **Protected Assets**: Tenant isolation boundary, User password hashes, MFA secrets, JWT signing keys, Session states.
- **Boundaries**: Client Browser <-> Public ALB <-> FastAPI Middleware <-> RDS PostgreSQL (RLS).

## 2. STRIDE Assessment Matrix

| Threat ID | STRIDE Category | Threat Description | Control / Mitigation | Residual Risk | Owner |
|:---:|---|---|---|:---:|---|
| **T-01.1** | **Spoofing** | Attacker injects another tenant's ID into request headers or body (`X-Tenant-ID: victim-uuid`). | **Ignore-and-Drop:** Middleware resolves tenant exclusively from the verified JWT `tenant_id` claim. Any client-sent tenant ID is purged. | Negligible | Security Lead |
| **T-01.2** | **Tampering** | Rogue actor attempts brute-force on staff password or MFA challenge. | Account lockout triggered after 5 consecutive failures for 15 minutes; rate limiting on `/auth/login` (5 req/min per IP). | Low | Security Lead |
| **T-01.3** | **Repudiation** | An admin deletes a user or elevates privileges and denies having done so. | Immutable audit log event (`ROLE_ASSIGNED` / `USER_CREATED`) written inside the same database transaction, signed with actor ID and client IP. | Low | CTO |
| **T-01.4** | **Information Disclosure** | Cross-tenant data bleed occurs via pooled database connections where previous transaction didn't clear session variables. | Enforce `SET LOCAL app.tenant_id = :tid` (transaction-scoped). Even if code omits `WHERE tenant_id = :id`, PostgreSQL RLS rejects rows from other tenants. | Low | CTO |
| **T-01.5** | **Denial of Service** | Volumetric brute-force attack saturates login endpoints and exhausts database connections. | Fast path rate-limiting at edge (WAF/Redis), short connection checkout timeout (5s), bcrypt/argon2 workload tuning. | Medium | Platform Lead |
| **T-01.6** | **Elevation of Privilege** | Normal clinician modifies user role to `PRACTICE_OWNER`. | Granular RBAC policy check on server: only users possessing `user:manage` AND valid step-up auth within 5 mins can assign roles. | Low | Security Lead |

## 3. Residual Risk Sign-Off
- **T-01.5 (DoS)**: Rate-limiting absorbs standard credential stuffing; distributed DDoS relies on CloudFront + WAF managed rules.
