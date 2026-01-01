"""Alembic environment configuration for database migrations.

This module configures the Alembic migration environment to work with:
- SQLModel/SQLAlchemy models
- Both online (CLI) and offline (SQL file generation) modes
- Kubernetes port-forwarding for database access (handled by CLI)
- Environment-specific database URLs
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# SQLModel uses SQLModel.metadata as its declarative base metadata.
# All models with `table=True` automatically register there when imported.
# The loader dynamically discovers and imports all table.py modules.
from src.app.entities.loader import get_metadata

# target_metadata is what Alembic uses for autogeneration
# get_metadata() imports all tables and returns SQLModel.metadata
target_metadata = get_metadata()

# This is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Get database URL from environment variable (set by CLI)
# The CLI handles port-forwarding and constructs the correct URL
database_url = os.environ.get("DATABASE_URL")

if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable not set. "
        "Run migrations via the CLI: uv run api-forge-cli k8s db migrate"
    )

# Override sqlalchemy.url in alembic.ini with runtime value
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
