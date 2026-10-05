"""The shared naming convention.

`alembic check` compares metadata to the database, so a convention that drifts from
what is applied produces spurious migrations. These assertions fail loudly if the
convention stops being applied, or if a module stops registering its tables.
"""

from sqlmodel import SQLModel

from app.core.metadata import NAMING_CONVENTION
from app.db_models import __all__ as registered


def test_the_naming_convention_is_applied_to_the_metadata() -> None:
    assert SQLModel.metadata.naming_convention == NAMING_CONVENTION


def test_expected_constraint_names_are_rendered() -> None:
    names = {
        constraint.name
        for table in SQLModel.metadata.tables.values()
        for constraint in table.constraints
    }

    assert "pk_tenants" in names
    assert "ck_tenants_status" in names
    assert "ck_tenants_slug_lowercase" in names
    assert "pk_user" in names


def test_the_registry_registers_every_domain_module_table() -> None:
    assert "Tenant" in registered
    assert "tenants" in SQLModel.metadata.tables
