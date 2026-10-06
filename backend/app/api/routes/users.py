import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, func, select

from app import crud
from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.core.config import settings
from app.core.db import tenant_transaction
from app.core.security import get_password_hash, verify_password
from app.models import (
    Message,
    UpdatePassword,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.modules.identity_tenancy.service import create_tenant_for_signup
from app.modules.users_roles import service as users_roles_service
from app.utils import generate_new_account_email, send_email

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve users.
    """

    count_statement = select(func.count()).select_from(User)
    count = session.exec(count_statement).one()

    statement = (
        select(User).order_by(col(User.created_at).desc()).offset(skip).limit(limit)
    )
    users = session.exec(statement).all()

    users_public = [UserPublic.model_validate(user) for user in users]
    return UsersPublic(data=users_public, count=count)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
    """
    Create new user.
    """
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    user = crud.create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        email_data = generate_new_account_email(
            email_to=user_in.email, username=user_in.email, password=user_in.password
        )
        send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    """
    Update own user.
    """

    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    user_data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(user_data)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    """
    Update own password.
    """
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
def read_user_me(current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    return current_user


def _deactivate(session: Session, user: User) -> Message:
    """Soft-deactivate one account, and commit.

    **Deactivation, not deletion** (`docs/features/03-users-and-roles/01-requirements.md` R14: *"A user
    is deactivated, not hard-deleted; clinical attribution survives"*). The row stays, so every
    `user_roles` grant that names this account — as its holder or as the granter — still resolves, and
    so does every audit record that attributes a decision to it. A hard delete is not merely
    discouraged here, it is refused by the schema: both `user_roles` foreign keys are `ON DELETE
    RESTRICT`, which is why `session.delete(user)` raised a foreign-key error for any account that had
    ever granted a role.

    The deactivated account's next request is `401`: `deps.get_current_user` refuses an inactive user,
    which is the contract the client signs out on.
    """
    user.is_active = False
    session.add(user)
    session.commit()
    return Message(message="User deactivated successfully")


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Deactivate own user.

    Kept as `DELETE /users/me` for the clients that call it, but it deactivates: the account and its
    attribution survive, and its next request is `401`.
    """
    if current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    return _deactivate(session, current_user)


@router.post("/signup", response_model=UserPublic)
def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    """
    Register an organisation, or a plain account.

    This is step ① of `docs/reference/business-flow.md`. A `clinic_name` registers the
    organisation and makes the signer its administrator; without one the account is
    created unattached, which is what a platform administrator does.

    Gated by `USERS_OPEN_REGISTRATION`. That is what makes self-registration safe:
    a signup can only ever reach the tenant it just created.

    **Organisation registration is one transaction.** The tenant, the account and the
    Practice Owner grant commit together or not at all, so a failure anywhere leaves no
    half-provisioned account: no organisation without an administrator, and no account
    pointing at an organisation whose roles were never written. Every write runs on the
    one `tenant_transaction` session, which is also what makes the role provisioning's
    forced-RLS inserts legal (`app.tenant_id` is set inside that transaction). The tenant
    id is drawn before the transaction opens so the context can name it.
    """
    if not settings.USERS_OPEN_REGISTRATION:
        raise HTTPException(
            status_code=403,
            detail="Open user registration is forbidden on this server",
        )
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )

    user_create = UserCreate.model_validate(user_in)
    if user_in.clinic_name is None:
        # An unattached account owns no tenant data, so it needs no tenant context and no
        # second write: one insert, one commit.
        return crud.create_user(session=session, user_create=user_create)

    tenant_id = uuid.uuid4()
    new_user = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    with tenant_transaction(tenant_id=tenant_id, actor_id=new_user.id) as tx:
        tenant = create_tenant_for_signup(tx, user_in.clinic_name, tenant_id=tenant_id)
        new_user.tenant_id = tenant.id
        tx.add(new_user)
        tx.flush()
        # Feature 03: the seven system roles are tenant-scoped, so a new organisation needs its own
        # copies, and the signer becomes its Practice Owner. Without this the account would be
        # authenticated but hold no permission and every route would deny it (fail closed).
        users_roles_service.provision_tenant_in_transaction(
            tx, tenant_id=tenant.id, owner_user_id=new_user.id
        )
        # Serialised inside the transaction, while the row is still bound to a live session.
        return UserPublic.model_validate(new_user)


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get a specific user by id.
    """
    user = session.get(User, user_id)
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> Any:
    """
    Update a user.
    """

    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )

    db_user = crud.update_user(session=session, db_user=db_user, user_in=user_in)
    return db_user


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    """
    Deactivate a user.

    Administered offboarding, answered with the route's existing `DELETE` verb: R14, and the reason
    the foreign keys on `user_roles` are `ON DELETE RESTRICT`. Nothing is removed from the database —
    the account, its grants and its audit attribution stay — and the account's next request is `401`.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    return _deactivate(session, user)
