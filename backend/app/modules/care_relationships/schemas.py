"""Response schemas for the care-relationship resolver.

The design names no care-relationship endpoint — the table is read by the policy layer, not by a route
(`docs/features/05-patients/03-design.md` "Treating-relationship rule";
`06-clinical-records/03-design.md` "Treating-relationship check") — so the only shape declared here is
the one the resolver returns to its callers. A request schema arrives only if a route to create or end a
relationship is specified, and that is **OPEN**: open-questions.md §3.2 `06` item 5 records "the
`care_relationships` source of truth, and who maintains it when a patient changes clinic" with the
Clinical Safety Officer.

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
