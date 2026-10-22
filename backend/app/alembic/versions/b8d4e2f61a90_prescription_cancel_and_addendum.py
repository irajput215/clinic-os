"""Prescription cancel and addendum: the reason code, the superseded original, the addendum key

Revision ID: b8d4e2f61a90
Revises: 6045114a607a
Create Date: 2026-10-08

FEAT-11 R5 ("`SIGNED` is immutable; a correction is an addendum") and R11 ("cancel before dispatch
requires a reason"), decision D-010.

* `prescriptions.cancel_reason_code` - set exactly when a row is `CANCELLED`
  (`ck_prescriptions_cancel_reason_present`), from the interim closed vocabulary
  (`ck_prescriptions_cancel_reason_code`). No row is `CANCELLED` before this revision (no route could
  cancel), so the check holds on an existing table.
* `prescriptions.supersedes_id` - the signed original an addendum corrects, through the tenant-bound
  key `(tenant_id, supersedes_id) -> prescriptions(tenant_id, id)`, so an addendum can never name
  another tenant's prescription; `uq_prescriptions_tenant_supersedes` allows one addendum per original.
* `prescriptions.addendum_key` - the server-computed SHA-256 of the addendum request's
  `Idempotency-Key` (never the raw header), present exactly on an addendum.
* `prescriptions_lock_signed()` is replaced: `supersedes_id` and `addendum_key` are frozen for the
  row's life, `cancel_reason_code` changes only on the transition into `CANCELLED`, and a terminal row
  stays frozen. Everything the earlier version enforced is unchanged.

Nullable columns and checks that hold on every existing row: the upgrade is safe on a populated table.
No `ALTER ... OWNER`, no role, no extension.
"""

import sqlalchemy as sa
from alembic import op

revision = "b8d4e2f61a90"
down_revision = "6045114a607a"
branch_labels = None
depends_on = None

_CANCEL_REASON_CODES = (
    "ENTERED_IN_ERROR",
    "CLINICALLY_NOT_REQUIRED",
    "PATIENT_DECLINED",
    "DUPLICATE",
    "SUPERSEDED_BY_ADDENDUM",
)
_HEX64 = r"^[0-9a-f]{64}$"

# Written out, as in `44c34ed0d6b2`, so this revision's meaning never changes after it is applied.
_TRANSITIONS = (
    ("DRAFT", "SIGNED"),
    ("DRAFT", "CANCELLED"),
    ("SIGNED", "QUEUED"),
    ("SIGNED", "BLOCKED"),
    ("SIGNED", "CANCELLED"),
    ("BLOCKED", "QUEUED"),
    ("BLOCKED", "CANCELLED"),
    ("QUEUED", "DISPATCHED"),
    ("QUEUED", "FAILED"),
    ("QUEUED", "REQUIRES_RECONCILIATION"),
    ("FAILED", "QUEUED"),
    ("FAILED", "CANCELLED"),
    ("REQUIRES_RECONCILIATION", "DISPATCHED"),
    ("REQUIRES_RECONCILIATION", "FAILED"),
    ("DISPATCHED", "REVERSED"),
)
_PAYLOAD = (
    "patient_id",
    "prescriber_id",
    "drafted_by",
    "medicine_name",
    "tga_category",
    "dosage_form",
    "dose_instruction",
    "quantity",
    "repeats",
    "triage_outcome",
    "conventional_therapy",
    "date_of_service",
    "payload_hash",
    "signed_at",
    "signed_by",
)


def _row(prefix: str, columns: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"{prefix}.{column}" for column in columns) + ")"


_PAIRS = ", ".join(f"('{a}', '{b}')" for a, b in _TRANSITIONS)


