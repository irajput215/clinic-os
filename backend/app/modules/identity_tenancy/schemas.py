"""Request and response schemas for the tenancy routes.

Design: `docs/features/01-tenancy-and-clinics/03-design.md`, "Endpoints" and "Deny-by-default request
path" step 6 ("Validate the body against a strict schema — unknown fields rejected, so a body
`tenant_id` is `422`").

`TenantCurrentRead` declares **exactly the columns `clinos_app` is granted on `tenants`** —
`03-design.md` "Database privileges" issues `GRANT SELECT (id, slug, status, data_region)` and withholds
`retention_profile`, and `legal_name` is not in the grant either. `US-1` states the same rule from the
other side: *"`retention_profile` is never returned to the application surface"*. A response model that
declared a withheld column would force the route to select it, and the day the application connects as
`clinos_app` (rather than as the table owner) that query would fail with `permission denied for column`.

`TenantSettingsUpdate` is **empty on purpose**. (`TenantProfileUpdate`, the clinic's PUBLIC display
name, is a separate sub-resource and not a security setting: `docs2/sdlc/01-auth-and-shell/api.md`,
"Clinic display name".) No document
names a tenant security setting: `05-data-and-audit.md` records a `tenant_settings` table in the
retention schedule and nothing more, `03-design.md` says only "security setting change versioned", and
Feature 15 (phase 4) owns `tenant_policy`. A field invented here would be a setting nobody specified,
written by a route whose required step-up control is blocked by **D-003**. The model exists so that the
strict-schema rule still holds: every field is an unknown field, so a body carrying `tenant_id` — or a
`retention_profile`, or anything else — is a `422` before the route refuses the change.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    ModelWrapValidatorHandler,
    PrivateAttr,
    model_validator,
)
from pydantic import Field as PydanticField
from sqlmodel import Field, SQLModel

# PRIVATE API, deliberately, for the reason the other modules' schemas record: SQLModel annotates
# `model_config` as `SQLModelConfig`, so a plain `ConfigDict` is rejected by mypy --strict and ty alike.
from sqlmodel._compat import SQLModelConfig

from app.modules.identity_tenancy.models import DISPLAY_NAME_MAX_LENGTH


class TenantCurrentRead(SQLModel):
    """The caller's own tenant, as `GET /api/v1/tenants/current` returns it.

    `status` and `data_region` are shown (US-1). `retention_profile` and `legal_name` are not: the
    application role holds no `SELECT` on either (`03-design.md`, "Database privileges").
    """

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    id: uuid.UUID
    slug: str
    status: str
    data_region: str
    created_at: datetime
    updated_at: datetime


class TenantSettingsUpdate(SQLModel):
    """The body of `PATCH /api/v1/tenants/current` — no field is settable yet.

    `extra="forbid"` is what makes that a control rather than a comment: a client cannot smuggle a
    `tenant_id` (or any future setting) past the route, and any name it sends is a `422` decided by the
    validation layer, in the same order the design fixes (validate against a strict schema).
    """

    model_config = SQLModelConfig(extra="forbid")


def normalise_display_name(value: str) -> str:
    """The display name as stored: whitespace runs collapsed to one space, ends trimmed.

    Raises `ValueError` (a `422` through the schema) for a name that is blank once trimmed, longer
    than `DISPLAY_NAME_MAX_LENGTH`, or carrying a character that does not print - a control
    character, or a format character such as a bidirectional override that could make the public
    page read differently from what was typed. `ck_tenants_display_name` refuses the same.
    """
    collapsed = " ".join(value.split())
    if not collapsed:
        raise ValueError("Enter the clinic's name.")
    if len(collapsed) > DISPLAY_NAME_MAX_LENGTH:
        raise ValueError(
            f"Keep the name to {DISPLAY_NAME_MAX_LENGTH} characters or fewer."
        )
    if not collapsed.isprintable():
        raise ValueError("Use letters, numbers, spaces and punctuation only.")
    return collapsed


class TenantProfileRead(SQLModel):
    """The caller's own clinic as every member of it may see it: the PUBLIC display name only."""

    model_config = SQLModelConfig(extra="forbid")

    display_name: str


class TenantProfileUpdate(BaseModel):
    """The body of `PATCH /api/v1/tenants/current/profile`.

    Strict (`extra="forbid"`): any unknown key is a `422`. The one exception is `tenant_id`, which
    INV-1 says is **ignored and audited** rather than refused: it is dropped before validation and the
    service records the attempt on the change's own transaction.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, AfterValidator(normalise_display_name)] = (
        PydanticField(max_length=1000)
    )

    _client_tenant_id_supplied: bool = PrivateAttr(default=False)

    @model_validator(mode="wrap")
    @classmethod
    def _ignore_client_tenant_id(
        cls, data: Any, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        supplied = isinstance(data, dict) and "tenant_id" in data
        if supplied:
            data = {key: value for key, value in data.items() if key != "tenant_id"}
        model = handler(data)
        model._client_tenant_id_supplied = supplied
        return model

    @property
    def client_tenant_id_supplied(self) -> bool:
        """Whether the body carried a `tenant_id` (which was ignored)."""
        return self._client_tenant_id_supplied


class PublicClinicRead(BaseModel):
    """`GET /api/v1/public/{clinic_slug}`: all an unauthenticated visitor learns about a clinic."""

    model_config = ConfigDict(extra="forbid")

    display_name: str


class StepUpRequest(SQLModel):
    """`POST /api/v1/auth/step-up`: re-prove the session's factor for one operation on one resource.

    The interim factor is the account password (ADR-F002; D-003 decides the real one). `operation`
    is a closed vocabulary and `resource_id` is the record the operation will act on, so the grant
    this returns cannot be spent on anything else. No `user_id` or `tenant_id`: both are the session.
    """

    model_config = SQLModelConfig(extra="forbid")

    password: str = Field(min_length=1, max_length=128)
    operation: Literal["prescription.sign", "prescription.dispatch"]
    resource_id: uuid.UUID


class StepUpGrantRead(SQLModel):
    """The single-use proof. `step_up_token` is SECRET: held by the client for one call, never logged."""

    model_config = SQLModelConfig(extra="forbid")

    step_up_token: str
    operation: str
    resource_id: uuid.UUID
    expires_at: datetime
