"""The model registry.

Alembic reads `SQLModel.metadata`, so every table must be imported somewhere on
that path. This module is that single place: `alembic/env.py` imports it, and
nothing else has to remember to import a model for its table to exist.

Importing it also applies the naming convention from `app.core.metadata` before
any table is defined.
"""

from sqlmodel import SQLModel

from app.core.metadata import NAMING_CONVENTION
from app.models import Item, User
from app.modules.identity_tenancy.models import Tenant

__all__ = ["NAMING_CONVENTION", "SQLModel", "Item", "Tenant", "User"]
