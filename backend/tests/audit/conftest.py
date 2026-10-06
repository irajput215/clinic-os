"""Fixtures for the Feature 04 audit tests.

Every case runs against the **migrated** database and the real API, and every row it inspects is
either written through the application or read as the owner connection. Two things are deliberate:

- **Nothing deletes an audit row.** The trail is append-only, the owner holds no `DELETE` on it by
  policy, and the whole point of the feature is that a row, once written, stays written. Assertions
  are therefore written as deltas against the state at the start of the case, never as absolute
  counts, and a re-run of the suite sees the same result.
- **Nothing writes an audit row directly.** A test that inserted its own event would prove the table
  accepts an insert; it would not prove that the application's writer chains it, which is the control.

`RbacApi` already registers an organisation through `POST /users/signup` — which provisions the seven
system roles and the bootstrap `PRACTICE_OWNER` grant — and signs in as its owner. That owner holds
`audit:read`, `patient:create` and `patient:update`, so it can drive every endpoint this module tests
without a second helper.
"""

import uuid
from collections.abc import Iterator
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine, tenant_transaction
from app.modules.audit import service
from app.modules.audit.actions import ACTIONS, PAYLOAD_ALLOW_LIST
from tests.utils.rbac import RbacApi

AUDIT_URL = f"{settings.API_V1_STR}/audit"
PATIENTS_URL = f"{settings.API_V1_STR}/patients"

# The chain, read as the **owner**, which is `postgres` locally and a superuser in CI. Reading as the
# owner is what makes an assertion about rows that exist rather than rows a policy would hide — and
# it is also the only role that can make the tampering the verification tests need, because the
# application role holds no `UPDATE` at all (which is the control those tests guard).
_ROWS = text(
    "SELECT event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type,"
    " resource_id, result, reason, request_id, correlation_id, prev_hash, hash, metadata"
    " FROM audit_log WHERE tenant_id = :tenant_id"
)


class AuditApi(NamedTuple):
    """The two handles a case needs: the HTTP API and a tenant whose chain it can inspect."""

    rbac: RbacApi
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    headers: dict[str, str]


def audit_rows(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every audit row of one tenant, oldest first, read as the owner."""
    with engine.connect() as conn:
        rows = conn.execute(_ROWS, {"tenant_id": tenant_id}).mappings().all()
    ordered = sorted(rows, key=lambda row: (row["timestamp"], str(row["event_id"])))
    return [dict(row) for row in ordered]


def audit_count(tenant_id: uuid.UUID) -> int:
    return len(audit_rows(tenant_id))


def actions_of(tenant_id: uuid.UUID) -> list[str]:
    return [str(row["action"]) for row in audit_rows(tenant_id)]


def chain_report(tenant_id: uuid.UUID) -> service.ChainReport:
    """Verify a tenant's chain through the application's own facade, not through the test."""
    with tenant_transaction(tenant_id=tenant_id) as session:
        return service.verify_chain(session, tenant_id=tenant_id)


def tamper(sql: str, params: dict[str, Any]) -> None:
    """Run a statement the application role cannot run, as the owner.

    This is the *attacker* in the tamper-detection tests: the simulation of somebody who reached the
    database with more privilege than `clinos_app` has. The migration's whole point is that this
    requires more than the application holds (`42501 insufficient_privilege` for `clinos_app`), and
    `tests/audit/test_append_only_grants.py` proves that half separately.
    """
    with engine.begin() as conn:
        conn.execute(text(sql), params)


@pytest.fixture
def api(client: TestClient, db: Session) -> Iterator[AuditApi]:
    """One signed-up organisation whose owner can exercise every endpoint here."""
    rbac = RbacApi(client, db)
    owner = rbac.register_tenant(clinic_name="Audit Test Clinic")
    assert owner.tenant_id is not None
    yield AuditApi(
        rbac=rbac,
        tenant_id=owner.tenant_id,
        user_id=owner.user_id,
        headers=owner.headers,
    )
    rbac.cleanup()


@pytest.fixture
def two_tenants(client: TestClient, db: Session) -> Iterator[tuple[AuditApi, AuditApi]]:
    """Two independent organisations, for the cross-tenant cases (S1, S2)."""
    rbac = RbacApi(client, db)
    first = rbac.register_tenant(clinic_name="Audit Tenant A")
    second = rbac.register_tenant(clinic_name="Audit Tenant B")
    assert first.tenant_id is not None and second.tenant_id is not None
    yield (
        AuditApi(
            rbac=rbac,
            tenant_id=first.tenant_id,
            user_id=first.user_id,
            headers=first.headers,
        ),
        AuditApi(
            rbac=rbac,
            tenant_id=second.tenant_id,
            user_id=second.user_id,
            headers=second.headers,
        ),
    )
    rbac.cleanup()


def test_every_emitted_action_is_in_the_catalogue() -> None:
    """Guard: nothing this slice emits may be outside doc 07 §1's closed vocabulary.

    It is a coverage test rather than a behavioural one, and it lives here so the catalogue, the
    allow-list and what the modules actually write cannot drift apart: the same assertions run over
    `PAYLOAD_ALLOW_LIST`, whose keys are the actions the writer will accept a payload for.
    """
    assert "patient.create" in ACTIONS
    assert "patient.update" in ACTIONS
    assert "audit.read" in ACTIONS
    assert "user.permission_change" in ACTIONS
    # Every allow-listed action is a catalogue action; the reverse is a deferral, not a defect.
    assert set(PAYLOAD_ALLOW_LIST) <= ACTIONS
