"""Organisation signup, verified by email, with one answer for every address (D-008).

Decision: `docs/reference/decisions/D-008-signup-email-verification.md`. Contract:
`docs2/sdlc/01-auth-and-shell/api.md` (`POST /users/signup`, `/signup/resend`, `/signup/verify`).

1. **Request** (`request_signup`). Every address gets the same answer and the same work, in one
   transaction: look the address up, one Argon2 hash, one `signup_requests` row, purge the expired
   rows, one email. A new address is emailed a verification link; an address that already has an
   account is emailed a notice to sign in or reset the password, its row carries no password and can
   never be verified. Nothing else is written: no tenant, no account.
2. **Resend** (`resend_signup_email`). The same request's email again, with a fresh link (the old one
   is then refused) and a fresh window; nothing for an unknown, expired or used request, or after
   `MAX_EMAILS_PER_REQUEST`. The caller learns nothing either way.
3. **Verify** (`verify_signup`). The link creates the organisation, the account and the Practice Owner
   grant in one transaction (what signup used to do at once), audits `user.create` in the new tenant,
   deletes every request for the address, and answers an access token.

**The link** is a signed token: purpose-bound (its own key, derived from `SECRET_KEY`, and a
`purpose` claim, so it never verifies as a session, an invitation or a reset link), expiring, and
naming one request and the one `link_id` that is current, which is what makes a resend retire the
previous link and verification spend it (the row is deleted).

**Emails carry nothing the requester typed** except the address they were sent to: not the clinic
name, not the person's name. Whoever types an address may not own it, and the email must not carry
their words to whoever does.
"""

import hashlib
import hmac
import html
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app import utils
from app.core import security
from app.core.config import settings
from app.core.db import engine, tenant_transaction
from app.core.security import get_password_hash
from app.models import User
from app.modules.audit import service as audit
from app.modules.identity_tenancy import service as identity_tenancy
from app.modules.users_roles import service as users_roles
from app.modules.users_roles.catalog import BOOTSTRAP_ROLE_CODE, USER_CREATE
from app.modules.users_roles.models import SignupRequest

PURPOSE = "signup-verification"
_KEY_LABEL = b"clinicos/signup-verification/v1"
#: A request's email is sent at most this many times (the first send and four resends), so the
#: resend route cannot be turned on one mailbox.
MAX_EMAILS_PER_REQUEST = 5


def _key() -> bytes:
    """The signing key for verification links, derived from `SECRET_KEY` and used nowhere else."""
    return hmac.new(settings.SECRET_KEY.encode(), _KEY_LABEL, hashlib.sha256).digest()


def _window() -> timedelta:
    return timedelta(hours=settings.SIGNUP_VERIFICATION_EXPIRE_HOURS)


def issue_link_token(*, request: SignupRequest) -> str:
    """Sign the link for a request's current `link_id`, expiring with the request."""
    claims = {
        "sub": str(request.id),
        "jti": str(request.link_id),
        "purpose": PURPOSE,
        "iat": request.sent_at,
        "nbf": request.sent_at,
        "exp": request.expires_at,
    }
    return jwt.encode(claims, _key(), algorithm=security.ALGORITHM)


@dataclass(frozen=True)
class LinkClaims:
    request_id: uuid.UUID
    link_id: uuid.UUID


def read_link_token(token: str) -> LinkClaims | None:
    """The claims of a valid, unexpired verification link, or `None` for anything else (one answer)."""
    try:
        claims = jwt.decode(
            token,
            _key(),
            algorithms=[security.ALGORITHM],
            options={"require": ["sub", "jti", "purpose", "exp", "nbf"]},
        )
        if claims["purpose"] != PURPOSE:
            return None
        return LinkClaims(
            request_id=uuid.UUID(str(claims["sub"])),
            link_id=uuid.UUID(str(claims["jti"])),
        )
    except InvalidTokenError, ValueError:
        return None


# --- Emails ------------------------------------------------------------------------------------


def _escaped(values: dict[str, str]) -> dict[str, str]:
    # `render_email_template` does not autoescape; every value is escaped here.
    return {key: html.escape(value) for key, value in values.items()}


def _send_verification(request: SignupRequest) -> None:
    link = f"{settings.FRONTEND_HOST}/verify-email?token={issue_link_token(request=request)}"
    utils.send_email(
        email_to=request.email,
        subject=f"{settings.PROJECT_NAME} - Confirm your email",
        html_content=utils.render_email_template(
            template_name="signup_verification.html",
            context=_escaped(
                {
                    "project_name": settings.PROJECT_NAME,
                    "email": request.email,
                    "valid_hours": str(settings.SIGNUP_VERIFICATION_EXPIRE_HOURS),
                    "link": link,
                }
            ),
        ),
    )


def _send_notice(request: SignupRequest) -> None:
    utils.send_email(
        email_to=request.email,
        subject=f"{settings.PROJECT_NAME} - You already have an account",
        html_content=utils.render_email_template(
            template_name="signup_existing_account.html",
            context=_escaped(
                {
                    "project_name": settings.PROJECT_NAME,
                    "email": request.email,
                    "login_link": f"{settings.FRONTEND_HOST}/login",
                    "recovery_link": f"{settings.FRONTEND_HOST}/recover-password",
                }
            ),
        ),
    )


def _send(request: SignupRequest) -> None:
    """The request's one email: the link for a new address, the notice for a taken one."""
    if request.hashed_password is None:
        _send_notice(request)
    else:
        _send_verification(request)


# --- Request -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SignupRequested:
    request_id: uuid.UUID


def _email_key(email: str) -> str:
    return email.lower()