def _function(*, with_addendum: bool) -> str:
    identity = ("id", "tenant_id", "created_at") + (
        ("supersedes_id", "addendum_key") if with_addendum else ()
    )
    terminal = ("state", "approval_id") + (
        ("cancel_reason_code",) if with_addendum else ()
    )
    cancel_reason = (
        """
    IF NEW.cancel_reason_code IS DISTINCT FROM OLD.cancel_reason_code
       AND NOT (NEW.state = 'CANCELLED' AND OLD.state <> 'CANCELLED') THEN
        RAISE EXCEPTION 'SIGNED_IS_IMMUTABLE: a cancel reason is recorded with the cancellation only'
            USING ERRCODE = 'check_violation';
    END IF;"""
        if with_addendum
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION prescriptions_lock_signed() RETURNS trigger AS $fn$
BEGIN
    IF {_row("NEW", identity)} IS DISTINCT FROM {_row("OLD", identity)} THEN
        RAISE EXCEPTION 'SIGNED_IS_IMMUTABLE: a prescription''s identity cannot change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.state IS DISTINCT FROM OLD.state
       AND (OLD.state, NEW.state) NOT IN ({_PAIRS}) THEN
        RAISE EXCEPTION 'INVALID_STATE_TRANSITION: % -> % is not a permitted transition',
            OLD.state, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.state <> 'DRAFT'
       AND {_row("NEW", _PAYLOAD)} IS DISTINCT FROM {_row("OLD", _PAYLOAD)} THEN
        RAISE EXCEPTION 'SIGNED_IS_IMMUTABLE: a signed prescription cannot be edited; amend by addendum'
            USING ERRCODE = 'check_violation';
    END IF;{cancel_reason}
    IF OLD.state IN ('CANCELLED', 'REVERSED')
       AND {_row("NEW", terminal)} IS DISTINCT FROM {_row("OLD", terminal)} THEN
        RAISE EXCEPTION 'SIGNED_IS_IMMUTABLE: a terminal prescription is immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column(
        "prescriptions",
        sa.Column("cancel_reason_code", sa.String(length=64), nullable=True),
    )
    op.add_column("prescriptions", sa.Column("supersedes_id", sa.Uuid(), nullable=True))
    op.add_column(
        "prescriptions", sa.Column("addendum_key", sa.String(length=64), nullable=True)
    )
    codes = ", ".join(f"'{code}'" for code in _CANCEL_REASON_CODES)
    op.create_check_constraint(
        "cancel_reason_code",
        "prescriptions",
        f"cancel_reason_code IS NULL OR cancel_reason_code IN ({codes})",
    )
    op.create_check_constraint(
        "cancel_reason_present",
        "prescriptions",
        "(state = 'CANCELLED') = (cancel_reason_code IS NOT NULL)",
    )
    op.create_check_constraint(
        "supersedes_other", "prescriptions", "supersedes_id IS NULL OR supersedes_id <> id"
    )
    op.create_check_constraint(
        "addendum_key",
        "prescriptions",
        f"(supersedes_id IS NULL AND addendum_key IS NULL) OR (supersedes_id IS NOT NULL"
        f" AND addendum_key ~ '{_HEX64}')",
    )
    op.create_foreign_key(
        "fk_prescriptions_tenant_supersedes",
        "prescriptions",
        "prescriptions",
        ["tenant_id", "supersedes_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_prescriptions_tenant_supersedes",
        "prescriptions",
        ["tenant_id", "supersedes_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_id IS NOT NULL"),
    )
    op.execute(_function(with_addendum=True))


def downgrade() -> None:
    op.execute(_function(with_addendum=False))
    op.drop_index("uq_prescriptions_tenant_supersedes", table_name="prescriptions")
    op.drop_constraint(
        "fk_prescriptions_tenant_supersedes", "prescriptions", type_="foreignkey"
    )
    # Suffix names: the shared naming convention renders `ck_prescriptions_<name>`, as on create.
    for name in (
        "addendum_key",
        "supersedes_other",
        "cancel_reason_present",
        "cancel_reason_code",
    ):
        op.drop_constraint(name, "prescriptions", type_="check")
    op.drop_column("prescriptions", "addendum_key")
    op.drop_column("prescriptions", "supersedes_id")
    op.drop_column("prescriptions", "cancel_reason_code")
