---
doc_id: FEAT-AUTH-06
title: Authentication, test plan
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 26-security-gates, D-003
---

# Authentication: test plan

All tests run in CI on synthetic two-tenant data with a canary tenant. A failing security test blocks
merge. Every row carries its exact command: a test name without its command is not evidence.

```bash
# Whole module, then the suites that gate Gate 3
cd backend && uv run pytest tests/auth tests/security/test_auth_grants.py \
  tests/security/test_no_credentials_in_logs.py tests/isolation/test_auth_isolation.py -v
```

## Functional tests (F) — R1–R14

| ID | Case | Expected result | Evidence command (F/S/A) |
|---|---|---|---|
| **F1** | Login with a valid credential and second factor | `200`; access token in body, refresh cookie set, session row written | `cd backend && uv run pytest tests/auth/test_login.py::test_login_with_mfa_issues_session -v` |
| **F2** | Login with a first factor but no second factor | No session created; only `GET /api/v1/auth/session` and enrolment reachable | `cd backend && uv run pytest tests/auth/test_mfa.py::test_login_without_second_factor_creates_no_session -v` |
| **F3** | Failed login (wrong credential) | `401` generic body; `LOGIN_FAILED` audited; no hint of account existence | `cd backend && uv run pytest tests/auth/test_login.py::test_failed_login_is_generic_and_audited -v` |
| **F4** | Refresh token used twice | Second call returns a different token; the first is rejected afterwards | `cd backend && uv run pytest tests/auth/test_session.py::test_refresh_token_rotates_on_every_use -v` |
| **F5** | Clinical session idle 21 minutes | `401` on the next request; idle-close event emitted | `cd backend && uv run pytest tests/auth/test_session.py::test_idle_timeout_closes_clinical_session -v` |
| **F6** | Session refreshed continuously for 12 hours | `401` at the absolute timeout regardless of activity | `cd backend && uv run pytest tests/auth/test_session.py::test_absolute_timeout_closes_session -v` |
| **F7** | Logout, then reuse the refresh cookie | `401` before expiry; `SESSION_REVOKED` audited | `cd backend && uv run pytest tests/auth/test_session.py::test_logout_revokes_server_side -v` |
| **F8** | Logout-all with three live sessions | Every family revoked; each device returns `401` | `cd backend && uv run pytest tests/auth/test_session.py::test_logout_all_revokes_every_family -v` |
| **F9** | Failures reach the defined threshold | Account locked, `ACCOUNT_LOCKED` audited, further attempts generic | `cd backend && uv run pytest tests/auth/test_lockout.py::test_lockout_at_defined_failure_count -v` |
| **F10** | Administrator releases a lockout with step-up and a reason | Account usable; release audited with `released_by` and `release_reason` | `cd backend && uv run pytest tests/auth/test_lockout.py::test_lockout_release_is_audited -v` |
| **F11** | Recovery request for an existing and an unknown account | Byte-identical response body, status and timing class | `cd backend && uv run pytest tests/auth/test_recovery.py::test_recovery_response_identical_for_known_and_unknown_account -v` |
| **F12** | Recovery completion with an enrolled factor | Second factor required before completion; single-use token; `PASSWORD_RESET_COMPLETED` audited | `cd backend && uv run pytest tests/auth/test_recovery.py::test_recovery_requires_enrolled_second_factor -v` |
| **F13** | Step-up then a named high-risk operation | Step-up succeeds; the operation proceeds; `STEP_UP_SUCCEEDED` written | `cd backend && uv run pytest tests/auth/test_step_up.py::test_step_up_succeeds_for_named_operation -v` |
| **F14** | First login with no enrolled factor | Enrolment forced before any clinical route is reachable | `cd backend && uv run pytest tests/auth/test_mfa.py::test_enrolment_forced_at_first_login -v` |
| **F15** | Role changed while a session is live | Refresh refused; a new login yields the new permission set | `cd backend && uv run pytest tests/auth/test_session.py::test_role_change_invalidates_refresh -v` |

## Security tests (S) — Gate 3 checks and threat controls