def _registered_address(session: Session, email_key: str) -> str | None:
    """The address of the account that already uses this one, case-insensitively (as sign-in
    matches it), or `None`. One statement, whichever the answer."""
    return session.exec(
        select(User.email).where(func.lower(col(User.email)) == email_key).limit(1)
    ).first()


def request_signup(
    *,
    email: str,
    password: str,
    full_name: str | None,
    clinic_name: str | None,
) -> SignupRequested:
    """Record a signup and email it, the same way whether or not the address has an account.

    The two paths differ only in what is stored and which template is rendered: both run the lookup,
    one Argon2 hash (of the chosen password, or of a random secret that is discarded), one insert,
    the purge of expired requests and one email, in one transaction. The email goes last, inside it,
    so a send that raises leaves no request behind.
    """
    now = datetime.now(UTC)
    key = _email_key(email)
    with Session(engine) as session, session.begin():
        registered = _registered_address(session, key)
        taken = registered is not None
        # Hash on both paths, so the expensive step does not tell the two apart.
        verifier = get_password_hash(
            password if not taken else secrets.token_urlsafe(32)
        )
        session.exec(delete(SignupRequest).where(col(SignupRequest.expires_at) < now))
        request = SignupRequest(
            # A notice goes to the address the account holds, exactly as it was registered.
            email=registered or email,
            email_key=key,
            # A request for a taken address keeps nothing the requester typed but the address.
            full_name=None if taken else full_name,
            clinic_name=None if taken else clinic_name,
            hashed_password=None if taken else verifier,
            sent_at=now,
            expires_at=now + _window(),
        )
        session.add(request)
        session.flush()
        _send(request)
        return SignupRequested(request_id=request.id)


def resend_signup_email(*, request_id: uuid.UUID) -> None:
    """Send a request's email again with a fresh link and window; silently nothing otherwise.

    Nothing is sent for an unknown, expired or already-used request, or once the request has had
    `MAX_EMAILS_PER_REQUEST` emails. The previous link names the old `link_id` and is refused from
    now on. A notice request gets the notice again (never a link).
    """
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        request = session.exec(
            select(SignupRequest)
            .where(SignupRequest.id == request_id)
            .with_for_update()
        ).first()
        if (
            request is None
            or request.expires_at <= now
            or request.send_count >= MAX_EMAILS_PER_REQUEST
        ):
            return
        request.link_id = uuid.uuid4()
        request.sent_at = now
        request.expires_at = now + _window()
        request.send_count += 1
        session.add(request)
        session.flush()
        _send(request)


# --- Verify ------------------------------------------------------------------------------------


def _usable(request: SignupRequest | None, claims: LinkClaims) -> bool:
    return (
        request is not None
        and request.hashed_password is not None
        and request.link_id == claims.link_id
        and request.expires_at > datetime.now(UTC)
    )


def _create_account(
    session: Session,
    request: SignupRequest,
    user_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None,
) -> User:
    """Insert the account with its organisation already set.

    The application role holds no `UPDATE` on `user.tenant_id` (an account is never moved between
    organisations), so the tenant is created first and the account is inserted into it.
    """
    assert request.hashed_password is not None
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email=request.email,
        full_name=request.full_name,
        hashed_password=request.hashed_password,
        is_active=True,
        is_superuser=False,
    )
    session.add(user)
    return user


def verify_signup(*, token: str) -> str | None:
    """Spend a verification link: create what the signup asked for and answer an access token.

    `None` is the one answer for a tampered, expired, wrong-purpose, replaced or used link, for a
    notice request, and for an address that has an account by now (another request verified first,
    or an invitation took it): the router answers each the same `400`.

    For a clinic signup the organisation, the account, its Practice Owner grant and the `user.create`
    event are one transaction under the new tenant's context, exactly as signup used to commit them;
    every request for the address is deleted on it too, so no other link for the address can verify.
    """
    claims = read_link_token(token)
    if claims is None:
        return None
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    try:
        with tenant_transaction(
            tenant_id=tenant_id, actor_id=user_id, actor_role=BOOTSTRAP_ROLE_CODE
        ) as session:
            request = session.exec(
                select(SignupRequest)
                .where(SignupRequest.id == claims.request_id)
                .with_for_update()
            ).first()
            if request is None or not _usable(request, claims):
                return None
            if _registered_address(session, request.email_key) is not None:
                return None
            tenant = (
                None
                if request.clinic_name is None
                else identity_tenancy.create_tenant_for_signup(
                    session, request.clinic_name, tenant_id=tenant_id
                )
            )
            user = _create_account(
                session,
                request,
                user_id,
                tenant_id=None if tenant is None else tenant.id,
            )
            if tenant is not None:
                session.flush()
                users_roles.provision_tenant_in_transaction(
                    session, tenant_id=tenant.id, owner_user_id=user.id
                )
                audit.record(
                    session,
                    audit.AuditEvent(
                        action=USER_CREATE,
                        result="SUCCESS",
                        resource_id=user.id,
                        payload={
                            "target_user_id": str(user.id),
                            "added": [BOOTSTRAP_ROLE_CODE],
                            "step_up": False,
                        },
                    ),
                )
            else:
                # An account that belongs to no organisation (what a platform administrator
                # registers): no tenant is created, so the transaction's tenant context names none
                # and there is no tenant-scoped audit trail to write it to. Neither `user` nor
                # `signup_requests` is a tenant table.
                session.flush()
            session.exec(
                delete(SignupRequest).where(
                    col(SignupRequest.email_key) == request.email_key
                )
            )
    except IntegrityError:
        # Two links for one address raced past the check: the unique index on the address refused
        # the second account and everything rolled back. The answer is the spent link's.
        return None
    return security.create_access_token(
        user_id, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
