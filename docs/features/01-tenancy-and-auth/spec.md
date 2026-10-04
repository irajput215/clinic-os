---
feature_id: FEAT-01
title: Tenancy and Authentication Specification
status: DRAFT
owner: Security Lead / CTO
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
traceability_docs:
  - clinic-os-secure-by-design/05-tenant-isolation.md
  - clinic-os-secure-by-design/06-authentication-rbac.md
  - clinic-os-secure-by-design/20-product-requirements.md
  - clinic-os-secure-by-design/21-technical-design.md
---

# Feature 01: Tenancy and Authentication

## 1. Overview & Purpose
Model customer clinic organisations (`tenants`), their clinical practice sites (`clinics`), and provide secure authentication with role-based access control (RBAC). 

**The Non-Negotiable Principle:**
Tenant identity is strictly **resolved from the authenticated session (JWT) and the addressed resource**. Tenant identity is **never** accepted from a request body, URL query parameter, or custom client header. Any supplied `tenant_id` from the client is dropped and audited as an anomaly.

---

## 2. Personas & User Stories

### Story 1.1: Practice Login with MFA
- **As a** Doctor / Authorised Prescriber
- **I want to** authenticate using my credentials and submit an MFA challenge
- **So that** I securely access patient records without risking unauthorized clinical access.
  - *Security Criterion:* MFA enforced for all clinical/admin accounts; accounts lock after 5 consecutive failures for 15 minutes (`ACCOUNT_LOCKED`).
  - *Audit Criterion:* Emits `LOGIN_SUCCEEDED`, `LOGIN_FAILED`, or `MFA_CHALLENGE_FAILED` with client IP and user agent. Password and token values are strictly excluded from logs.

### Story 1.2: Tenant-Scoped API Operations
- **As a** Clinic Administrator
- **I want to** query staff and clinic branches
- **So that** I only ever view data belonging to my licensed organisation.
  - *Security Criterion:* Every query is constrained by PostgreSQL Row-Level Security (`FORCE ROW LEVEL SECURITY`) bound to `SET LOCAL app.tenant_id = :tenant_id`.
  - *Audit Criterion:* Denied attempts across tenant boundaries return `404` or `403` and emit a security anomaly event `TENANT_CROSS_ACCESS_ATTEMPT`.

### Story 1.3: Step-Up Authentication for High-Risk Actions
- **As a** Practice Owner / Administrator
- **I want to** be prompted for re-authentication when modifying clinic security settings or granting roles
- **So that** an unattended workstation cannot be hijacked for privilege escalation.
  - *Security Criterion:* Step-up token validity is limited to 5 minutes and single-purpose.

---

## 3. Granular RBAC Permissions
Roles are thin bundles over atomic permissions:

| Permission | Description | Assigned Roles |
|---|---|---|
| `tenant:read` | View tenant profile & subscription info | `PRACTICE_OWNER`, `CLINIC_ADMIN` |
| `tenant:configure` | Update security policies, billing, integrations | `PRACTICE_OWNER` |
| `clinic:manage` | Create, update branches and practice details | `PRACTICE_OWNER`, `CLINIC_ADMIN` |
| `clinic:read` | View clinic operating hours and details | All authenticated roles |
| `user:read` | View team members within tenant | `PRACTICE_OWNER`, `CLINIC_ADMIN`, `DOCTOR` |
| `user:manage` | Invite staff, assign roles, de-activate accounts | `PRACTICE_OWNER`, `CLINIC_ADMIN` |
| `session:revoke` | Force-logout a session or user | `PRACTICE_OWNER`, `CLINIC_ADMIN` |

---

## 4. API Endpoints (Deny-by-Default)

| Method | Endpoint | Required Permission | Step-Up Required? | Audit Event |
|---|---|---|:---:|---|
| `POST` | `/api/v1/auth/login` | None (Public) | No | `LOGIN_SUCCEEDED` / `LOGIN_FAILED` |
| `POST` | `/api/v1/auth/mfa/challenge` | Session In-Flight | No | `MFA_VERIFIED` / `MFA_CHALLENGE_FAILED` |
| `POST` | `/api/v1/auth/step-up` | Authenticated | Yes | `STEP_UP_SUCCEEDED` |
| `POST` | `/api/v1/auth/logout` | Authenticated | No | `LOGOUT` |
| `GET` | `/api/v1/tenants/current` | `tenant:read` | No | `TENANT_VIEWED` |
| `PATCH` | `/api/v1/tenants/current` | `tenant:configure` | Yes | `TENANT_CONFIG_CHANGED` |
| `GET` | `/api/v1/clinics` | `clinic:read` | No | `CLINIC_LISTED` |
| `POST` | `/api/v1/clinics` | `clinic:manage` | No | `CLINIC_CREATED` |
| `GET` | `/api/v1/users` | `user:read` | No | `USER_LIST_VIEWED` |
| `POST` | `/api/v1/users` | `user:manage` | Yes | `USER_CREATED` |
| `PATCH` | `/api/v1/users/{id}/roles` | `user:manage` | Yes | `ROLE_ASSIGNED` |

---

## 5. Database Schema & RLS Implementation

Every multi-tenant table carries `tenant_id UUID NOT NULL`.

```sql
-- 1. Tenants Table (Global catalog, no tenant_id)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Clinics Table (Tenant-scoped)
CREATE TABLE clinics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    address JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_clinics_tenant_id ON clinics(tenant_id);

-- 3. Row-Level Security Backstop
ALTER TABLE clinics ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinics FORCE ROW LEVEL SECURITY;

CREATE POLICY clinics_tenant_isolation ON clinics
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

### Connection Pool Isolation Guard
In SQLAlchemy / Psycopg, every checkout from the connection pool executes:
```python
# Before query execution
session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(current_user.tenant_id)})
```
`SET LOCAL` ensures that when the transaction completes or rolls back, the variable resets and cannot bleed into subsequent requests on the same pooled connection.
