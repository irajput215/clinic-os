"""The tenant-scoped transaction helper.

`docs/features/01-tenancy-and-clinics/03-design.md` §"The connection-pool hazard":
tenant context is set inside the transaction that runs the query and nowhere else,
and the helper refuses to open without context.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.core.db import TenantContextRequired, engine, tenant_transaction


def _current_tenant_setting(session: Session) -> str | None:
    return session.exec(text("SELECT current_setting('app.tenant_id', true)")).scalar()


def test_tenant_transaction_requires_tenant_context() -> None:
    with pytest.raises(TenantContextRequired):
        with tenant_transaction(tenant_id=None):
            pytest.fail("the transaction must not open without tenant context")


def test_tenant_transaction_sets_context_inside_the_transaction() -> None:
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, request_id="req_test"
    ) as session:
        assert _current_tenant_setting(session) == str(tenant_id)
        assert session.exec(
            text("SELECT current_setting('app.actor_id', true)")
        ).scalar() == str(actor_id)
        assert (
            session.exec(
                text("SELECT current_setting('app.request_id', true)")
            ).scalar()
            == "req_test"
        )


def test_tenant_context_does_not_survive_the_transaction() -> None:
    """After the block, a fresh checkout sees no tenant context.

    This guards the `SET LOCAL` choice against a regression to a session-level
    `SET`. The concurrent pooled proof is task T1-20.
    """
    with tenant_transaction(tenant_id=uuid.uuid4()) as session:
        assert _current_tenant_setting(session) is not None

    with Session(engine) as session:
        assert _current_tenant_setting(session) in (None, "")


def test_tenant_transaction_clears_context_when_the_body_raises() -> None:
    tenant_id = uuid.uuid4()

    with pytest.raises(ValueError, match="boom"):
        with tenant_transaction(tenant_id=tenant_id) as session:
            assert _current_tenant_setting(session) == str(tenant_id)
            raise ValueError("boom")

    with Session(engine) as session:
        assert _current_tenant_setting(session) in (None, "")
