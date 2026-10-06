"""merge the tenancy, clinical-records and tga-approvals branches

Revision ID: 9a21387b450c
Revises: cb01431c784e, e5a9d3b8c2f4
Create Date: 2026-10-06 19:58:17.715298

Three features were built in parallel and every one of them hung a migration off the same parent,
`b7c1d9e4f2a3` (the audit log): `fbcebceb0686` — clinics, care relationships and the `tenant:read`
grant — on `feat/clinics-and-care-relationships`; `d4c9b7a1e5f2` — clinical records — on
`wip/clinical-records`; and `e5a9d3b8c2f4` — the TGA approvals tables and the `tga_approval:revoke`
grant — on `wip/tga-approvals-engine`. No branch could see the others, so `cb01431c784e` joined the
first pair and this revision joins the third to them.

Alembic refuses to run `upgrade head` at all while more than one head exists, so this is not a
formality: without it the deployed migration step fails before `fastapi deploy` — exactly what
happened when the first two branches met.

This revision is the join, and it is deliberately empty. Every parent keeps its own `upgrade()` and
all of them have already run. There is nothing to reconcile: the three chains touch disjoint objects —
`clinics`, `care_relationships` and one `role_permissions` row on one side; `clinical_records` and
`clinical_record_versions` on another; `tga_approvals`, `tga_approval_events`, their triggers and one
further `role_permissions` row on the third. The only objects two branches both touch are those
`role_permissions` rows, and each parent inserts its own with `ON CONFLICT DO NOTHING`, so neither
depends on the other's order.

Re-chaining one branch onto another instead would rewrite history that may already be applied
somewhere, which is the failure this file exists to avoid.

## Downgrade

`downgrade()` is empty for the same reason `upgrade()` is. Unapplying this revision returns Alembic to
its two parents — that is, to more than one head — which is the honest state of branches that were
built in parallel. A non-empty downgrade here would be a silent drop of tables this revision does not
own.
"""
# revision identifiers, used by Alembic.
revision = '9a21387b450c'
down_revision = ('cb01431c784e', 'e5a9d3b8c2f4')
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to do: each parent performs its own DDL."""


def downgrade() -> None:
    """Nothing to undo: see the module docstring."""
