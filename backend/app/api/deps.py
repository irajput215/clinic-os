from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import TokenPayload, User
from app.modules.identity_tenancy import service as identity_tenancy_service
from app.modules.users_roles import service as users_roles_service
from app.modules.users_roles.policy import Actor

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)

# The reason code for "authenticated, but not attached to an organisation". Every refusal in this
# codebase carries a machine-readable code — the policy layer's `DecisionCode`, the users-and-roles
# `LAST_ADMINISTRATOR` — and this boundary answer was the one that did not, so a client could not
# tell "you have no organisation" from "you are not allowed to do this". The patients screen reads
# the code to say what to do next rather than guessing from the status.
NO_ORGANISATION = "NO_ORGANISATION"

# The reason code for "authenticated, in an organisation that may not transact" (R10). One code
# covers every non-`ACTIVE` status — suspended, closing, closed — and a tenant row that cannot be
# read at all, so the refusal discloses nothing about the organisation's state or existence beyond
# the fact the caller's own session already asserts.
TENANT_NOT_ACTIVE = "TENANT_NOT_ACTIVE"


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    """Resolve the session, and answer `401` whenever the session cannot be used.

    Every way a session can be unusable is `401` and only `401`: a token that does not verify, a
    token for an account that no longer exists, and a deactivated account (R5 — *"the deactivated
    user's next request returns `401`"*). This is a contract, not a preference: the client signs out
    on `401` and keeps every other status in the page, so a session problem reported as `403` or
    `404` would leave a signed-in user looking at a screen that will never load. A `403` means the
    opposite thing here — the session is valid and the identity is simply not allowed — and
    `get_actor` below is where that starts.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except InvalidTokenError, ValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session's account no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _refuse_inactive_tenant(current_user: User, session: Session) -> None:
    """Raise `403 TENANT_NOT_ACTIVE` when the account's organisation may not transact (R10).

    One implementation for both boundaries below, so "which statuses pass" cannot drift between them.
    An account with no organisation has no tenant status to enforce and is not this check's business:
    the platform administrator is exactly that account, and `GET /users/me` is how a session
    bootstraps. Tenant-scoped data remains unreachable for it — `get_actor` refuses `NO_ORGANISATION`
    before any tenant query runs.
    """
    if current_user.tenant_id is None:
        return
    if not identity_tenancy_service.tenant_is_active(
        session, tenant_id=current_user.tenant_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": TENANT_NOT_ACTIVE,
                "message": "This organisation is not active",
            },
        )


def get_active_tenant_user(current_user: CurrentUser, session: SessionDep) -> User:
    """An authenticated account whose organisation, if it has one, may transact (R10).

    The session counterpart of `get_actor`: it resolves no permission set, so it is for the
    self-service routes that act on the caller's **own** account (`/users/me`, `/login/test-token`)
    and need no tenant scope. Without it those routes were the last authenticated surface a suspended
    organisation could still reach, which is what R10 — *"refused on every request even with a valid
    unexpired session"* — rules out.

    It is deliberately **not** applied to the superuser-only administration routes (`/users/`,
    `/users/{user_id}`): those are the platform surface, and the platform administrator legitimately
    holds no organisation.
    """
    _refuse_inactive_tenant(current_user, session)
    return current_user


ActiveTenantUser = Annotated[User, Depends(get_active_tenant_user)]


def get_actor(current_user: CurrentUser, session: SessionDep) -> Actor:
    """Build the request's authorisation actor from the verified session.

    The tenant comes from the session row and nowhere else (INV-1); the permission set is resolved by
    the users-and-roles service under that tenant's forced RLS context and is recomputed on every
    request (R2). An authenticated account with no organisation cannot be scoped to a tenant, so it is
    refused `403` here — before the policy layer runs — rather than defaulted.

    **Tenant status is enforced here (R10).** A tenant that is not `ACTIVE` is refused on every
    request that resolves one, even when its account holds a valid, unexpired access token — the
    design's deny-by-default path step 2, *"enforce `status = ACTIVE` at resolution"*. The check is an
    allow-list (`identity_tenancy.service.is_active_status`), so an unknown status fails closed, and a
    tenant row that cannot be read is refused with the same code as a suspended one rather than
    defaulted to active. One code for every non-`ACTIVE` case means the response cannot be used to
    probe whether an organisation exists. `get_active_tenant_user` applies the same check to the
    self-service routes that build no actor.

    The policy layer's own verdict for a missing tenant is `401 NO_IDENTITY`
    (`03-users-and-roles/03-design.md`, "The central policy layer"). `403` is used at this boundary
    because the caller *is* authenticated; the existing patient routes have always answered `403`
    for "no organisation", and changing that is a contract change outside this slice.
    """
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": NO_ORGANISATION,
                "message": "This account has no organisation",
            },
        )
    _refuse_inactive_tenant(current_user, session)
    return users_roles_service.actor_for(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        is_active=current_user.is_active,
    )


ActorDep = Annotated[Actor, Depends(get_actor)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user
