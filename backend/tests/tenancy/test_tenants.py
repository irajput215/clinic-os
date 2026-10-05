"""The `tenants` table.

Requirements: `docs/features/01-tenancy-and-clinics/01-requirements.md` R2 (status
vocabulary, unique lower-case slug). Design: ".../03-design.md", "Table: tenants
(GLOBAL — no RLS)". The table is global, so these tests exercise the database
constraints directly rather than through row-level security.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select

from app.core.db import engine
from app.modules.identity_tenancy.models import Tenant
from app.modules.identity_tenancy.service import DEMO_TENANT_SLUG, seed_demo_tenant


@pytest.fixture(autouse=True)
def clean_tenants() -> Iterator[None]:
    """Tenants are global, so a leaked row would affect every later test."""
    with Session(engine) as session:
        session.exec(delete(Tenant))
        session.commit()
    yield
    with Session(engine) as session:
        session.exec(delete(Tenant))
        session.commit()


def _tenant(**overrides: Any) -> Tenant:
    fields: dict[str, Any] = {
        "slug": "demo-clinic",
        "legal_name": "Demo Clinic Pty Ltd",
        "retention_profile": "default",
    }
    fields.update(overrides)
    return Tenant(**fields)


def test_tenant_status_controlled_vocabulary() -> None:
    with pytest.raises(IntegrityError, match="ck_tenants_status"):
        with Session(engine) as session:
            session.add(_tenant(status="ARCHIVED"))
            session.commit()


@pytest.mark.parametrize("status", ["ACTIVE", "SUSPENDED", "CLOSING", "CLOSED"])
def test_tenant_accepts_every_status_in_the_vocabulary(status: str) -> None:
    with Session(engine) as session:
        tenant = _tenant(slug=f"clinic-{status.lower()}", status=status)
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
        assert tenant.status == status


def test_tenant_slug_is_unique() -> None:
    with Session(engine) as session:
        session.add(_tenant(slug="duplicate"))
        session.commit()

    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.add(_tenant(slug="duplicate", legal_name="Another Clinic"))
            session.commit()


def test_tenant_slug_must_be_lowercase() -> None:
    with pytest.raises(IntegrityError, match="ck_tenants_slug_lowercase"):
        with Session(engine) as session:
            session.add(_tenant(slug="Demo-Clinic"))
            session.commit()


def test_tenant_defaults_to_active_in_the_australian_region() -> None:
    with Session(engine) as session:
        tenant = _tenant()
        session.add(tenant)
        session.commit()
        session.refresh(tenant)

        assert tenant.status == "ACTIVE"
        assert tenant.data_region == "ap-southeast-2"
        assert tenant.id is not None
        assert tenant.created_at is not None
        assert tenant.updated_at is not None


def test_seed_demo_tenant_is_idempotent() -> None:
    """`initial_data.py` runs on every deploy, so the seed must not duplicate."""
    with Session(engine) as session:
        first = seed_demo_tenant(session)
        second = seed_demo_tenant(session)

        assert first.id == second.id
        assert first.slug == DEMO_TENANT_SLUG
        assert first.status == "ACTIVE"
        assert session.exec(select(Tenant)).all() == [first]


def test_tenant_updated_at_advances_on_change() -> None:
    """A column called `updated_at` that never moves is worse than no column."""
    with Session(engine) as session:
        tenant = _tenant()
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
        created_at = tenant.created_at
        updated_at = tenant.updated_at
        tenant_id = tenant.id

    with Session(engine) as session:
        stored = session.get(Tenant, tenant_id)
        assert stored is not None
        stored.legal_name = "Demo Clinic Pty Ltd (renamed)"
        session.add(stored)
        session.commit()
        session.refresh(stored)

        assert stored.updated_at > updated_at
        assert stored.created_at == created_at