| ID | Case | Expected result | Evidence command |
|---|---|---|---|
| **S1** | Direct API call with a valid first-factor token and a forged `mfa=true` claim | Refused; MFA cannot be asserted by the client; attempt audited | `cd backend && uv run pytest tests/security/test_auth_mfa_enforcement.py::test_mfa_cannot_be_asserted_by_client -v` |
| **S2** | Access token past `exp` | `401`, no data returned | `cd backend && uv run pytest tests/security/test_auth_tokens.py::test_expired_access_token_refused -v` |
| **S3** | Rotated refresh token replayed | Family revoked, user notified, `AUTH_REFRESH_REUSE_DETECTED` audited | `cd backend && uv run pytest tests/security/test_auth_tokens.py::test_refresh_reuse_revokes_family -v` |
| **S4** | Session revoked, token still inside `exp` | `401` before token expiry; `SESSION_REVOKED` audited | `cd backend && uv run pytest tests/security/test_auth_tokens.py::test_revoked_session_refused_before_expiry -v` |
| **S5** | Threshold failures, then an audited administrator release | Lockout enforced in the auth path; release writes the event; failure history intact | `cd backend && uv run pytest tests/security/test_auth_lockout.py::test_lockout_and_audited_release -v` |
| **S6** | Each of the five named operations called without fresh step-up | `403 step_up_required`; nothing performed; denial audited | `cd backend && uv run pytest tests/security/test_auth_step_up.py::test_step_up_enforced_for_named_operations -v` |
| **S7** | Step-up token reused, and applied to a different resource | Refused both ways; single-use and resource-bound | `cd backend && uv run pytest tests/security/test_auth_step_up.py::test_step_up_token_single_use_and_resource_bound -v` |
| **S8** | Seed data and the access-review baseline inspected | One identity per person; zero shared clinical or administrative accounts | `cd backend && uv run pytest tests/security/test_auth_no_shared_accounts.py::test_no_shared_accounts_in_seed_data -v` |
| **S9** | **Sentinel test:** a unique credential value is placed in every auth request path and every log sink is scanned (app log, audit payload, error telemetry, trace, metric label, queue message, crash report) | Sentinel count is zero everywhere; CI fails on any occurrence | `cd backend && uv run pytest tests/security/test_no_credentials_in_logs.py::test_credential_sentinel_absent_from_all_log_sinks -v` |
| **S10** | `information_schema.role_table_grants` and `column_privileges` inspected; app role attempts to read the verifier and the MFA seed | `clinos_app` holds no `SELECT` on `hashed_password` or `mfa_enrolments.secret`; the read raises `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_auth_grants.py::test_app_role_cannot_read_credential_material -v` |
| **S11** | Wrong credential, unknown account, locked account compared | Identical body, status and timing class; no enumeration signal | `cd backend && uv run pytest tests/security/test_auth_enumeration.py::test_login_errors_do_not_disclose_account_existence -v` |
| **S12** | Valid tenant-A token requests a tenant-B resource | `404 Not Found`, never `403`; cross-tenant denial audited | `cd backend && uv run pytest tests/isolation/test_auth_isolation.py::test_cross_tenant_token_returns_404 -v` |
| **S13** | Authenticated request with no resolvable tenant | Refused; zero rows; no "all tenants" fallback | `cd backend && uv run pytest tests/isolation/test_auth_isolation.py::test_missing_tenant_context_denies -v` |
| **S14** | `alg: none`, a symmetric-algorithm token, and an unknown `kid` | Each refused `401`; no key material accepted from the request | `cd backend && uv run pytest tests/security/test_auth_tokens.py::test_alg_none_and_unknown_kid_rejected -v` |
| **S15** | TOTP presented for a permission change or security-config change | Refused; passkey or hardware key required | `cd backend && uv run pytest tests/security/test_auth_step_up.py::test_totp_rejected_for_permission_and_security_config_change -v` |
| **S16** | Authentication rate limits exceeded | `429` with `Retry-After`; backoff observed; no whole-tenant lockout | `cd backend && uv run pytest tests/security/test_auth_rate_limits.py::test_auth_rate_limit_and_backoff -v` |
| **S17** | User offboarded while three sessions are live | Every family revoked within 60 s; tokens then refused | `cd backend && uv run pytest tests/security/test_auth_tokens.py::test_offboarding_revokes_all_sessions_within_60_seconds -v` |
| **S18** | Frontend bundle and error responses scanned for credential values | Zero matches; no token, verifier or seed in any bundle or error body | `cd backend && uv run pytest tests/security/test_no_credentials_in_logs.py::test_no_credentials_in_bundles_or_error_responses -v` |

## Audit tests (A) — 05-data-and-audit.md event catalogue

| ID | Case | Expected result | Evidence command |
|---|---|---|---|
| **A1** | Each success path (login, step-up, revocation) | One event with the full envelope, correct `action`, `actor_role` and `request_id` | `cd backend && uv run pytest tests/auth/test_audit_events.py::test_success_events_use_the_standard_envelope -v` |
| **A2** | Each refusal (`401`, `403`, step-up failure, cross-tenant) | A denied or failed event written with equal fidelity, before the response | `cd backend && uv run pytest tests/auth/test_audit_events.py::test_denied_and_failed_events_equal_fidelity -v` |
| **A3** | Audit store made unavailable during login | The action fails `503`; no session is issued unaudited | `cd backend && uv run pytest tests/auth/test_audit_events.py::test_audit_write_failure_fails_closed -v` |
| **A4** | Wrong second factor | `MFA_CHALLENGE_FAILED` emitted with `method`, `reason`, `source_ip` | `cd backend && uv run pytest tests/auth/test_audit_events.py::test_mfa_challenge_failed_audited -v` |
| **A5** | Break-glass elevation granted | `AUTH_BREAK_GLASS_GRANTED` with `ticket_reference`, `expires_at`, `step_up`, dual notification | `cd backend && uv run pytest tests/auth/test_audit_events.py::test_break_glass_granted_audited -v` |

## Grant-inspection test detail (S10)

* **Source:** `07-audit-architecture.md` §3; `04-database-erd.md` §9; `12-data-classification.md` §5.1; Gate 3.
* **Command:** `cd backend && uv run pytest tests/security/test_auth_grants.py::test_app_role_cannot_read_credential_material -v`

The test inspects `information_schema.role_table_grants` and `column_privileges` for `clinos_app` and
`clinos_auth`, then asserts the runtime denial:

```python
def test_app_role_cannot_read_credential_material(db_app_role, db_admin_role):
    table_grants = db_admin_role.execute("""
        SELECT table_name, privilege_type FROM information_schema.role_table_grants
        WHERE grantee = 'clinos_app'
          AND table_name IN ('audit_log','refresh_tokens','login_attempts','mfa_enrolments')
    """).fetchall()
    audit = {g.privilege_type for g in table_grants if g.table_name == "audit_log"}
    assert audit == {"SELECT", "INSERT"}, f"audit_log grant leak: {audit}"
    attempts = {g.privilege_type for g in table_grants if g.table_name == "login_attempts"}
    assert {"UPDATE", "DELETE", "TRUNCATE"}.isdisjoint(attempts)

    # Column-level: the app role must not hold SELECT on credential material.
    cols = db_admin_role.execute("""
        SELECT table_name, column_name FROM information_schema.column_privileges
        WHERE grantee = 'clinos_app' AND privilege_type = 'SELECT'
          AND ((table_name = 'users' AND column_name = 'hashed_password')
            OR (table_name = 'mfa_enrolments' AND column_name = 'secret'))
    """).fetchall()
    assert cols == [], f"credential column granted to app role: {cols}"

    with pytest.raises(DBAPIError) as exc:
        db_app_role.execute("SELECT hashed_password FROM users LIMIT 1")
    assert "permission denied" in str(exc.value).lower()
```

Under **Branch A** the `users.hashed_password` and `mfa_enrolments.secret` assertions are vacuous
because those columns do not exist; the test asserts their absence from
`information_schema.columns` instead. This is the only branch-dependent test in the suite.

## Traceability
F1–F15 cover R1–R14. S1–S18 cover the Gate 3 checks (`26 §4`) and the controls in
04-threat-model.md. A1–A5 cover the event catalogue in 05-data-and-audit.md. A failing cross-tenant
assertion, MFA-enforcement assertion or credential-sentinel assertion is a release blocker.
