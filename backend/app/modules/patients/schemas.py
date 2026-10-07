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
    """One keyset page of patients, the total that matches, and the cursor for the next page.

    `count` is the number of live patients that match the request - the tenant's whole list for
    `GET /patients`, the matches for a search - not the length of this page. `next_cursor` is `null`
    on the last page. The cursor is opaque: it names the last row of this page by its internal id,
    never by a name, so it carries nothing a URL or a log line must not hold.
    """

    data: list[PatientRead]
    count: int
    next_cursor: str | None = None


# The bounds of a search. The query floor is an open item (`01-requirements.md` OPEN-2, open question
# O3: "≥ 3 characters is the draft's engineering floor, not a source requirement"), so the floor is one
# visible character: the whole list is already reachable page by page through `GET /patients`, so a
# longer floor would protect nothing and would stop a clinician finding "Li" or "Ng".
SEARCH_QUERY_MAX_LENGTH = 100
# The server-side maximum for one page, list or search. A client may ask for fewer; asking for more is
# a `422` rather than a silently truncated result (T1-35: "the result cap is 25 on the patient list").
MAX_PATIENTS_PAGE_SIZE = 25
SEARCH_MAX_TERMS = 6
# A cursor is a short signed token around one UUID; the bound keeps a hostile value from the decoder.
MAX_CURSOR_LENGTH = 256


class PatientSearch(SQLModel):
    """The body of `POST /api/v1/patients/search`.

    The term travels in the body, never in a URL (`01-requirements.md` R12), so it reaches no access
    log, proxy log or browser history. It is never logged or audited either: the audit event records
    which *kinds* of term were used (`query_filters`), not what they were (`02-user-stories.md` US-7).
    """

    model_config = SQLModelConfig(extra="forbid", str_strip_whitespace=True)

    q: str = Field(min_length=1, max_length=SEARCH_QUERY_MAX_LENGTH)
    cursor: str | None = Field(default=None, max_length=MAX_CURSOR_LENGTH)
    limit: int = Field(default=MAX_PATIENTS_PAGE_SIZE, ge=1, le=MAX_PATIENTS_PAGE_SIZE)

    @model_validator(mode="after")
    def _bound_the_number_of_terms(self) -> Self:
        if len(self.q.split()) > SEARCH_MAX_TERMS:
            raise ValueError(f"q may hold at most {SEARCH_MAX_TERMS} words")
        return self
