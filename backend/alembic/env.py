"""
Alembic environment configuration for database migrations.

This module configures Alembic to work with:
- AsyncPG driver for PostgreSQL
- Pydantic Settings for configuration
- Async SQLAlchemy operations
"""

import asyncio
import logging
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import your models here to ensure they are registered with SQLAlchemy
from app.core.database import Base
from app.models import user, token, usage, system_config  # noqa: F401

# Set up logging
logger = logging.getLogger("alembic.env")

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    """Get database URL from Pydantic Settings or environment variables."""
    import os

    # Try to get from environment variables first (with KBR_ prefix)
    url = os.getenv("KBR_DATABASE_URL")
    if url:
        return url

    # Fallback to non-prefixed environment variable
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    # Try to get from Pydantic Settings
    try:
        from app.core.config import get_settings

        settings = get_settings()
        return settings.DATABASE_URL
    except Exception as e:
        # If all else fails, try config file
        config_url = config.get_main_option("sqlalchemy.url")
        if config_url and config_url != "driver://user:pass@localhost/dbname":
            return config_url

        # If we still don't have a URL, raise an informative error
        raise ValueError(
            "Database URL not found. Please set one of:\n"
            "  - KBR_DATABASE_URL environment variable\n"
            "  - DATABASE_URL environment variable\n"
            "  - Configure settings in .env file\n"
            f"Original error: {e}"
        )


def run_migrations_offline() -> None:
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
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with database connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in async mode with asyncpg support.

    This function creates an async engine specifically configured for
    database migrations with the asyncpg driver.
    """
    # Get the database URL
    database_url = get_url()

    # Ensure we're using the async driver
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError(
            f"Expected PostgreSQL URL with asyncpg driver, got: {database_url[:50]}..."
        )

    # Create async engine configuration
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url

    # Create async engine with appropriate settings for migrations
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # Use NullPool for migrations to avoid connection issues
        echo=False,  # Set to True for SQL debugging
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        # Ensure proper cleanup
        await connectable.dispose()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode using async engine.

    This is the main entry point for running migrations with a live database connection.
    """
    logger.info("Running migrations in online mode with async engine")
    try:
        asyncio.run(run_async_migrations())
        logger.info("Migrations completed successfully")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
