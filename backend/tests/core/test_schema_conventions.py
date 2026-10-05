"""The database and the model metadata must agree on every generated name.

`alembic check` compares the schema the models describe with the schema in the database, but
autogenerate does **not** compare CHECK constraints. That blind spot hid a real mistake: the two
`tenants` checks were double-prefixed in every database — including one built from scratch, so it was
not environment drift — while `alembic check` reported "no new upgrade operations detected".

`app.core.metadata` exists so that one convention names everything. These tests assert the outcome
directly, because that is the only thing that can: a convention is only worth having if something
fails when it is not applied.
"""

from typing import Any

from sqlalchemy import inspect
from sqlmodel import SQLModel

import app.db_models  # noqa: F401 - importing registers every table on SQLModel.metadata
from app.core.db import engine

# The prefixes `app.core.metadata` generates. A name may use one of them, once.
_PREFIXES = ("pk_", "fk_", "ck_", "uq_", "ix_")


def _metadata_names(table: Any) -> tuple[set[str], set[str]]:
    """Constraint and index names as the models declare them."""
    constraints = {c.name for c in table.constraints if c.name}
    indexes = {i.name for i in table.indexes if i.name}
    return constraints, indexes


def _database_names(inspector: Any, table: str) -> tuple[set[str], set[str]]:
    """Constraint and index names as Postgres actually holds them."""
    constraints = {
        row["name"] for row in inspector.get_check_constraints(table) if row.get("name")
    }
    constraints |= {
        row["name"]
        for row in inspector.get_unique_constraints(table)
        if row.get("name")
    }
    primary_key = inspector.get_pk_constraint(table).get("name")
    if primary_key:
        constraints.add(primary_key)
    constraints |= {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys(table)
        if foreign_key.get("name")
    }
    # Postgres backs a UNIQUE constraint with an index and reports it in both lists, so an index
    # check that did not subtract one from the other would count the constraint twice.
    indexes = {row["name"] for row in inspector.get_indexes(table) if row.get("name")}
    indexes -= {
        row["name"]
        for row in inspector.get_unique_constraints(table)
        if row.get("name")
    }
    return constraints, indexes


def _describe(problems: list[str], kind: str) -> str:
    return (
        f"{kind} names differ between the models and the database — the convention was not applied, "
        "or a migration renamed something the models do not expect:\n  "
        + "\n  ".join(problems)
    )


def test_every_constraint_name_matches_the_model_metadata() -> None:
    inspector = inspect(engine)
    problems: list[str] = []

    for table_name, table in sorted(SQLModel.metadata.tables.items()):
        declared, _ = _metadata_names(table)
        actual, _ = _database_names(inspector, table_name)
        problems += [
            f"{table_name}: the models declare {name!r}, the database does not have it"
            for name in sorted(declared - actual)
        ]
        problems += [
            f"{table_name}: the database has {name!r}, the models do not declare it"
            for name in sorted(actual - declared)
        ]

    assert not problems, _describe(problems, "Constraint")


def test_every_index_name_matches_the_model_metadata() -> None:
    inspector = inspect(engine)
    problems: list[str] = []

    for table_name, table in sorted(SQLModel.metadata.tables.items()):
        _, declared = _metadata_names(table)
        _, actual = _database_names(inspector, table_name)
        problems += [
            f"{table_name}: the models declare {name!r}, the database does not have it"
            for name in sorted(declared - actual)
        ]
        problems += [
            f"{table_name}: the database has {name!r}, the models do not declare it"
            for name in sorted(actual - declared)
        ]

    assert not problems, _describe(problems, "Index")


def test_no_constraint_name_is_prefixed_twice() -> None:
    """`ck_tenants_ck_tenants_status`.

    This is what a declared name that is already conventional produces when the convention is then
    applied to it: `name='ck_tenants_status'` became `ck_tenants_` + `ck_tenants_status`. It reads as
    harmless, and it silently breaks anything that looks a constraint up by name.
    """
    inspector = inspect(engine)
    doubled: list[str] = []

    for table_name in sorted(SQLModel.metadata.tables):
        constraints, indexes = _database_names(inspector, table_name)
        for name in sorted(constraints | indexes):
            prefix = name.split("_", 1)[0] + "_"
            if prefix in _PREFIXES and name.count(prefix) > 1:
                doubled.append(f"{table_name}.{name}")

    assert not doubled, (
        "These names carry the same prefix twice, so the convention was applied to a name that "
        "already had it:\n  " + "\n  ".join(doubled)
    )


def test_the_tenant_checks_are_named_as_the_decisions_record_says() -> None:
    """The exact regression, pinned by name so it cannot come back quietly."""
    inspector = inspect(engine)
    actual, _ = _database_names(inspector, "tenants")

    assert "ck_tenants_status" in actual
    assert "ck_tenants_slug_lowercase" in actual
