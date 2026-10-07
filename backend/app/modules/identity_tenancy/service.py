"""Tenant service facade.

Everything outside this package reaches `tenants` through here
(`docs/reference/build-contract.md` §7: a module owns its tables).

The flow this implements is step ① of `docs/reference/business-flow.md`: a clinic
registers, which creates its organisation and makes the signer its administrator.

`create_tenant_for_signup` writes the organisation on **the caller's session and never commits**:
registration is one transaction, owned by the route, so the tenant, the account and the Practice
Owner grant either all exist or none does (see `app/api/routes/users.py`, `POST /users/signup`).
"""

import re
import uuid
from collections.abc import Iterator
from itertools import islice

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.identity_tenancy.models import Tenant

# `retention_profile` names a retention schedule — none exists yet (open item L2,
# retention by state and territory), so both paths use a placeholder.
DEFAULT_RETENTION_PROFILE = "default"

DEMO_TENANT_SLUG = "demo-clinic"
DEMO_TENANT_LEGAL_NAME = "Demo Clinic Pty Ltd"

# The unique index behind "two clinics may share a name": `Field(unique=True, index=True)` renders as
# a unique index under the naming convention (`app.core.metadata`), and PostgreSQL reports the index
# name in the violation. Only this one uniqueness violation is retried — an email collision is a
# different fact about a different table and must not be masked by a slug retry.
TENANT_SLUG_UNIQUE_INDEX = "ix_tenants_slug"

# A bound, not `while True`: a pathological run of collisions fails closed instead of spinning.
MAX_SLUG_ATTEMPTS = 100

# The only status that may transact. R10 (`docs/features/01-tenancy-and-clinics/01-requirements.md`):
# a `SUSPENDED` tenant is refused on every request, even with a valid unexpired session; the design's
# deny-by-default path enforces `status = ACTIVE` at resolution. The check is an allow-list rather
# than a deny-list of `SUSPENDED`/`CLOSED`, so a status added to the vocabulary later — or a value the
# database somehow holds — fails closed instead of being admitted by omission.
ACTIVE_STATUS = "ACTIVE"


def is_active_status(status: str | None) -> bool:
    """`True` only for the literal `ACTIVE`. Fails closed on anything else, including unknown values."""
    return status == ACTIVE_STATUS


def get_tenant_by_slug(session: Session, slug: str) -> Tenant | None:
    return session.exec(select(Tenant).where(Tenant.slug == slug)).first()


def tenant_is_active(session: Session, *, tenant_id: uuid.UUID) -> bool:
    """Whether the tenant this request resolved is allowed to transact.

    `tenants` is global (no RLS), so this is a plain read. A tenant row that cannot be read is
    refused exactly as a non-`ACTIVE` one is: the boundary answers one code for both, so the
    response cannot disclose whether the organisation exists.
    """
    tenant = session.get(Tenant, tenant_id)
    return tenant is not None and is_active_status(tenant.status)


def tenant_display_name(session: Session, *, tenant_id: uuid.UUID) -> str | None:
    """The organisation's name as its own staff see it, or `None` when the row cannot be read.

    For the caller's **own** resolved tenant only (a staff invitation names the clinic the invitee
    is joining). `tenants` is global with no RLS, so the caller must pass the tenant the session
    resolved and never a request value.
    """
    tenant = session.get(Tenant, tenant_id)
    return None if tenant is None else tenant.legal_name


def slugify(clinic_name: str) -> str:
    """A routing slug: lower-case, hyphenated, within the column's 64 characters.

    The slug is routing only and never an authorisation input
    (`docs/features/01-tenancy-and-clinics/03-design.md`).
    """
    slug = re.sub(r"[^a-z0-9]+", "-", clinic_name.lower()).strip("-")
    return slug[:64] or "organisation"


def _slug_candidates(base: str) -> Iterator[str]:
    """The deterministic sequence of slugs one clinic name may take: `base`, `base-2`, `base-3`, …"""
    yield base
    suffix = 2
    while True:
        yield f"{base[:59]}-{suffix}"
        suffix += 1


def _is_slug_collision(error: IntegrityError) -> bool:
    """Whether this uniqueness violation is the tenant slug's, and so is the one signup retries."""
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    return getattr(diagnostic, "constraint_name", None) == TENANT_SLUG_UNIQUE_INDEX


def create_tenant_for_signup(
    session: Session, clinic_name: str, *, tenant_id: uuid.UUID | None = None
) -> Tenant:
    """Create the organisation, inside the caller's transaction. **The caller commits.**

    Two clinics may share a name, so the slug is uniqued rather than rejected. Uniqueness is decided
    by the database, not by a read-then-write check: the read can be stale between two concurrent
    signups, and the unique index is the only authority. Each attempt runs in a savepoint, so a
    collision rolls back exactly that attempt — the caller's transaction stays usable and keeps
    everything already written to it. A violation on any other constraint is raised, not retried.

    `tenant_id` may be pre-generated by the caller so it can open the tenant's transaction (and set
    `app.tenant_id`) before the row exists; the row rolled back on a collision is retried under the
    same id, which is free again once the savepoint rolls back.
    """
    base = slugify(clinic_name)
    for slug in islice(_slug_candidates(base), MAX_SLUG_ATTEMPTS):
        try:
            with session.begin_nested():
                tenant = Tenant(
                    id=tenant_id if tenant_id is not None else uuid.uuid4(),
                    slug=slug,
                    legal_name=clinic_name,
                    retention_profile=DEFAULT_RETENTION_PROFILE,
                )
                session.add(tenant)
                session.flush()
        except IntegrityError as error:
            if not _is_slug_collision(error):
                raise
            continue
        return tenant

    # Fail closed rather than loop or invent a slug the caller did not ask for.
    raise RuntimeError(
        f"could not find a free tenant slug for {clinic_name!r} in {MAX_SLUG_ATTEMPTS} attempts"
    )


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
