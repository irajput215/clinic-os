"""The `tenants` table.

`docs/features/01-tenancy-and-clinics/03-design.md`, "Table: tenants (GLOBAL — no RLS)".
A tenant is the customer organisation. The table is global by design: tenant context is
proven from the actor's session and the addressed resource, never read from here, so it
carries no row-level security.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models import User

TenantStatus = Literal["ACTIVE", "SUSPENDED", "CLOSING", "CLOSED"]

# SQLModel cannot map a Literal to a column type, so the vocabulary is enforced by
# the CHECK constraint below and mirrored here for schemas and validators.
STATUS_VOCABULARY: tuple[TenantStatus, ...] = (
    "ACTIVE",
    "SUSPENDED",
    "CLOSING",
    "CLOSED",
)

# Data stays in Australia (INV-6); this release admits one region.
DATA_REGIONS: tuple[str, ...] = ("ap-southeast-2",)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"
    __table_args__ = (
        # These names are suffixes: the shared naming convention renders them as
        # ck_tenants_status and ck_tenants_slug_lowercase (app.core.metadata).
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'CLOSING', 'CLOSED')",
            name="status",
        ),
        # The slug is routing only, never an authorisation input; keeping it
        # lower-case makes the uniqueness guarantee predictable.
        sa.CheckConstraint("slug = lower(slug)", name="slug_lowercase"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    slug: str = Field(unique=True, index=True, max_length=64)
    legal_name: str = Field(max_length=255)
    status: str = Field(default="ACTIVE", max_length=16)
    data_region: str = Field(default="ap-southeast-2", max_length=32)
    retention_profile: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow, sa_column_kwargs={"onupdate": _utcnow}
    )

    # One organisation holds many accounts. The reverse side is `User.tenant`, and the foreign key
    # carries `ON DELETE SET NULL`: closing an organisation must not fail because an account pointed
    # at it, and an orphaned account is a link to repair rather than data to destroy.
    #
    # This describes the schema as it is today — one account belongs to at most one organisation
    # (D-003 leaves the identity model open, including whether a practitioner works across clinics
    # through separate user rows or through memberships). Whoever settles D-003 changes this
    # relationship, which is why it is declared here and not inferred at the call site.
    # Quoted because `User` is imported only under TYPE_CHECKING: unquoting it would make this a
    # runtime cross-module import, which build-contract §7 rules out ("no module reaches into another
    # module's tables"). SQLAlchemy resolves the string against the class registry at mapper
    # configuration.
    users: list["User"] = Relationship(back_populates="tenant")  # noqa: UP037


# The operations a step-up grant can authorise. Closed, like every vocabulary that gates an action:
# `docs/features/02-authentication/03-design.md` "Step-up for the five named high-risk operations"
# binds a token to one operation, and only the two prescription operations have a route that consumes
# one today. A third operation is added here, in the check constraint and in the route that spends it.
STEP_UP_OPERATIONS: tuple[str, ...] = ("prescription.sign", "prescription.dispatch")
_STEP_UP_OPERATION_SQL = ", ".join(f"'{operation}'" for operation in STEP_UP_OPERATIONS)

# The longest a grant may live, enforced by the database as well as by the service. Two minutes is
# the step-up window `02-authentication/03-design.md` gives sign and dispatch ("2 min, single use");
# OPEN-5 there records doc 06's 2 minutes against D-003 Option B's 5, and the shorter is the fail-safe.
STEP_UP_MAX_LIFETIME_SECONDS: int = 120


class StepUpGrant(SQLModel, table=True):
    """One fresh-factor proof: single use, short-lived, bound to user + operation + resource.

    The interim step-up of ADR-F002 (password re-entry; D-003 is open) done **server-side**: the
    factor is checked by `POST /api/v1/auth/step-up`, which stores only the SHA-256 of the opaque
    token it hands back, and the operation's own transaction spends the row with one conditional
    `UPDATE ... WHERE consumed_at IS NULL AND expires_at > now()`. Spent, expired, for another user,
    another operation or another resource: the update matches nothing and the operation is refused.

    The token itself is SECRET (`02-authentication/05-data-and-audit.md`) and is never stored: a
    reader of this table cannot replay a grant.
    """

    __tablename__ = "step_up_grants"
    __table_args__ = (
        sa.CheckConstraint(
            f"operation IN ({_STEP_UP_OPERATION_SQL})", name="operation"
        ),
        sa.CheckConstraint("expires_at > issued_at", name="window"),
        sa.CheckConstraint(
            f"expires_at <= issued_at + interval '{STEP_UP_MAX_LIFETIME_SECONDS} seconds'",
            name="max_lifetime",
        ),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash"),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name="consumed_after_issue",
        ),
        sa.UniqueConstraint("token_hash", name="uq_step_up_grants_token_hash"),
        sa.Index(
            "ix_step_up_grants_tenant_user_issued",
            "tenant_id",
            "user_id",
            "issued_at",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": sa.text("gen_random_uuid()")},
    )
    # CASCADE, unlike the clinical tables: a grant is a two-minute credential, not a record, and it
    # must never be the reason an organisation or an account cannot be removed.
    tenant_id: uuid.UUID = Field(
        foreign_key="tenants.id", ondelete="CASCADE", nullable=False
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", nullable=False
    )
    operation: str
    resource_id: uuid.UUID = Field(nullable=False)
    token_hash: str
    issued_at: datetime = Field(sa_type=sa.DateTime(timezone=True))
    expires_at: datetime = Field(sa_type=sa.DateTime(timezone=True))
    consumed_at: datetime | None = Field(
        default=None, sa_type=sa.DateTime(timezone=True)
    )
