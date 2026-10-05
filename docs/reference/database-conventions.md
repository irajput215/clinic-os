---
doc_id: OZ-REF-DB
title: Database schema, relationships and migration conventions
owner: Engineering Lead
status: DRAFT — for review
last_reviewed: 2026-10-05
next_review: 2026-11-05
classification: RESTRICTED
repo_docs:
  - README.md
  - AGENTS.md
  - reference/build-contract.md
---

# Database conventions

The stack is SQLModel on PostgreSQL with Alembic. These conventions apply to every table, and they are
the ones a reviewer checks a schema change against. Where a rule is already true in this repository it
says so, with the artefact; where it is not, it says that instead.

## Where the schema is defined

Four layers, and only one of them builds the database.

| Layer | File | Role |
|---|---|---|
| Models | [`app/modules/<module_id>/models.py`](../../backend/app/modules/), plus the frozen template layer in [`app/models.py`](../../backend/app/models.py) | The *target* shape. Changing a model changes nothing by itself |
| Naming convention | [`core/metadata.py`](../../backend/app/core/metadata.py) | One convention for `pk_`/`fk_`/`ck_`/`uq_`/`ix_`. Applied on import |
| Registry | [`db_models.py`](../../backend/app/db_models.py) | The single place Alembic reads. A model not imported here has no table, ever |
| Migrations | [`alembic/versions/`](../../backend/app/alembic/versions/) | The DDL that actually runs, in order |

**The database is the sum of the migrations, not of the models.** A model change with no migration is a
bug that `alembic check` usually catches — but not always, see "What the tools cannot see" below.

**Migrations are not hermetic.** Replaying them with newer code does not reproduce what an older
environment got, because migrations run inside whatever `app.core.metadata` says *at replay time*. This
has already produced two different schema histories in this repository ([`../progress.md`](../progress.md)
§4.8). Pin a constraint name with `op.f()` when the migration must produce an exact name regardless of
the convention.

## Creating relationships

Define relationships in the models. Never add a foreign key by hand in the database — the migration is
the only thing that should change a schema, so that a rebuilt database and a deployed one agree.

- **One-to-many.** The `ForeignKey` column goes on the "many" side, and `Relationship` is declared on
  **both** models with `back_populates`, so neither direction can drift from the other.
- **Many-to-many.** Use an explicit link table, not an association proxy. Give it its own columns when
  the edge carries data of its own — a role, a start date, an end date — because that data has to live
  somewhere and retrofitting it later means a new table plus a data migration.
- **Optional relations.** A nullable relation is normal here: an account may exist without an
  organisation, because signup can create an unattached account before a clinic is named.

Two SQLModel details that cost time if you meet them by surprise:

```python
# `Tenant | None` fails at mapper configuration: SQLAlchemy resolves a relationship's target from the
# annotation, and looks for a class literally named "Tenant | None".
tenant: Optional["Tenant"] = Relationship(back_populates="users")   # correct-ish

# When the other model lives in another module, keep the target a string. Importing it for real would
# be a runtime cross-module import, which build-contract §7 forbids ("no module reaches into another
# module's tables"). The same reason the foreign key names its table as a string.
users: list["User"] = Relationship(back_populates="tenant")
```

A relationship that fails to configure fails at **first use** — the request that needed it — not at
import. So a relationship needs a test that navigates it, not just a model that declares it.

### Changing the schema

```bash
cd backend
uv run alembic revision --autogenerate -m "message"
# read the generated file before running it
uv run alembic upgrade head
uv run alembic check      # must report no new upgrade operations
```

Always read autogenerate output. It does not detect table or column **renames** (it emits a drop plus a
create, which destroys data), and it does not compare **CHECK constraints** at all.

## Keeping it manageable as it grows

- **Group models by domain.** One module per area, never one growing `models.py`. A module owns its
  tables and is reached only through its service facade. Keep cross-domain references deliberate and
  few — every one is a coupling that outlives the change that added it.
- **One naming convention on the metadata.** Without it Alembic emits unpredictable names and every
  later migration is guesswork. Declare check constraints with a *suffix* (`name="status"` renders as
  `ck_tenants_status`); passing an already-conventional name produces `ck_tenants_ck_tenants_status`.
- **Decide `ondelete` explicitly for every foreign key.** It is a data-loss decision, not a detail:

  | Behaviour | Use for |
  |---|---|
  | `RESTRICT` | Clinical and audit records. Nothing may remove a record another record depends on |
  | `SET NULL` | A reassignable link — an account that outlives the organisation it pointed at |
  | `CASCADE` | True child data only: rows that have no meaning without the parent |

- **Prefer soft deletes for health data.** A `deleted_at` column keeps the record for retention and
  audit while hiding it from normal reads. Hard deletes are for data with no clinical or audit life.
  This is not free: every query must filter, which is exactly the kind of rule that needs a shared
  helper rather than discipline.
- **Keep an append-only audit table.** For this product the audit record is a control, not a log: the
  write happens in the same transaction as the change, and a failed audit write fails the operation
  (INV-4, [`build-contract.md`](build-contract.md)). That is feature 04 and is specified in
  [`features/04-audit-log/`](../features/04-audit-log/) — see the reconciliation note below.
- **Index every foreign key** you filter or join on. PostgreSQL does not index a foreign key for you.
  `users.tenant_id` is indexed; the index name follows the convention (`ix_user_tenant_id`).
- **Plan multi-tenancy before the second table, not after.** Every tenant-owned table carries its
  tenant column from its first migration, with row-level security as a second line of defence rather
  than the only one. Retrofitting tenancy means revisiting every query and every row, and the failure
  mode is silent: rows that should have been invisible simply are not.
- **UUID primary keys**, so an identifier in a URL or a log is not a guessable sequence and not a
  business fact. `gen_random_uuid()` is the server default.
- **CI must run the migrations**, not just the tests. `tests/conftest.py` builds tables from
  `SQLModel.metadata`, so the suite would pass even if every migration were broken.

## What the tools cannot see

`uv run alembic check` is necessary and not sufficient. Autogenerate does not compare `CHECK`
constraints, so a wrong or renamed check constraint is invisible to it while the models and the
database disagree — which is how `ck_tenants_ck_tenants_status` survived in every environment, for the
whole life of the table, with a clean `alembic check`
([`../progress.md`](../progress.md) §4.7).

[`tests/core/test_schema_conventions.py`](../../backend/tests/core/test_schema_conventions.py) closes
that gap: it compares every constraint and index name the models declare against the live database, and
fails on a name that carries the same prefix twice.

## Visualisation

**Generated, never hand-maintained.** A hand-drawn diagram is wrong the first time someone forgets it;
a generated one cannot be.

- **[`docs/reference/schema/`](schema/README.md)** holds the Mermaid ER diagrams, generated by
  [`scripts/schema-diagram.sh`](../../scripts/schema-diagram.sh) with
  [tbls](https://github.com/k1LoW/tbls) reading the migrated database — so the diagram describes what
  the migrations *produced*, not what the models intend.
- **The diagrams are committed and checked in CI.** `test-backend.yml` regenerates them and fails if
  they differ, so a schema change that forgets the diagram fails the build rather than leaving the
  documentation quietly wrong. Regenerate with:

  ```bash
  docker compose up -d --wait db
  (cd backend && uv run alembic upgrade head)
  ./scripts/schema-diagram.sh
  ```

- **Split the diagram per domain once a single one stops being readable** — around twenty tables. tbls
  takes `--include`/`--exclude`, so a split is one more invocation per domain in the script, not a
  different tool. The current schema is two domain tables and one diagram.
- **DBeaver or pgAdmin for exploration.** The generated diagrams answer "what is the shape"; they are
  the wrong tool for browsing rows. `docker compose` publishes Adminer on
  [localhost:8080](http://localhost:8080) for browsing without installing a client.
- **A generated schema document is good input for a coding agent.** It is derived from the database, so
  it cannot drift from it — unlike a prose description of the schema, which is a second source of truth
  and eventually a wrong one.

> `schema.json`, which tbls also emits, is **not** committed: it embeds the server's full `version()`
> string including the compiler and architecture it was built with, so it can never match between a
> laptop and a CI runner. The Mermaid markdown carries no such string.

## Where this repository stands

Honest status, as of 2026-10-05.

| Convention | State | Evidence |
|---|---|---|
| One naming convention | **Done** | [`core/metadata.py`](../../backend/app/core/metadata.py) |
| UUID primary keys | **Done** | `tenants.id`, `user.id` |
| Modules per domain | **Done, with one exception** | Layout rule in [`../../AGENTS.md`](../../AGENTS.md); `User` still lives in the legacy layer |
| Names asserted against the database | **Done** | [`test_schema_conventions.py`](../../backend/tests/core/test_schema_conventions.py) |
| Migrations run in CI from an empty database | **Done** | `test-backend.yml` → `prestart.sh` → `alembic upgrade head` |
| `alembic check` in CI | **Done** | `test-backend.yml` |
| Schema diagrams generated and gated | **Done** | [`schema-diagram.sh`](../../scripts/schema-diagram.sh), `test-backend.yml` |
| Relationships declared on both sides | **Partial** | `Tenant.users` ↔ `User.tenant`, with a test; `users.tenant_id` is the only foreign key so far |
| `ondelete` decided per foreign key | **Done for the one key that exists** | `users.tenant_id` → `SET NULL` |
| Foreign keys indexed | **Done for the one key that exists** | `ix_user_tenant_id` |
| Multi-tenancy from the first table | **Partial** | `tenants` and `users.tenant_id` exist; **no row-level security yet**, so the column is a link, not an isolation boundary |
| Soft deletes for health data | **Not implemented** | No `deleted_at` anywhere. Belongs with the first clinical table |
| Append-only audit table | **Not implemented** | Feature 04, [`features/04-audit-log/`](../features/04-audit-log/) |
| Diagram split per domain | **Not needed yet** | Two domain tables; revisit around twenty |

## Reconciled with the rest of this document set

This document does not override the feature documents, and two of its rules are already owned
elsewhere:

1. **Soft deletes and the audit table** are requirements of feature 04 and are constrained by the
   retention and erasure position, which is a privacy decision rather than a schema preference
   ([`open-questions.md`](open-questions.md)). A `deleted_at` column is the mechanism; *what may be
   deleted and what must be kept* is not an engineering call.
2. **`tenant_id` on every table** is INV-1 and the tenancy feature's design, including the rule that
   tenant identity is resolved from the session and never supplied. See
   [`features/01-tenancy-and-clinics/03-design.md`](../features/01-tenancy-and-clinics/03-design.md).
3. **The identity model is open.** `users.tenant_id` currently models "one account, one organisation",
   which D-003 has not settled — it may become memberships
   ([`decisions/D-003-identity-model.md`](decisions/D-003-identity-model.md)). `User.tenant` describes
   today's schema; whoever settles D-003 changes it.
