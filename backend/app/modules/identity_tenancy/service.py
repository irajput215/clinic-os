"""Tenant service facade.

Everything outside this package reaches `tenants` through here
(`docs/reference/build-contract.md` §7: a module owns its tables).

The flow this implements is step ① of `docs/reference/business-flow.md`: a clinic
registers, which creates its organisation and makes the signer its administrator.
"""

import re

from sqlmodel import Session, select

from app.modules.identity_tenancy.models import Tenant

# `retention_profile` names a retention schedule — none exists yet (open item L2,
# retention by state and territory), so both paths use a placeholder.
DEFAULT_RETENTION_PROFILE = "default"

DEMO_TENANT_SLUG = "demo-clinic"
DEMO_TENANT_LEGAL_NAME = "Demo Clinic Pty Ltd"


def get_tenant_by_slug(session: Session, slug: str) -> Tenant | None:
    return session.exec(select(Tenant).where(Tenant.slug == slug)).first()


def slugify(clinic_name: str) -> str:
    """A routing slug: lower-case, hyphenated, within the column's 64 characters.

    The slug is routing only and never an authorisation input
    (`docs/features/01-tenancy-and-clinics/03-design.md`).
    """
    slug = re.sub(r"[^a-z0-9]+", "-", clinic_name.lower()).strip("-")
    return slug[:64] or "organisation"


def create_tenant_for_signup(session: Session, clinic_name: str) -> Tenant:
    """Register an organisation. Two clinics may share a name, so the slug is uniqued."""
    base = slugify(clinic_name)
    slug = base
    suffix = 2
    while get_tenant_by_slug(session, slug) is not None:
        slug = f"{base[:59]}-{suffix}"
        suffix += 1

    tenant = Tenant(
        slug=slug,
        legal_name=clinic_name,
        retention_profile=DEFAULT_RETENTION_PROFILE,
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


def seed_demo_tenant(session: Session) -> Tenant:
    """Create the demo tenant if it is absent. Idempotent: startup calls it every run."""
    existing = get_tenant_by_slug(session, DEMO_TENANT_SLUG)
    if existing is not None:
        return existing

    tenant = Tenant(
        slug=DEMO_TENANT_SLUG,
        legal_name=DEMO_TENANT_LEGAL_NAME,
        retention_profile=DEFAULT_RETENTION_PROFILE,
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant
