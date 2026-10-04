# Data Classification and Audit Ledger: Tenancy and Authentication

## 1. Field-Level Classification (Doc 12 Alignment)

| Field Name | Classification Level | Storage & Encryption | Redaction in Logs | Export Policy |
|---|---|---|:---:|---|
| `users.email` | **RESTRICTED** | AES-256 at rest (RDS) | No (Auditable identifier) | Allowed with `user:read` |
| `users.hashed_password` | **HIGHLY RESTRICTED** | Argon2id hash + salt | **STRICT REDACTION** | **NEVER EXPORTED** |
| `users.mfa_secret` | **HIGHLY RESTRICTED** | KMS Envelope Encrypted | **STRICT REDACTION** | **NEVER EXPORTED** |
| `tenants.name` | **INTERNAL** | Standard RDS | No | Tenant-scoped export |
| `clinics.address` | **RESTRICTED** | AES-256 at rest | Partial (Suburb/State only) | Allowed with `clinic:read` |

---

## 2. Audit Event Envelope (Doc 07 Alignment)

All authentication and administration operations emit events into the append-only `audit_log` table.

### Audit Log Schema
```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    actor_id UUID,                     -- NULL for unauthenticated attempts
    actor_email VARCHAR(255),
    event_type VARCHAR(100) NOT NULL,  -- e.g. LOGIN_SUCCEEDED, ROLE_ASSIGNED
    resource_type VARCHAR(50) NOT NULL,-- e.g. user, tenant, clinic
    resource_id UUID,
    action_status VARCHAR(20) NOT NULL,-- SUCCESS, DENIED, FAILED
    ip_address INET,
    user_agent TEXT,
    payload_hash CHAR(64),             -- SHA-256 hash of payload metadata (no PII)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Strict Immutability: Application role has INSERT and SELECT only
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM app_user;
```

### Event Catalogue for Feature 01
| Event Name | Trigger Condition | Severity |
|---|---|:---:|
| `LOGIN_SUCCEEDED` | Valid email, password, and MFA code | INFO |
| `LOGIN_FAILED` | Invalid credentials submitted | WARN |
| `ACCOUNT_LOCKED` | 5 failed attempts reached | **ALERT** |
| `MFA_CHALLENGE_FAILED` | Invalid TOTP/SMS token submitted | WARN |
| `STEP_UP_SUCCEEDED` | Critical action authenticated with re-prompt | INFO |
| `USER_CREATED` | New team member invited/created | INFO |
| `ROLE_ASSIGNED` | Role assigned or permissions elevated | **NOTICE** |
| `TENANT_CONFIG_CHANGED` | Clinic security policy altered | **NOTICE** |
