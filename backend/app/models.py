import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from pydantic import EmailStr
from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

# The naming convention must be applied before this module defines any table.
from app.core.metadata import NAMING_CONVENTION  # noqa: F401

if TYPE_CHECKING:
    from app.modules.identity_tenancy.models import Tenant


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    # The organisation being registered. When present, the signup creates the tenant
    # and makes the signer its administrator; the API keeps it optional so a platform
    # administrator can still create an unattached account.
    clinic_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    # The organisation this account belongs to. Nullable for now: the platform
    # administrator predates tenancy, and `tenants` is global rather than row-secured,
    # so the column is a link rather than an isolation boundary. Enforcing it belongs
    # with the first tenant-scoped table (patients), not with this one.
    # SET NULL: closing an organisation must not fail because an account pointed at it.
    tenant_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="tenants.id",
        index=True,
        ondelete="SET NULL",
    )
    # The reverse of `Tenant.users`. `SET NULL` is the rule on the column above, so removing an
    # organisation detaches its accounts instead of refusing the delete or destroying them.
    #
    # `Optional[...]` rather than `Tenant | None`: SQLAlchemy resolves a relationship's target from
    # the annotation, and `Tenant | None` is looked up as a class literally named "Tenant | None".
    # The quotes stay because `Tenant` is imported only under TYPE_CHECKING — unquoting it would make
    # this a runtime cross-module import, which build-contract §7 rules out ("no module reaches into
    # another module's tables"). The foreign key above names the same table by string, for the same
    # reason.
    #
    # NOTE: this is a one-line change to the legacy template layer, which AGENTS.md freezes. The
    # module map (build-contract §7) gives `users` to the `users_roles` module, so the whole `User`
    # model is due to move to `app/modules/users_roles/models.py`; when it does, this relationship
    # moves with it. Recorded in docs/progress.md §4 rather than left as a silent exception.
    tenant: Optional["Tenant"] = Relationship(back_populates="users")  # noqa: UP037, UP045


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None
    tenant_id: uuid.UUID | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
