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

`TenantSettingsUpdate` is **empty on purpose**, and it is the only request schema here. No document
names a tenant security setting: `05-data-and-audit.md` records a `tenant_settings` table in the
retention schedule and nothing more, `03-design.md` says only "security setting change versioned", and
Feature 15 (phase 4) owns `tenant_policy`. A field invented here would be a setting nobody specified,
written by a route whose required step-up control is blocked by **D-003**. The model exists so that the
strict-schema rule still holds: every field is an unknown field, so a body carrying `tenant_id` — or a
`retention_profile`, or anything else — is a `422` before the route refuses the change.
"""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

# PRIVATE API, deliberately, for the reason the other modules' schemas record: SQLModel annotates
# `model_config` as `SQLModelConfig`, so a plain `ConfigDict` is rejected by mypy --strict and ty alike.
from sqlmodel._compat import SQLModelConfig


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
