import uuid
from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import account_context_statement, engine, run_pipelined
from app.core.logging import current_request_id, record_identity
from app.core.server_timing import expose_server_timing
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


@dataclass(frozen=True)
class SessionAccount:
    """The verified session's account, whether its organisation may transact (R10), and its grants.

    `permissions` and `role_codes` are the account's grants in its own organisation, read in the same
    transaction as the account; empty for an account with no organisation.
    """

    user: User
    may_transact: bool
    permissions: frozenset[str]
    role_codes: frozenset[str]


def get_session_account(token: TokenDep) -> SessionAccount:
    """Resolve the session, and answer `401` whenever the session cannot be used.

    Every way a session can be unusable is `401` and only `401`: a token that does not verify, a
    token for an account that no longer exists, and a deactivated account (R5 — *"the deactivated
    user's next request returns `401`"*). This is a contract, not a preference: the client signs out
    on `401` and keeps every other status in the page, so a session problem reported as `403` or
    `404` would leave a signed-in user looking at a screen that will never load. A `403` means the
    opposite thing here — the session is valid and the identity is simply not allowed — and
    `get_actor` below is where that starts.

    Every authenticated request pays this, so it is one round trip
    (`docs/reference/performance.md`): the account, its organisation's status and the account's
    grants are read in one pipelined transaction, and the connection goes back to the pool before
    the route runs. The grants are the actor's permission set for `get_actor`, so the permission set
    is still recomputed from the database on every request (R2). The account is returned detached; a
    route that changes it attaches it to its own session.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        user_id = uuid.UUID(str(token_data.sub))
    except InvalidTokenError, ValidationError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # One flight, one transaction: the account and its organisation's status, the transaction's
    # context resolved by the database from that same account row, the account's grants under that
    # context, and COMMIT. Nothing here is read from the request beyond the verified token (INV-1).
    with Session(engine) as session:
        account_rows, _, grant_rows = run_pipelined(
            session,
            [
                identity_tenancy_service.session_account_statement(user_id),
                account_context_statement(
                    user_id=user_id, request_id=current_request_id()
                ),
                users_roles_service.held_grants_in_context_statement(user_id),
            ],
            commit=True,
        )
    account = identity_tenancy_service.session_account_from_rows(account_rows)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session's account no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user, may_transact = account
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # A verified session may see how long its own request took; an anonymous caller may not
    # (`app/core/server_timing.py`, "What is never recorded").
    expose_server_timing()
    permissions, role_codes = users_roles_service.grants_from_rows(grant_rows)
    record_identity(tenant_id=user.tenant_id, actor_id=user.id)
    return SessionAccount(
        user=user,
        may_transact=may_transact,
        permissions=permissions,
        role_codes=role_codes,
    )


SessionAccountDep = Annotated[SessionAccount, Depends(get_session_account)]


def get_current_user(account: SessionAccountDep) -> User:
    """The verified session's account (see `get_session_account` for every `401`)."""
    return account.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _refuse_inactive_tenant(account: SessionAccount) -> None:
    """Raise `403 TENANT_NOT_ACTIVE` when the account's organisation may not transact (R10).

    One implementation for both boundaries below, so "which statuses pass" cannot drift between them.
    An account with no organisation has no tenant status to enforce and is not this check's business:
    the platform administrator is exactly that account, and `GET /users/me` is how a session
    bootstraps. Tenant-scoped data remains unreachable for it — `get_actor` refuses `NO_ORGANISATION`
    before any tenant query runs. The status was read with the account, in the same statement
    (`identity_tenancy.service.session_account`).
    """
    if not account.may_transact:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": TENANT_NOT_ACTIVE,
                "message": "This organisation is not active",
            },
        )


def get_active_tenant_user(account: SessionAccountDep) -> User:
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
    _refuse_inactive_tenant(account)
    return account.user


ActiveTenantUser = Annotated[User, Depends(get_active_tenant_user)]


def get_actor(account: SessionAccountDep) -> Actor:
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
    current_user = account.user
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": NO_ORGANISATION,
                "message": "This account has no organisation",
            },
        )
    _refuse_inactive_tenant(account)
    # The grants were read with the account, under this tenant's context, in this request
    # (`get_session_account`): recomputed per request, never cached (R2).
    return Actor(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        is_active=current_user.is_active,
        permissions=account.permissions,
        role_codes=account.role_codes,
    )


ActorDep = Annotated[Actor, Depends(get_actor)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user
