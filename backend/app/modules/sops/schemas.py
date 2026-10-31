"""SOP request and response shapes (docs3 feature 02, manual §13)."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.users_roles.catalog import SYSTEM_ROLE_CODES

Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Body = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)
]


class SopWrite(BaseModel):
    """A new SOP, or the next version of one. An empty `applies_to_roles` means everyone."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    body: Body
    applies_to_roles: list[str] = Field(
        default_factory=list, max_length=len(SYSTEM_ROLE_CODES)
    )
    required_for_onboarding: bool = False

    @field_validator("applies_to_roles")
    @classmethod
    def _known_roles(cls, roles: list[str]) -> list[str]:
        unknown = sorted(set(roles) - set(SYSTEM_ROLE_CODES))
        if unknown:
            raise ValueError(f"Unknown role code(s): {', '.join(unknown)}")
        return sorted(set(roles))


class SopCard(BaseModel):
    """One SOP in the list, with where the caller stands on it."""

    id: uuid.UUID
    title: str
    applies_to_roles: list[str]
    required_for_onboarding: bool
    current_version: int
    updated_at: datetime
    applies_to_me: bool
    #: The newest version the caller acknowledged, or `None`. Current when it equals `current_version`.
    my_acknowledged_version: int | None


class SopVersionRead(BaseModel):
    version: int
    published_at: datetime
    published_by_name: str | None


class SopDetail(SopCard):
    """The current text and the version history (R6)."""

    body: str
    versions: list[SopVersionRead]


class MatrixSop(BaseModel):
    id: uuid.UUID
    title: str
    current_version: int
    applies_to_roles: list[str]


class MatrixRow(BaseModel):
    user_id: uuid.UUID
    name: str
    role_codes: list[str]
    #: sop id -> the newest version this person acknowledged; absent when none or not applicable.
    acknowledged: dict[uuid.UUID, int]
    #: The SOPs that apply to this person.
    applicable: list[uuid.UUID]


class AcknowledgementMatrix(BaseModel):
    """Staff x SOP x acknowledged version (R8)."""

    sops: list[MatrixSop]
    staff: list[MatrixRow]
