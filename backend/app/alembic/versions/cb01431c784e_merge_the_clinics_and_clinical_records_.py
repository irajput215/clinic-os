"""merge the clinics and clinical-records branches

Revision ID: cb01431c784e
Revises: d4c9b7a1e5f2, fbcebceb0686
Create Date: 2026-10-06 19:29:56.927603

Two features were built in parallel and each hung a migration off the same parent, `b7c1d9e4f2a3`
(the audit log): `fbcebceb0686` — clinics, care relationships and the `tenant:read` grant — on
`feat/clinics-and-care-relationships`, and `d4c9b7a1e5f2` — clinical records — on
`wip/clinical-records`. Neither branch could see the other, so merging them leaves Alembic with **two**
heads, and `alembic upgrade head` refuses to run at all while more than one exists. The merge is
therefore not a formality: without this revision the deployed migration step fails.

This revision is the join, and it is deliberately empty. Both parents keep their own `upgrade()`, and
both have already run; there is nothing to reconcile, because the two chains touch disjoint objects —
`clinics`, `care_relationships` and one row in `role_permissions` on one side, `clinical_records` and
`clinical_record_versions` on the other. Re-chaining one branch onto the other instead would rewrite
history that may already be applied somewhere, which is the failure this file exists to avoid.

## Downgrade

`downgrade()` is empty for the same reason `upgrade()` is. Unapplying this revision returns Alembic to
the two parents — that is, to two heads — which is the honest state of the two branches. A non-empty
downgrade here would be a silent drop of one branch's tables, and neither branch owns the other's.
"""
# revision identifiers, used by Alembic.
revision = 'cb01431c784e'
down_revision = ('d4c9b7a1e5f2', 'fbcebceb0686')
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to do: each parent performs its own DDL."""


def downgrade() -> None:
    """Nothing to undo: see the module docstring."""
