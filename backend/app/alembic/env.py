import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
assert config.config_file_name is not None
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# target_metadata = None

from sqlmodel import SQLModel  # noqa

from app.core.config import settings  # noqa

# Registers every table and applies the naming convention; import it before
# reading the metadata.
import app.db_models  # noqa: E402, F401

target_metadata = SQLModel.metadata

# The monthly partitions of `audit_log` are created by the migration that creates the table
# (`b7c1d9e4f2a3`), and PostgreSQL lists each one in `pg_class` as an ordinary table. Autogenerate
# reads them that way too, so without this filter every `alembic check` would propose dropping
# `audit_log_2026_10` and `audit_log_default` — objects the models must not describe, because the
# partition strategy is DDL and a model cannot express `PARTITION BY`.
#
# The filter is deliberately narrow: it ignores relations PostgreSQL records as a **partition**
# (`pg_inherits`), never every table whose name happens to start with `audit_log_`. A real table named
# `audit_log_notes` is still compared, so nothing hides behind a name pattern.
def include_object(object_, name, type_, reflected, compare_to):
    if type_ == "table" and reflected and name in _partitions:
        return False
    return True


# Populated by `run_migrations_online` before the context is configured. Offline mode leaves it empty,
# which is correct: offline autogenerate cannot create a partition either.
_partitions = set()


def _load_partitions():
    """The partition children in the current schema.

    **This uses a connection of its own, and that is load-bearing.** SQLAlchemy begins a transaction
    implicitly on the first statement executed against a connection. Running this query on the
    *migration* connection before `context.begin_transaction()` therefore leaves that connection
    already inside a transaction, and Alembic's context manager — which does not begin a second one —
    commits nothing: every migration reports success and every one of them is rolled back at process
    exit. That is what happened on the first run of this change, and it is recorded here so the next
    person does not have to rediscover it.
    """
    from sqlalchemy import create_engine
    from sqlalchemy import text as _text

    probe = create_engine(get_url(), poolclass=pool.NullPool)
    try:
        with probe.connect() as connection:
            rows = connection.execute(
                _text(
                    "SELECT c.relname FROM pg_inherits i "
                    "JOIN pg_class c ON c.oid = i.inhrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema()"
                )
            ).all()
            _partitions.update(row[0] for row in rows)
    except Exception:  # noqa: BLE001 - a fresh database has no `pg_inherits` rows at all
        pass
    finally:
        probe.dispose()


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    # Migrations need an owning role; the application runs least privilege. `MIGRATION_DATABASE_URL`
    # is optional and falls back to `DATABASE_URL`, so an existing deployment is unchanged.
    return str(settings.MIGRATION_DATABASE_URL)


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section)
    assert configuration is not None
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    _load_partitions()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
