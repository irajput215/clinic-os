"""The relationship between an account and the organisation it belongs to.

The foreign key is a column; the `Relationship` is ORM wiring on top of it. This asserts the wiring
actually resolves, because a relationship that fails to configure fails at *first use* — which in
production is the request that needed it, not the import that would have caught it earlier.

Design: `docs/features/01-tenancy-and-clinics/03-design.md`, "Table: tenants".
"""

from sqlmodel import Session

from app.core.db import engine
from app.models import User
from app.modules.identity_tenancy.models import Tenant


def test_a_user_belongs_to_a_tenant_and_the_tenant_lists_its_users() -> None:
    with Session(engine) as session:
        tenant = Tenant(
            slug="relationship-clinic",
            legal_name="Relationship Clinic",
            retention_profile="default",
        )
        session.add(tenant)
        session.commit()
        session.refresh(tenant)

        user = User(
            email="clinician@relationship.example",
            hashed_password="not-a-real-hash-in-a-not-a-real-test",
            tenant_id=tenant.id,
        )
        session.add(user)
        session.commit()

        # Both directions of the same relationship, which is what `back_populates` exists to keep
        # consistent: navigating from either side must agree.
        assert user.tenant is not None
        assert user.tenant.id == tenant.id
        assert [member.email for member in tenant.users] == [
            "clinician@relationship.example"
        ]

        session.delete(user)
        session.commit()
        session.delete(tenant)
        session.commit()


def test_an_account_without_an_organisation_has_no_tenant() -> None:
    """The link is nullable on purpose: signup can create an unattached account."""
    with Session(engine) as session:
        user = User(
            email="unattached@relationship.example",
            hashed_password="not-a-real-hash-in-a-not-a-real-test",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        assert user.tenant_id is None
        assert user.tenant is None

        session.delete(user)
        session.commit()
