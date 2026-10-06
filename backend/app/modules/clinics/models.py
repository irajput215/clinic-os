"""The `clinics` table — a tenant's practice locations.

Design: `docs/features/01-tenancy-and-clinics/03-design.md`, "Table: `clinics` (tenant-scoped)";
requirements: `docs/features/01-tenancy-and-clinics/01-requirements.md` R3 and R11. Task T1-01 Part B.

`clinics` is the tenant-scoped child of `tenants`: one customer organisation, several practice sites,
all of them inside the same tenant boundary. It carries `tenant_id NOT NULL`, an `ON DELETE RESTRICT`
foreign key to `tenants`, and `UNIQUE (tenant_id, id)` — the tenant-bound child key
`04-database-erd.md` §8 expects, so a future child table can reference a clinic without being able to
reference one belonging to another organisation. The migration that creates it also creates the forced
row-level security policy, which a model cannot express.

## The column set is a recorded choice, not a specification

The design says the column set, its uniqueness rules and its classification are **OPEN** (*"are not
invented here"*; `03-design.md` open items, `05-data-and-audit.md` open items) and names only three
things: `id`, `tenant_id`, the standard timestamps, and that the table "has a human-readable label
because US-02 requires create and rename". This slice therefore implements the smallest label-plus-
contact shape the task directs — `name`, `address`, `phone` — and keeps two consequences visible:

- **Per-field classification stays unassigned.** `05-data-and-audit.md` states no level for any
  `clinics` column and this change does not invent one; feature task T1-10 owns classification for
  every Phase 1 table.
- **`UNIQUE (tenant_id, name)` is an engineering choice.** A rename onto an existing name must be a
  `422` rather than a `500` (R11, test F7), which needs a uniqueness rule *somewhere*; the design does
  not say whether the label or a separate code is the grain. A name is a label rather than an
  identifier, so a multi-site group with two identically named rooms would be refused — flagged for
  the Head of Platform + Privacy Officer rather than settled here.

There is no `deleted_at`: `05-data-and-audit.md` records the tenant/clinic retention position as
**REQUIRES LEGAL/REGULATORY VALIDATION** and clinic deletion as OPEN, and a soft-delete column with no
schedule behind it is a filter nobody has agreed to. The no-`DELETE` grant (design, "Database
privileges") is what keeps a clinic from being removed today.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


# A shared TypeEngine instance: types are immutable, and `sa_type` wants an instance or a class,
# not a factory (the `patients` model uses the same spelling).
_TIMESTAMPTZ = sa.DateTime(timezone=True)


class Clinic(SQLModel, table=True):
    __tablename__ = "clinics"
    __table_args__ = (
        # Named explicitly rather than left to the convention, which keys a unique constraint on its
        # first column alone and would collide with the primary key name.
        sa.UniqueConstraint("tenant_id", "id", name="uq_clinics_tenant_id_id"),
        # R11/F7: a rename onto an existing name is refused, and the refusal is a constraint
        # violation the service maps to `422` rather than a `500`.
        sa.UniqueConstraint("tenant_id", "name", name="uq_clinics_tenant_id_name"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    # RESTRICT, not CASCADE or SET NULL: a practice location is part of the organisation's record.
    # Removing the organisation must fail loudly rather than delete its sites or leave them orphaned.
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    # The human-readable label US-02 creates and renames. `tenant_id` leads both unique constraints,
    # so `ORDER BY name` inside a tenant is served by `uq_clinics_tenant_id_name` without a second
    # index.
    name: str = Field(max_length=255)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )
