"""One naming convention for every constraint and index.

Adopted while the schema holds three tables. Constraint names are read by Alembic
when it compares metadata to the database, so a convention introduced after ten
tables exist becomes a rename migration across all ten — which is why this lands
now rather than later.

Applied by import: `app.models` and `app.modules` both import this module before
defining any table, and `app.db_models` (the registry Alembic reads) imports both.
"""

from typing import Final

from sqlmodel import SQLModel

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

SQLModel.metadata.naming_convention = NAMING_CONVENTION
