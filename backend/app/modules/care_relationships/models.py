"""The `care_relationships` table — the practitioner/patient treating relationship.

Task T1-04 (Feature 03 R7, and the dependency Feature 05's R7 and Feature 06's R11 both name).
The table is read by the central policy layer under the request's tenant context; it is never inferred
from clinic membership and never widened to the tenant
(`docs/features/06-clinical-records/03-design.md`, "Treating-relationship check";
`docs/features/03-users-and-roles/04-threat-model.md` T-03.1).

## The column set comes from the consumers, not from an ERD

`04-database-erd.md` defines no `care_relationships` table — every feature that needs it records the
same open item ("`care_relationships` is named in `06-authentication-rbac.md` §10 but has no ERD table
definition"). Two independent consumers agree on the tuple, and this model is that tuple:

    care_relationships(tenant_id, practitioner_id, patient_id, clinic_id, active_from, active_to, source)

(`docs/features/05-patients/03-design.md` "Treating-relationship rule" and
`docs/features/06-clinical-records/03-design.md` "Treating-relationship check", in both cases verbatim
including the `hasActiveCareRelationship` reading.) `id`, `created_at` and `updated_at` are added
because every table in this repository carries them.

## Choices this model makes, and why they are flagged

- **`active_to IS NULL` means open-ended; the interval is half-open `[active_from, active_to)`.**
  `D-006` fixes the half-open boundary as the interim fail-safe for validity intervals, and an
  ended relationship is exactly `active_to <= now`. There is no `is_active` boolean: two sources of
  truth for one fact is how a stale relationship keeps authorising.
- **`clinic_id` is nullable.** The tuple names it, but a relationship is between a practitioner and a
  patient; tying it to one site would make "a practitioner working across two clinics" (an OPEN
  question, `open-questions.md` §3.2 `05` item 4) unrepresentable without inventing a second row per
  site. `NULL` means "not tied to one site", and it is a recorded choice rather than a reading of the
  design, which says nothing about nullability.
- **`source` is `NOT NULL` and has no closed vocabulary.** The design names the column and no values,
  and open-questions.md §3.2 `06` item 5 records "the `care_relationships` source of truth, and who
  maintains it" as **OPEN** with the Clinical Safety Officer. A required free-text column records who
  said so at write time; inventing a `CHECK` vocabulary here would settle an open clinical-governance
  question in code.
- **`practitioner_id` references the legacy `user` table.** The design's referent is `users`, which is
  task T1-03 and is blocked by **D-003**; `user` is the only account table that exists. The foreign key
  moves with T1-03, exactly as `user_roles.user_id` does (recorded in that migration's docstring).
- **No `DELETE` grant.** `clinos_app` holds `SELECT, INSERT, UPDATE` and is refused `DELETE` and
  `TRUNCATE` by the migration: ending a relationship is `active_to`, and an authorisation record that
  can vanish is not evidence. `tests/isolation/test_app_role_is_not_owner.py` enforces exactly that
  rule for every tenant table.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


_TIMESTAMPTZ = sa.DateTime(timezone=True)


class CareRelationship(SQLModel, table=True):
    __tablename__ = "care_relationships"
    __table_args__ = (
        # An interval that ends before it starts is not an interval. Named as a suffix, so the shared
        # convention renders `ck_care_relationships_active_interval`.
        sa.CheckConstraint(
            "active_to IS NULL OR active_to > active_from",
            name="active_interval",
        ),
        # The tenant-bound child key `04-database-erd.md` §8 expects: a child of this table can
        # reference it without reaching across a tenant boundary.
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_care_relationships_tenant_id_id"
        ),
        # The lookup the policy layer makes — one practitioner, one patient, one tenant — in that
        # order, so the index leads with `tenant_id` as every tenant table's does.
        sa.Index(
            "ix_care_relationships_tenant_practitioner_patient",
            "tenant_id",
            "practitioner_id",
            "patient_id",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    # RESTRICT throughout: an authorisation record is not destroyed because a parent row moved.
    # `tenants`, `patients` and `clinics` are all governed by the no-hard-delete rule anyway.
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    practitioner_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="RESTRICT", nullable=False
    )
    patient_id: uuid.UUID = Field(
        foreign_key="patients.id", ondelete="RESTRICT", nullable=False
    )
    clinic_id: uuid.UUID | None = Field(
        default=None, foreign_key="clinics.id", ondelete="RESTRICT"
    )
    active_from: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    active_to: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    source: str = Field(max_length=128)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_type=_TIMESTAMPTZ,
        sa_column_kwargs={"onupdate": _utcnow},
    )
