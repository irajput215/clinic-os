"""the five database roles and their grants

Revision ID: 33c56ebab859
Revises: 134a7201f6d2
Create Date: 2026-10-05 23:22:35.174508

Task T1-11. The application role split the tenancy design requires
(`docs/features/01-tenancy-and-clinics/03-design.md`, "Database privileges"):
*"The application connects as `clinos_app`: non-owner, no `BYPASSRLS`; roles are created by
migration, never by hand (`05 §4`)."*

Five roles, and only what the design specifies for objects that **exist today**
(`tenants`, `user`, `patients`). Every grant that names a table or column which has not landed is
deferred below, not invented.

## The five roles

`clinos_app` (134a7201f6d2 already created it), `clinos_migrator`, `clinos_retention`,
`clinos_readonly_audit`, `clinos_auth`.

All are `NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOLOGIN PASSWORD NULL`. **`NOLOGIN` and a
null password are deliberate**: a credential does not belong in a migration and cannot be rotated
from one. The deployment gives each role a credential out of band, at the moment it switches a
runtime path onto it. `BYPASSRLS` is what makes a policy decorative, so no role here holds it.

Two further names appear once, in passing, in the design and are **not** created: `clinos_extractor`
(`docs/features/09-tga-inbox/03-design.md`: `INSERT, SELECT ON tga_extraction_results`) and
`clinos_webhook_ingest` (`docs/features/12-pharmacy-dispatch/03-design.md`: `INSERT` on
`webhook_events`, and the policy shape is OPEN-2). Neither has a table to grant on yet; they land
with those tables.

## Grants that apply today

From `docs/features/01-tenancy-and-clinics/03-design.md` §Database privileges, verbatim::

    REVOKE ALL ON tenants FROM clinos_app;
    GRANT SELECT (id, slug, status, data_region) ON tenants TO clinos_app;  -- retention_profile withheld

`tenants` is global and carries no RLS, so column-level grants are its whole protection:
`retention_profile` is CONFIDENTIAL and withheld from the application.

From `docs/features/05-patients/03-design.md` §Database privileges, verbatim::

    GRANT SELECT, INSERT, UPDATE ON patients TO clinos_app;
    REVOKE DELETE, TRUNCATE ON patients FROM clinos_app;   -- the no-hard-delete rule, enforced by grant

`134a7201f6d2` already issued the `GRANT`; re-stating it here makes this migration the one place the
least-privilege set is written down, and re-issuing a grant is a no-op. The `REVOKE` of `DELETE` and
`TRUNCATE` is the control requirement R11 depends on: the app role cannot hard-delete a patient even
if a future grant is added in error.

## Ownership — not changed here, and why (production-affecting if it ever is)

The design's ownership statements are `ALTER TABLE clinics OWNER TO clinos_migrator` and, for the
audit table, *"`clinos_migrator` | Owns the schema, runs migrations | DDL; owns the table"*
(`docs/features/04-audit-log/03-design.md`). Both tables are absent. The design's requirement on the
tables that exist is the negative one — *"clinos_app never owns a table"* — and that already holds:
`postgres` owns `tenants`, `user` and `patients`.

**No `ALTER TABLE ... OWNER` is issued for the existing tables.** The design does not name them, and
re-owning them is production-affecting (the owner is the role DDL authority runs as). `clinos_migrator`
therefore owns nothing yet; it owns `clinics` and `audit_log` when those migrations land. Flagged for
the lead rather than guessed at.

## Deferred grants — "applies when that table lands"

The design specifies these, and none names an object that exists yet, so none is issued:

* `clinics` — `GRANT SELECT, INSERT, UPDATE ON clinics TO clinos_app`; `REVOKE DELETE, TRUNCATE`;
  `ALTER TABLE clinics OWNER TO clinos_migrator` (`01-tenancy-and-clinics/03-design.md`).
* `users`, `roles`, `role_permissions`, `user_roles`, `permissions` — `GRANT SELECT, INSERT, UPDATE ON
  users, roles TO clinos_app`; `REVOKE DELETE, TRUNCATE`; `GRANT SELECT ON permissions`; the rest of
  `03-users-and-roles/03-design.md` §Database privileges.
* `audit_log` — `SELECT, INSERT` to `clinos_app`, `SELECT` to `clinos_readonly_audit`, partition drop
  to `clinos_retention`, ownership to `clinos_migrator` (`04-audit-log/03-design.md` §Database
  privileges). Today's `patients` policy is `TO PUBLIC`, so it does not reference these roles.
* `refresh_tokens`, `login_attempts`, `account_lockouts`, `mfa_enrolments` —
  `02-authentication/03-design.md` §Database privileges.
* `retention_jobs`, the admin/config tables — `14-reports-and-exports/03-design.md`,
  `15-admin-and-config/03-design.md`.

## Why no grants on `user`

The legacy `user` table carries the design's name for the auth tables (`users`) but not its shape:
`subject_id`, `display_name`, `status`, `mfa_enrolled_at` and `last_login_at` do not exist, and the
Phase-1 `users` table is T1-03, still blocked by D-003. The design also contradicts itself on this
table — `03-users-and-roles/03-design.md` grants `clinos_app` table-level `SELECT, INSERT, UPDATE`,
while `02-authentication/03-design.md` says `REVOKE ALL ... GRANT SELECT (<columns>)` and, under
Branch B, `REVOKE SELECT (hashed_password)`. Those cannot both hold (a table-level `GRANT SELECT`
cannot be narrowed by a column-level `REVOKE`), so applying either would be choosing a side. No grant
is issued on `user`; the conflict is reported, not resolved here. Consequently `clinos_auth`,
`clinos_readonly_audit` and `clinos_retention` hold no privilege on any table that exists today.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "33c56ebab859"
down_revision = "134a7201f6d2"
branch_labels = None
depends_on = None

# The application role already exists (134a7201f6d2), but listing it here keeps the five roles the
# design names in one place. `NOLOGIN` and `PASSWORD NULL`: the deployment sets a credential out of
# band; creating the role with one would put a secret in a migration, where it cannot be rotated.
_ROLES = (
    "clinos_app",
    "clinos_migrator",
    "clinos_retention",
    "clinos_readonly_audit",
    "clinos_auth",
)

# The four roles this migration introduces. `clinos_app` already had `USAGE ON SCHEMA public` from
# 134a7201f6d2, so its schema grant is not re-issued and, below, not revoked.
_NEW_ROLES = (
    "clinos_migrator",
    "clinos_retention",
    "clinos_readonly_audit",
    "clinos_auth",
)


def _create_role(name: str) -> None:
    # Idempotent: 134a7201f6d2 may already have created `clinos_app`, and a re-run of an interrupted
    # migration must not fail. The attributes are asserted only at creation — a deployment may have
    # given the role LOGIN out of band, and an `ALTER ROLE ... NOLOGIN` here would revoke that on
    # every upgrade.
    op.execute(
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{name}') THEN "
        f"CREATE ROLE {name} "
        "NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOLOGIN PASSWORD NULL; "
        "END IF; END $$"
    )


def upgrade() -> None:
    for role in _ROLES:
        _create_role(role)

    # A table privilege is unusable without USAGE on the schema that holds the table. This is not a
    # data privilege; it is what makes the grants below reachable.
    for role in _NEW_ROLES:
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")

    # `tenants` is global (no RLS): column-level grants are its protection.
    op.execute("REVOKE ALL ON tenants FROM clinos_app")
    op.execute("GRANT SELECT (id, slug, status, data_region) ON tenants TO clinos_app")

    # `patients` is tenant-scoped. `SELECT, INSERT, UPDATE` and no `DELETE`/`TRUNCATE`; the granted
    # privileges were issued by 134a7201f6d2, and restating them is a no-op that keeps the design's
    # least-privilege set readable in one place.
    op.execute("GRANT SELECT, INSERT, UPDATE ON patients TO clinos_app")
    op.execute("REVOKE DELETE, TRUNCATE ON patients FROM clinos_app")


def downgrade() -> None:
    # Reverse only what this migration introduced. `SELECT, INSERT, UPDATE ON patients` is
    # 134a7201f6d2's grant, still in force when this revision is downgraded, so revoking it here
    # would undo another migration's work. The `REVOKE DELETE, TRUNCATE` above removed nothing (no
    # such grant ever existed) and has nothing to reverse.
    op.execute("REVOKE ALL ON tenants FROM clinos_app")
    for role in _NEW_ROLES:
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")

    # The roles are deliberately NOT dropped. They are cluster-level objects, not schema objects:
    # a deployment may already have given one a credential out of band, and dropping it would revoke
    # a live application's access on a schema rollback. Revoking the privileges is the reversible
    # half; the role stays until a deliberate, out-of-band decision removes it.
