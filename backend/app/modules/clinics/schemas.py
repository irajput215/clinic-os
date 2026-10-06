"""Request and response schemas for the clinics module.

Design: `docs/features/01-tenancy-and-clinics/03-design.md`, "Table: `clinics` (tenant-scoped)".
Every model is strict (`extra="forbid"`) on the same reasoning as the patients module: a body carrying
`tenant_id` is an unknown field and a `422`, never a silently ignored value (INV-1).

**No request schema exists yet.** The design's clinic endpoints (`GET /api/v1/tenants/current/clinics`,
`POST /api/v1/clinics`, `PATCH /api/v1/clinics/{id}`, `03-design.md` "Endpoints") are not in this
slice — the Feature 01 backlog names the table and the two `tenants/current` routes only — so the only
shapes declared here are the ones a read returns. `ClinicCreate`/`ClinicUpdate` land with those routes
and with `clinic:read`/`clinic:manage`, which are candidates absent from the fixed catalogue
(`01-requirements.md` OPEN-2).

`tenant_id` is absent from `ClinicRead` on purpose: the caller already knows its own tenant, and a
response that echoed it would invite a client to treat it as an input.
"""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

# PRIVATE API, deliberately, and the reason is the same as the patients schemas: SQLModel annotates
# `model_config` as `SQLModelConfig`, so a plain `ConfigDict` is rejected by both mypy --strict and ty.
from sqlmodel._compat import SQLModelConfig


class ClinicRead(SQLModel):
    """A practice location as the API returns it.

    `from_attributes` lets the service hand over a declared model rather than a raw ORM entity
    (build-contract §6 control 5: no ORM entity is ever returned from a route).
    """

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    id: uuid.UUID
    name: str
    address: str | None = None
    phone: str | None = None
    created_at: datetime
    updated_at: datetime


class ClinicsPublic(SQLModel):
    """A bounded page of clinics plus the caller's total, following `PatientsPublic`."""

    model_config = SQLModelConfig(extra="forbid")

    data: list[ClinicRead]
    count: int
