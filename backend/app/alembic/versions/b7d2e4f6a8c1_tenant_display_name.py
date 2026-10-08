"""tenants.display_name: the clinic's public name

Revision ID: b7d2e4f6a8c1
Revises: 94d4331e9eb0
Create Date: 2026-10-08 09:00:00.000000

Contract: `docs2/sdlc/01-auth-and-shell/api.md`, "Clinic display name". The sidebar and the public
booking page showed a name derived from the routing slug, because the only name a tenant had was
`legal_name`, which is CONFIDENTIAL (`docs/features/01-tenancy-and-clinics/03-design.md`) and must
never be shown publicly. `display_name` is the PUBLIC name the Practice Owner chooses.

## Backfill: from the slug, never from `legal_name`

Signup stores the clinic name it was given in `legal_name`, so for most tenants that value *is* the
name the owner typed. It is still classified CONFIDENTIAL, and an operator-created tenant (the demo
tenant, `Demo Clinic Pty Ltd`) holds a real legal entity name there. Copying it into a PUBLIC column
would declassify it without anyone deciding to, so every existing tenant gets the name its public
booking page already shows today: the slug, title-cased (`green-valley-clinic` -> `Green Valley
Clinic`). Nothing becomes public that was not public already, and the owner renames it in Settings.

## Constraint and grants

`NOT NULL`, at most 120 characters, no padding and no control character (`ck_tenants_display_name`),
the same rule the API applies. The application role gains `SELECT (display_name)` and the only
`UPDATE` it holds on `tenants`: `UPDATE (display_name, updated_at)`. `legal_name`, `status` and
`retention_profile` stay unwritable to it, and `legal_name` and `retention_profile` unreadable.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'b7d2e4f6a8c1'
down_revision = '94d4331e9eb0'
branch_labels = None
depends_on = None

_MAX = 120

# The slug, title-cased, with the same fallback the API's own normaliser would reach for a blank
# result. `initcap` upper-cases the first letter of each word; slugs are lower-case already.
_BACKFILL = sa.text(
    "UPDATE tenants SET display_name = COALESCE("
    "  NULLIF(btrim(left(initcap(replace(slug, '-', ' ')), :max)), ''),"
    "  'Clinic'"
    ")"
)


def upgrade():
    op.add_column(
        'tenants',
        sa.Column(
            'display_name',
            sqlmodel.sql.sqltypes.AutoString(length=_MAX),
            nullable=True,
        ),
    )
    op.get_bind().execute(_BACKFILL, {"max": _MAX})
    op.alter_column('tenants', 'display_name', nullable=False)
    op.create_check_constraint(
        op.f('ck_tenants_display_name'),
        'tenants',
        f"char_length(display_name) BETWEEN 1 AND {_MAX}"
        " AND display_name = btrim(display_name)"
        " AND display_name !~ '[[:cntrl:]]'",
    )
    op.execute("GRANT SELECT (display_name) ON tenants TO clinos_app")
    op.execute("GRANT UPDATE (display_name, updated_at) ON tenants TO clinos_app")


def downgrade():
    # Dropping the column drops its column grants; `updated_at`'s is revoked explicitly.
    op.execute("REVOKE UPDATE (updated_at) ON tenants FROM clinos_app")
    op.drop_constraint(op.f('ck_tenants_display_name'), 'tenants', type_='check')
    op.drop_column('tenants', 'display_name')
