"""Tenant service facade.

Everything outside this package reaches `tenants` through here
(`docs/reference/build-contract.md` §7: a module owns its tables).

The flow this implements is step ① of `docs/reference/business-flow.md`: a clinic
registers, which creates its organisation and makes the signer its administrator.

`create_tenant_for_signup` writes the organisation on **the caller's session and never commits**:
registration is one transaction, owned by the route, so the tenant, the account and the Practice
Owner grant either all exist or none does (see `app/api/routes/users.py`, `POST /users/signup`).
"""

import hashlib
import re
import secrets
import uuid
from collections.abc import Iterator
from itertools import islice
from typing import Final

from sqlalchemy import func, insert, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.db import tenant_transaction
from app.core.security import verify_password
from app.crud import DUMMY_HASH
from app.models import User

# The audit module is reached through its service facade (`docs/reference/build-contract.md` §7).
from app.modules.audit import service as audit
from app.modules.identity_tenancy.models import (
    STEP_UP_MAX_LIFETIME_SECONDS,
    StepUpGrant,
    Tenant,
)
from app.modules.identity_tenancy.schemas import StepUpGrantRead

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


def active_tenant_id_for_slug(session: Session, slug: str) -> uuid.UUID | None:
    """The tenant an unauthenticated public route serves, resolved **server-side** from its slug.

    The slug is routing only, never an authorisation input (`01-tenancy-and-clinics/03-design.md`):
    it chooses *which* clinic's public booking page is asked for and grants nothing - no session, no
    permission, no read of anything but that clinic's free slots. Only an `ACTIVE` organisation is
    returned; an unknown slug and a suspended, closing or closed organisation all answer `None`, so the
    caller's `404` is uniform and discloses neither existence nor status.
    """
    tenant = get_tenant_by_slug(session, slug)
    if tenant is None or not is_active_status(tenant.status):
        return None
    return tenant.id


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


# --------------------------------------------------------------------------------------------
# Step-up: a fresh factor for one operation on one resource (interim, ADR-F002)
# --------------------------------------------------------------------------------------------
#
# `docs/features/02-authentication/03-design.md` "Step-up for the five named high-risk operations":
# *"A step-up token is bound to user + session + operation + resource id, consumed on use, refused on
# a different resource, and a failure is audited."* D-003 (the identity model: MFA, sessions) is open,
# so the factor here is the interim ADR-F002 names - re-entering the account password - and the
# server, not the browser, checks it. What D-003 changes is the factor (`_factor_verified`); the
# grant, its binding and its consumption stay.
#
# Two deliberate deviations, recorded in the PR:
#
# - **Not bound to a session.** The platform issues stateless access tokens with no session record
#   (D-003), so there is no session id to bind to. The grant is bound to the user, the operation and
#   the resource, lives two minutes, and is spent once.
# - **`403 STEP_UP_REQUIRED`, not `401`.** Feature 02 owns step-up and answers `403` with a challenge;
#   features 10 and 11 write `401 step_up_required`. The client signs out on any `401`
#   (`app.api.deps.get_current_user`), so a `401` would end the session of a clinician who mistyped a
#   password. `STEP_UP_REQUIRED` is the code `identity_tenancy.router` already uses for the same refusal.

STEP_UP_ACTION: Final[str] = "auth.step_up"
STEP_UP_FAILED_ACTION: Final[str] = "auth.step_up_failed"
STEP_UP_REQUIRED: Final[str] = "STEP_UP_REQUIRED"
STEP_UP_FAILED: Final[str] = "STEP_UP_FAILED"
# What the trail records as the factor, so nobody mistakes the interim for MFA (ADR-F002).
STEP_UP_METHOD: Final[str] = "PASSWORD_REENTRY"


