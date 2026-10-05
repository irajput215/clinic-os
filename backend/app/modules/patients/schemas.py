"""Request and response schemas for the patients module.

Design: `docs/features/05-patients/03-design.md`, "Deny-by-default request path" step 6
("validate the body against a strict Pydantic v2 schema (extra fields forbidden, so
`tenant_id` is rejected)") and step 8 ("serialise through a declared response model").

Every model here is strict — `extra="forbid"` — so a body carrying `tenant_id`,
`deleted_at`, `merged_into_patient_id`, `id`, a blind index or any other column the
design does not expose is a `422` rather than a quietly ignored field (requirement R2).

Two things are deliberately absent, and both are load-bearing:

- **No request schema accepts a tenant identifier.** The tenant is resolved from the
  authenticated session and from nowhere else (INV-1), so a `tenant_id` in a body is an
  unknown field and is rejected before any query runs.
- **No response schema carries an identifier.** `medicare_number`, `ihi` and both blind
  indexes are not declared here, so they cannot be serialised even by accident. This
  slice exposes no identifier value at all; requirement R9's mask (`•••• ` + last three)
  becomes relevant only when one is added.

`deceased_at` is exposed because it is an ordinary clinical attribute of the record, not
an identifier. The rules that *act* on it (blocking operations) are not in this slice.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import AfterValidator, EmailStr, Field, model_validator
from sqlmodel import SQLModel

# PRIVATE API, deliberately. SQLModel annotates `model_config` as `SQLModelConfig`,
# so a plain `ConfigDict` is rejected by BOTH mypy --strict and ty; this is the only
# spelling that satisfies both. It can break on a SQLModel upgrade, so it is recorded
# in docs/progress.md §4 rather than left as an unexplained import.
from sqlmodel._compat import SQLModelConfig

from app.modules.patients.models import SEX_AT_BIRTH_VOCABULARY


def _check_sex_at_birth(value: str) -> str:
    """Validate against the model's own vocabulary so the two cannot drift."""
    if value not in SEX_AT_BIRTH_VOCABULARY:
        raise ValueError(
            f"sex_at_birth must be one of: {', '.join(SEX_AT_BIRTH_VOCABULARY)}"
        )
    return value


SexAtBirth = Annotated[str, AfterValidator(_check_sex_at_birth)]

# The columns the database declares NOT NULL. A PATCH may not clear one by sending an
# explicit `null`: the alternative is an IntegrityError surfacing as a `500`, which is a
# server fault reported for a client error.
_REQUIRED_ON_WRITE = ("given_name", "family_name", "date_of_birth")


class PatientCreate(SQLModel):
    """The body of `POST /api/v1/patients`.

    There is no `tenant_id` field and there never will be: `extra="forbid"` turns one into
    a `422` (INV-1). Identifier columns are absent for the same reason — their key custody
    is an open item (`04-database-erd.md` open item 5), so no value is accepted yet.
    """

    model_config = SQLModelConfig(extra="forbid", str_strip_whitespace=True)

    given_name: str = Field(min_length=1, max_length=255)
    family_name: str = Field(min_length=1, max_length=255)
    preferred_name: str | None = Field(default=None, max_length=255)
    date_of_birth: date
    sex_at_birth: SexAtBirth | None = None
    gender_identity: str | None = Field(default=None, max_length=255)
    address_line: str | None = Field(default=None, max_length=255)
    suburb: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=64)
    postcode: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=64)
    email: EmailStr | None = Field(default=None, max_length=255)
    deceased_at: datetime | None = None


class PatientUpdate(SQLModel):
    """The body of `PATCH /api/v1/patients/{patient_id}`.

    Every field is optional and applied with `exclude_unset`, so an omitted field is left
    alone and an explicit `null` clears a nullable one. A `null` for a NOT NULL column is
    rejected here rather than at the database.
    """

    model_config = SQLModelConfig(extra="forbid", str_strip_whitespace=True)

    given_name: str | None = Field(default=None, min_length=1, max_length=255)
    family_name: str | None = Field(default=None, min_length=1, max_length=255)
    preferred_name: str | None = Field(default=None, max_length=255)
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth | None = None
    gender_identity: str | None = Field(default=None, max_length=255)
    address_line: str | None = Field(default=None, max_length=255)
    suburb: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=64)
    postcode: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=64)
    email: EmailStr | None = Field(default=None, max_length=255)
    deceased_at: datetime | None = None

    @model_validator(mode="after")
    def _reject_clearing_a_required_column(self) -> Self:
        for name in _REQUIRED_ON_WRITE:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} may not be cleared")
        return self


class PatientRead(SQLModel):
    """A patient as the API returns it.

    `from_attributes` lets the service hand over a declared model rather than a raw ORM
    entity. No identifier column and no `tenant_id` is declared: the caller already knows
    its own tenant, and nothing that is not needed is exposed.
    """

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    id: uuid.UUID
    given_name: str
    family_name: str
    preferred_name: str | None = None
    date_of_birth: date
    sex_at_birth: str | None = None
    gender_identity: str | None = None
    address_line: str | None = None
    suburb: str | None = None
    state: str | None = None
    postcode: str | None = None
    phone: str | None = None
    email: str | None = None
    deceased_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PatientsPublic(SQLModel):
    """A bounded page of patients plus the caller's total, following `UsersPublic`."""

    data: list[PatientRead]
    count: int
