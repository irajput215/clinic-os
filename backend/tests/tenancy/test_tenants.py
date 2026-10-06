"""The `tenants` table.

Requirements: `docs/features/01-tenancy-and-clinics/01-requirements.md` R2 (status
vocabulary, unique lower-case slug). Design: ".../03-design.md", "Table: tenants
(GLOBAL — no RLS)". The table is global, so these tests exercise the database
constraints directly rather than through row-level security.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select

from app.core.config import settings
from app.core.db import engine
from app.models import User
from app.modules.identity_tenancy import service as identity_tenancy_service
from app.modules.identity_tenancy.models import Tenant
from app.modules.identity_tenancy.service import (
    DEMO_TENANT_SLUG,
    seed_demo_tenant,
    slugify,
)
from app.modules.users_roles import service as users_roles_service
from app.modules.users_roles.models import Role, RolePermission, UserRole

# Every table one organisation signup writes. The atomicity test compares these counts.
_COUNTED_TABLES = ("tenants", "roles", "role_permissions", "user_roles", '"user"')


def _row_counts() -> dict[str, int]:
    """Row counts for the registration tables, read as the owner (no RLS filter)."""
    with engine.connect() as conn:
        return {
            table: int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
            for table in _COUNTED_TABLES
        }


def _clear_tenants(session: Session) -> None:
    """Remove tenants and the rows that reference them.

    `roles` and the grant tables carry `ON DELETE RESTRICT` to `tenants` by design, so a tenant with
    a seeded role bundle cannot be deleted until its RBAC rows are gone. That ordering is the test's
    to get right — production never deletes a tenant.
    """
    session.exec(delete(UserRole))
    session.exec(delete(RolePermission))
    session.exec(delete(Role))
    session.exec(delete(Tenant))


@pytest.fixture(autouse=True)
def clean_tenants() -> Iterator[None]:
    """Tenants are global, so a leaked row would affect every later test."""
    with Session(engine) as session:
        _clear_tenants(session)
        session.commit()
    yield
    with Session(engine) as session:
        _clear_tenants(session)
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


def test_slugify_produces_a_lowercase_routing_slug() -> None:
    assert slugify("Northside Family Clinic") == "northside-family-clinic"
    assert slugify("  St. Mary's  Hospital!! ") == "st-mary-s-hospital"
    assert slugify("!!!") == "organisation"


def test_signup_registers_an_organisation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step ① of docs/reference/business-flow.md."""
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)
    clinic_name = f"Northside Clinic {uuid.uuid4()}"

    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": f"admin-{uuid.uuid4()}@example.com",
            "password": "correct-horse-battery",
            "full_name": "Clinic Administrator",
            "clinic_name": clinic_name,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] is not None

    with Session(engine) as session:
        tenant = session.get(Tenant, uuid.UUID(body["tenant_id"]))
        assert tenant is not None
        assert tenant.legal_name == clinic_name
        assert tenant.slug == slugify(clinic_name)
        assert tenant.status == "ACTIVE"


def test_two_clinics_may_share_a_name(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name is not an identifier, so the slug is uniqued rather than rejected."""
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)
    payload = {
        "password": "correct-horse-battery",
        "full_name": "Clinic Administrator",
        "clinic_name": "Riverside Medical Centre",
    }

    slugs = []
    for _ in range(2):
        response = client.post(
            f"{settings.API_V1_STR}/users/signup",
            json={**payload, "email": f"admin-{uuid.uuid4()}@example.com"},
        )
        assert response.status_code == 200
        with Session(engine) as session:
            tenant = session.get(Tenant, uuid.UUID(response.json()["tenant_id"]))
            assert tenant is not None
            slugs.append(tenant.slug)

    assert slugs[0] == "riverside-medical-centre"
    assert slugs[1] != slugs[0]


def test_slug_suffixes_are_deterministic(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Collisions are resolved by the unique index, and the retry sequence is fixed, not random."""
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)

    slugs = []
    for _ in range(3):
        response = client.post(
            f"{settings.API_V1_STR}/users/signup",
            json={
                "email": f"admin-{uuid.uuid4()}@example.com",
                "password": "correct-horse-battery",
                "full_name": "Clinic Administrator",
                "clinic_name": "Deterministic Clinic",
            },
        )
        assert response.status_code == 200
        with Session(engine) as session:
            tenant = session.get(Tenant, uuid.UUID(response.json()["tenant_id"]))
            assert tenant is not None
            slugs.append(tenant.slug)

    assert slugs == [
        "deterministic-clinic",
        "deterministic-clinic-2",
        "deterministic-clinic-3",
    ]


def test_slug_retry_is_bounded_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry sequence has a terminus: it refuses rather than inventing a slug."""
    with Session(engine) as session:
        session.add(_tenant(slug="bounded-clinic"))
        session.commit()

    monkeypatch.setattr(identity_tenancy_service, "MAX_SLUG_ATTEMPTS", 1)

    with (
        Session(engine) as session,
        pytest.raises(RuntimeError, match="free tenant slug"),
    ):
        identity_tenancy_service.create_tenant_for_signup(session, "Bounded Clinic")


def test_a_failure_after_the_account_is_created_leaves_nothing_behind(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Organisation signup is one transaction: nothing half-provisioned survives a mid-way failure.

    The failure is injected at the step after the account row has been written — the Practice Owner
    grant — so the test proves the *whole* unit rolls back: the organisation, the account, the seven
    role bundles and the grant. Before this change the tenant was committed before the account and the
    grant ran in a third transaction, so this failure left an organisation with no administrator.
    """
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)
    email = f"admin-{uuid.uuid4()}@example.com"
    clinic_name = f"Halfway Clinic {uuid.uuid4()}"
    before = _row_counts()

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected failure after the account row was written")

    monkeypatch.setattr(users_roles_service, "provision_tenant_in_transaction", explode)

    with pytest.raises(RuntimeError, match="injected failure"):
        client.post(
            f"{settings.API_V1_STR}/users/signup",
            json={
                "email": email,
                "password": "correct-horse-battery",
                "full_name": "Clinic Administrator",
                "clinic_name": clinic_name,
            },
        )

    # Every table the registration writes is back where it started: no orphan organisation, account,
    # role, permission bundle or grant.
    assert _row_counts() == before
    with Session(engine) as session:
        assert (
            session.exec(select(Tenant).where(Tenant.legal_name == clinic_name)).first()
            is None
        )
        assert session.exec(select(User).where(User.email == email)).first() is None


def test_signup_without_a_clinic_name_creates_an_unattached_account(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The platform administrator's path: an account with no organisation."""
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)

    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": f"staff-{uuid.uuid4()}@example.com",
            "password": "correct-horse-battery",
            "full_name": "Platform Operator",
        },
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] is None