def _token_hash(token: str) -> str:
    """The only form of a step-up token the database ever holds."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _record_step_up(
    session: Session,
    *,
    action: str,
    result: str,
    operation: str,
    resource_id: uuid.UUID,
    reason: str | None = None,
) -> None:
    payload: dict[str, str] = {"operation": operation}
    if action == STEP_UP_ACTION:
        payload["mfa_method"] = STEP_UP_METHOD
    audit.record(
        session,
        audit.AuditEvent(
            action=action,
            result=result,
            resource_id=resource_id,
            reason=reason,
            payload=payload,
        ),
    )


def _factor_verified(session: Session, *, user_id: uuid.UUID, password: str) -> bool:
    """Does `password` verify against this account's current hash? Constant-ish time either way.

    The hash is read by primary key from the session's own account. A rehash suggested by the hasher
    is **not** written here: a step-up must not change the credential it is checking.
    """
    user = session.get(User, user_id)
    hashed = user.hashed_password if user is not None and user.is_active else None
    verified, _rehash = verify_password(password, hashed or DUMMY_HASH)
    return verified and hashed is not None


def issue_step_up(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    actor_role: str | None,
    password: str,
    operation: str,
    resource_id: uuid.UUID,
) -> StepUpGrantRead | None:
    """Check the factor and, on success, store a grant and return its token. `None` is a refusal.

    Both outcomes are audited on the transaction that decides them: `auth.step_up` with the method,
    or `auth.step_up_failed` with the operation. The refusal commits (it is returned, not raised), so
    a guessing attack leaves its trail even though the caller is told nothing beyond "not verified".
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=user_id, actor_role=actor_role
    ) as session:
        if not _factor_verified(session, user_id=user_id, password=password):
            _record_step_up(
                session,
                action=STEP_UP_FAILED_ACTION,
                result="DENIED",
                operation=operation,
                resource_id=resource_id,
                reason=STEP_UP_FAILED,
            )
            return None
        token = secrets.token_urlsafe(32)
        table = StepUpGrant.metadata.tables[StepUpGrant.__tablename__]
        expires_at = (
            session.connection()
            .execute(
                insert(table)
                .values(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    operation=operation,
                    resource_id=resource_id,
                    token_hash=_token_hash(token),
                    # The database clock decides both ends, so the window cannot be widened by an
                    # application instance whose clock is ahead.
                    issued_at=func.now(),
                    expires_at=func.now()
                    + text(f"interval '{STEP_UP_MAX_LIFETIME_SECONDS} seconds'"),
                )
                .returning(table.c.expires_at)
            )
            .scalar_one()
        )
        _record_step_up(
            session,
            action=STEP_UP_ACTION,
            result="SUCCESS",
            operation=operation,
            resource_id=resource_id,
        )
        return StepUpGrantRead(
            step_up_token=token,
            operation=operation,
            resource_id=resource_id,
            expires_at=expires_at,
        )


def consume_step_up(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    operation: str,
    resource_id: uuid.UUID,
    token: str | None,
) -> bool:
    """Spend a grant on the **caller's** transaction. `True` exactly once per grant.

    One conditional `UPDATE`: the row must be this tenant's, this user's, for this operation and this
    resource, unspent, and unexpired by the database clock. Two concurrent spends of one token
    serialise on the row and the second matches nothing. The spend commits or rolls back with the
    operation it authorised, so an operation that fails with an error leaves the grant usable for its
    retry, and one that is refused (a committed refusal) spends it.

    A refusal is audited here, as `auth.step_up_failed` with `STEP_UP_REQUIRED`.
    """
    spent = False
    if token:
        table = StepUpGrant.metadata.tables[StepUpGrant.__tablename__]
        spent = (
            session.connection()
            .execute(
                update(table)
                .where(
                    table.c.token_hash == _token_hash(token),
                    table.c.tenant_id == tenant_id,
                    table.c.user_id == user_id,
                    table.c.operation == operation,
                    table.c.resource_id == resource_id,
                    table.c.consumed_at.is_(None),
                    table.c.expires_at > func.now(),
                )
                .values(consumed_at=func.now())
                .returning(table.c.id)
            )
            .first()
            is not None
        )
    if not spent:
        _record_step_up(
            session,
            action=STEP_UP_FAILED_ACTION,
            result="DENIED",
            operation=operation,
            resource_id=resource_id,
            reason=STEP_UP_REQUIRED,
        )
    return spent
