"""
Safe database migration script for Kubernetes initContainer.

Handles:
1. Advisory lock to prevent concurrent migrations across Pods
2. Auto-stamp if tables exist but alembic_version is empty
3. Standard alembic upgrade head
"""

import asyncio
import logging
import os
import sys

# Ensure the backend directory is on sys.path (for 'app' package imports)
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
# Change to backend dir so alembic.ini is found
os.chdir(_backend_dir)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("migrate")

# PostgreSQL advisory lock ID (arbitrary unique int64)
MIGRATION_LOCK_ID = 7239841


async def check_and_stamp():
    """Phase 1: Acquire lock, check state, auto-stamp if needed.

    Returns the stamp revision applied (or None if no stamp needed).
    The advisory lock is held for the entire duration to prevent
    concurrent migrations from other Pods.
    """
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    stamp_rev = None

    async with engine.connect() as conn:
        # 1. Acquire advisory lock (blocks other Pods)
        logger.info("Acquiring migration advisory lock...")
        await conn.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_ID})"))
        logger.info("Lock acquired")

        try:
            # 2. Check if alembic_version table exists and has a revision
            result = await conn.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables "
                    "  WHERE table_schema='public' AND table_name='alembic_version'"
                    ")"
                )
            )
            alembic_table_exists = result.scalar()

            current_rev = None
            if alembic_table_exists:
                result = await conn.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
                row = result.first()
                current_rev = row[0] if row else None

            # 3. If no revision stamped, check if tables already exist
            if current_rev is None:
                result = await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname='public' AND tablename NOT IN ('alembic_version') "
                        "ORDER BY tablename"
                    )
                )
                existing_tables = [row[0] for row in result]

                if existing_tables:
                    logger.info(
                        f"Found {len(existing_tables)} existing tables but no alembic revision: "
                        f"{existing_tables}"
                    )
                    stamp_rev = await detect_stamp_revision(conn, existing_tables)
                    logger.info(f"Will auto-stamp to revision: {stamp_rev}")
                else:
                    logger.info("Empty database, will run all migrations")
            else:
                logger.info(f"Current alembic revision: {current_rev}")

            await conn.commit()
        finally:
            await conn.execute(text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_ID})"))
            logger.info("Migration lock released")

    await engine.dispose()
    return stamp_rev


async def detect_stamp_revision(conn, existing_tables: list[str]) -> str:
    """Detect which alembic revision matches the current database state."""
    # Check for cache token columns (migration a1b2c3d4e5f6)
    result = await conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='usage_records' AND column_name='cache_creation_input_tokens'"
        )
    )
    has_cache_columns = result.first() is not None

    # Check for model_pricing table (migration 7ce867a32c84)
    has_model_pricing = "model_pricing" in existing_tables

    if has_cache_columns:
        return "head"
    elif has_model_pricing:
        return "7ce867a32c84"  # pragma: allowlist secret
    else:
        return "0f4f689d9e69"


def main():
    try:
        # Phase 1: Check state and auto-stamp (async)
        stamp_rev = asyncio.run(check_and_stamp())

        # Phase 2: Run alembic commands (alembic manages its own async internally)
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")

        if stamp_rev is not None:
            logger.info(f"Stamping to revision: {stamp_rev}")
            command.stamp(alembic_cfg, stamp_rev)
            logger.info(f"Stamped to {stamp_rev}")

        logger.info("Running alembic upgrade head...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Migration completed successfully")

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
