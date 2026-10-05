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
from app.modules.users_roles import service as users_roles_service
from app.modules.users_roles.policy import Actor

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except InvalidTokenError, ValidationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_actor(current_user: CurrentUser) -> Actor:
    """Build the request's authorisation actor from the verified session.

    The tenant comes from the session row and nowhere else (INV-1); the permission set is resolved by
    the users-and-roles service under that tenant's forced RLS context and is recomputed on every
    request (R2). An authenticated account with no organisation cannot be scoped to a tenant, so it is
    refused `403` here — before the policy layer runs — rather than defaulted.

    The policy layer's own verdict for a missing tenant is `401 NO_IDENTITY`
    (`03-users-and-roles/03-design.md`, "The central policy layer"). `403` is used at this boundary
    because the caller *is* authenticated; the existing patient routes have always answered `403`
    for "no organisation", and changing that is a contract change outside this slice.
    """
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has no organisation",
        )
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
