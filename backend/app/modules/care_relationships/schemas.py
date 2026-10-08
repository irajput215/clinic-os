"""Schemas for the care-relationship resolver and its interim upkeep routes.

The design names no care-relationship endpoint — the table is read by the policy layer
(`docs/features/05-patients/03-design.md` "Treating-relationship rule";
`06-clinical-records/03-design.md` "Treating-relationship check") — and the source of truth is **OPEN**
(open-questions.md C13). Decision D-007 records the interim upkeep routes these shapes serve
(`docs2/sdlc/02-patients/api.md`, "Care team").

`tenant_id` is absent deliberately: the caller is the request's own tenant context, and a schema that
carried it would invite a client to treat it as an input (INV-1).
"""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

# PRIVATE API, deliberately, for the reason the other modules' schemas record: SQLModel annotates
# `model_config` as `SQLModelConfig`, so a plain `ConfigDict` is rejected by mypy --strict and ty alike.
from sqlmodel._compat import SQLModelConfig


class CareRelationshipRead(SQLModel):
    """One treating relationship as the resolver returns it.

    `active_to is None` means open-ended; the interval is half-open `[active_from, active_to)`. The
    `id` is what the audit envelope records as `care_relationship_id`
    (`docs/features/06-clinical-records/05-data-and-audit.md`), which is why the resolver returns the
    row rather than a bare boolean.
    """

    model_config = SQLModelConfig(extra="forbid", from_attributes=True)

    id: uuid.UUID
    practitioner_id: uuid.UUID
    patient_id: uuid.UUID
    clinic_id: uuid.UUID | None = None
    active_from: datetime
    active_to: datetime | None = None
    source: str


class CareTeamMember(SQLModel):
    """One active relationship on a patient's care team. `practitioner_name` is `None` for an account
    that is no longer an active practitioner (the relationship still shows, so it can be ended)."""

    id: uuid.UUID
    practitioner_id: uuid.UUID
    practitioner_name: str | None
    active_from: datetime
    source: str


class CareTeamPublic(SQLModel):
    data: list[CareTeamMember]
    count: int


class CareRelationshipCreate(SQLModel):
    """Add a practitioner to a patient's care team. Unknown fields (a `tenant_id` above all) are `422`."""

    model_config = SQLModelConfig(extra="forbid")

    practitioner_id: uuid.UUID
