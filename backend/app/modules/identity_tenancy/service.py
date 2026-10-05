"""Tenant service facade.

Everything outside this package reaches `tenants` through here
(`docs/reference/build-contract.md` §7: a module owns its tables).
"""

from sqlmodel import Session, select

from app.modules.identity_tenancy.models import Tenant

# Demo seed. The MVP needs one organisation to hang patients and approvals from;
# the real onboarding path is feature 01's tenancy administration, which is not
# built yet. `retention_profile` names a retention schedule — none exists yet
# (open item L2, retention by state and territory), so the seed uses a placeholder.
DEMO_TENANT_SLUG = "demo-clinic"
DEMO_TENANT_LEGAL_NAME = "Demo Clinic Pty Ltd"
DEMO_RETENTION_PROFILE = "default"


def get_tenant_by_slug(session: Session, slug: str) -> Tenant | None:
    return session.exec(select(Tenant).where(Tenant.slug == slug)).first()


def seed_demo_tenant(session: Session) -> Tenant:
    """Create the demo tenant if it is absent. Idempotent: startup calls it every run."""
    existing = get_tenant_by_slug(session, DEMO_TENANT_SLUG)
    if existing is not None:
        return existing

    tenant = Tenant(
        slug=DEMO_TENANT_SLUG,
        legal_name=DEMO_TENANT_LEGAL_NAME,
        retention_profile=DEMO_RETENTION_PROFILE,
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant
