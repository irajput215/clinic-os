"""The two clinical-record tables — `clinical_records` and `clinical_record_versions`.

Design: `docs/features/06-clinical-records/03-design.md` §"Schema"; requirements
`docs/features/06-clinical-records/01-requirements.md` R1-R17.

The design's own sentence is the shape of this module: **the narrative is one column**. The
`subjective`/`objective`/`assessment`/`plan` surface a clinician types is serialised into
`clinical_record_versions.body`; there are no SOAP columns and no second notes table (R3).
`encounters`, `consultation_notes`, `diagnoses` and `allergies` are **not** introduced: the source
contract has no such tables and `01-requirements.md` §"Out of scope for the MVP" says so in terms
(*"An `encounters` resource or `clinical_encounters` table: it does not exist in the source contract
and is not introduced here"*).

Three properties are deliberate and load-bearing:

- **A version row is never updated.** No grant, no route and no `Relationship` in this module offers
  a mutation path; the migration adds a `BEFORE UPDATE OR DELETE` trigger for every role, including
  the table owner and the migration role (`03-design.md` §"Immutability mechanism at two layers").
  An amendment is a **new row** whose `supersedes_version` names the version it replaces and whose
  `reason` carries the clinician's typed amendment reason. `reason` is `HEALTH_INFORMATION`: it is
  stored here and never copied into an audit event or a log line.
- **`clinical_records.signed_at` is the signature clock.** It is set once, by `POST /sign`, and is
  never cleared. `clinical_record_versions.signed_at` is declared because the schema contract lists
  it, but **nothing in this slice writes it**: the design fixes the application role's privileges on
  that table at exactly `SELECT, INSERT`, so no permitted statement can set a column on an existing
  version row. The signature evidence is the record's `signed_at` plus the `clinical_record.write`
  audit event that `POST /sign` writes in the same transaction. Resolving where a per-version
  signature would live is reported as an open item rather than worked around with a grant that would
  break the feature's own `S1`-`S11` immutability suite.
- **`signature_digest` is declared and unwritten.** It is repo-proposed with no source field
  (`01-requirements.md` OPEN-5) and no key-custody decision; the column exists so the model and the
  schema contract agree, and this slice never populates it.

Indexes follow `docs/reference/database-conventions.md`: `tenant_id` leads every one of them, and the
names use the repository's `ix_` prefix. The design's *timeline* index is written against `created_at`
rather than `signed_at`: `03-design.md` records that choice as an open item, and `signed_at` is NULL
for every unsigned record, so it cannot order a timeline. The keyset read orders by
`created_at DESC, id DESC` and this index serves it.
"""

import uuid
from datetime import UTC, datetime
from typing import Final

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

# The closed sets the design's schema table fixes. Feature code validates against these tuples so a
# route's accepted vocabulary and the database's CHECK constraint cannot drift apart.
RECORD_TYPE_VOCABULARY: Final[tuple[str, ...]] = (
    "NOTE",
    "OBSERVATION",
    "HISTORY",
    "ADDENDUM",
    "RESULT",
)
BODY_FORMAT_VOCABULARY: Final[tuple[str, ...]] = ("MARKDOWN", "PLAIN")

# The default the create route applies when the client does not name one: the feature's own story is
# "author a clinical note" (US-1). The column stays NOT NULL and the CHECK still constrains it.
DEFAULT_RECORD_TYPE: Final[str] = "NOTE"


def _utcnow() -> datetime:
    return datetime.now(UTC)


# A shared TypeEngine instance: types are immutable, and `sa_type` wants an instance or a class,
# not a factory.
_TIMESTAMPTZ = sa.DateTime(timezone=True)


class ClinicalRecord(SQLModel, table=True):
    """The parent record: patient, type, attribution, current version and signature clock."""

    __tablename__ = "clinical_records"
    __table_args__ = (
        sa.CheckConstraint(
            "record_type IN ('NOTE', 'OBSERVATION', 'HISTORY', 'ADDENDUM', 'RESULT')",
            name="record_type",
        ),
        # Named explicitly: the convention keys a unique constraint on its first column, which would
        # collide with the primary key name. The parent needs `(tenant_id, id)` unique so the child's
        # composite foreign key can be tenant-bound (`04-database-erd.md` §8).
        sa.UniqueConstraint("tenant_id", "id", name="uq_clinical_records_tenant_id_id"),
        # The tenant-bound patient link. `patients` carries `uq_patients_tenant_id_id` for exactly
        # this purpose, and the target is a string so this module never imports another module's
        # models (`database-conventions.md`, "Creating relationships").
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patients.tenant_id", "patients.id"],
            name="fk_clinical_records_tenant_id_patient_id_patients",
            ondelete="RESTRICT",
        ),
        # The timeline read: the caller's patient, newest first. `created_at` is NOT NULL, so it
        # orders a timeline that includes unsigned drafts; PostgreSQL scans this index backwards for
        # the `DESC` keyset order.
        sa.Index(
            "ix_clinical_records_tenant_patient_created_at",
            "tenant_id",
            "patient_id",
            "created_at",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    # RESTRICT, not CASCADE: a clinical record is retained clinical history. Removing the tenant
    # that owns it must fail loudly rather than destroy or orphan it (`database-conventions.md`).
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    # No `foreign_key=` here: the tenant-bound link is the composite constraint above, which is the
    # one that makes a cross-tenant patient reference impossible.
    patient_id: uuid.UUID = Field(nullable=False)
    record_type: str = Field(default=DEFAULT_RECORD_TYPE, nullable=False)
    # Attribution is the point: `NOT NULL`, always server-set from the session (`03-design.md`).
    author_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="RESTRICT", nullable=False
    )
    # The authoritative pointer to the highest version. Only the patient/record metadata columns may
    # change after creation, and only through the column-scoped grant the migration issues.
    current_version: int = Field(default=1, nullable=False)
    # Set once by `POST /sign`; never cleared (`03-design.md`: "set on sign; content can then only be
    # added to").
    signed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    # Soft delete only; nothing in this slice sets it (no DELETE route exists — R12).
    deleted_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)


class ClinicalRecordVersion(SQLModel, table=True):
    """One immutable version of a record's narrative.

    Append-only by construction: this module inserts rows and never updates or deletes one, and the
    migration revokes `UPDATE`/`DELETE`/`TRUNCATE` from the application role and installs a trigger
    that refuses both statements for **every** role.
    """

    __tablename__ = "clinical_record_versions"
    __table_args__ = (
        sa.CheckConstraint("version >= 1", name="version_minimum"),
        sa.CheckConstraint("body_format IN ('MARKDOWN', 'PLAIN')", name="body_format"),
        # One row per `(record, version)` (R8). The unique constraint also makes the ascending version
        # order total, so the read path needs no tie-breaker (R9).
        sa.UniqueConstraint(
            "tenant_id",
            "clinical_record_id",
            "version",
            name="uq_clinical_record_versions_tenant_record_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "clinical_record_id"],
            ["clinical_records.tenant_id", "clinical_records.id"],
            name="fk_clinical_record_versions_tenant_id_clinical_record_id",
            ondelete="RESTRICT",
        ),
        # Narrative search is a care requirement, so the index ships even though the search API is
        # out of scope for the MVP (`01-requirements.md` R16, "Out of scope"). A partial GIN index
        # over the narrative: `body <> ''` keeps empty revisions out, and the predicate deliberately
        # contains no `now()` — a clock in an index predicate is not immutable and would stop the
        # planner from using it (`03-design.md`, "Constraints, indexes and read order").
        sa.Index(
            "ix_clinical_record_versions_body_fts",
            sa.text("to_tsvector('english'::regconfig, body)"),
            postgresql_using="gin",
            postgresql_where=sa.text("body <> ''"),
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="RESTRICT", nullable=False
    )
    clinical_record_id: uuid.UUID = Field(nullable=False)
    version: int = Field(nullable=False)
    # HIGHLY_SENSITIVE. The narrative lives here and nowhere else (R3); it is never logged, never
    # audited and never returned in an error response (INV-5, R15).
    body: str = Field(nullable=False)
    body_format: str = Field(nullable=False)
    author_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="RESTRICT", nullable=False
    )
    signed_at: datetime | None = Field(default=None, sa_type=_TIMESTAMPTZ)
    # The version this one replaces. `None` on version 1; every later version names its predecessor,
    # which is what makes the amendment chain walkable (R6).
    supersedes_version: int | None = Field(default=None)
    # The clinician's typed amendment reason. HEALTH_INFORMATION: free text may contain clinical
    # content, so it is never copied into an audit event, a log line or a metric (`05-data-and-audit.md`).
    reason: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=_TIMESTAMPTZ)
    # Repo-proposed with no source field (OPEN-5); unwritten in this slice.
    signature_digest: str | None = Field(default=None)
