"""
Alembic environment configuration — async-compatible.

This file is executed by Alembic when running any ``alembic`` CLI command.
It reads the ``DATABASE_URL`` from the project's ``.env`` file (via
``python-dotenv``) so that database credentials are never stored in version
control.

All ORM models are imported here so Alembic can detect schema changes during
``alembic revision --autogenerate``.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------------------------
# Load .env so DATABASE_URL is available as an environment variable
# ---------------------------------------------------------------------------
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ---------------------------------------------------------------------------
# Import all ORM models so Alembic can detect them for autogenerate
# ---------------------------------------------------------------------------
# This import registers all models on the shared Base.metadata.
import app.models  # noqa: F401, E402
from app.database import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object (gives access to values in alembic.ini)
# ---------------------------------------------------------------------------
config = context.config

# Override the sqlalchemy.url with the value from the environment so that
# credentials are read from .env rather than the ini file.
database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set.  "
        "Create a .env file with DATABASE_URL=postgresql+asyncpg://..."
    )
config.set_main_option("sqlalchemy.url", database_url)

# ---------------------------------------------------------------------------
# Set up logging from alembic.ini
# ---------------------------------------------------------------------------
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Metadata for autogenerate support
# ---------------------------------------------------------------------------
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Helper: run migrations in offline mode (no DB connection required)
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This generates SQL scripts without actually connecting to the database.
    Useful for generating migration scripts to review before applying.
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


# ---------------------------------------------------------------------------
# Helper: run migrations in online mode (with a live DB connection)
# ---------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    """Execute the migrations using an active database connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within a connection context."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using asyncio."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
