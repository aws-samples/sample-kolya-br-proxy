"""
Database configuration and connection management using SQLAlchemy with PostgreSQL.
"""

import logging
from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# SQLAlchemy setup
metadata = MetaData()
Base = declarative_base(metadata=metadata)

# Global variables for database engine and session
engine = None
async_session_maker = None


async def init_db() -> None:
    """Initialize database connection and create tables."""
    global engine, async_session_maker

    settings = get_settings()

    # Create async engine
    if settings.DEBUG:
        # Use NullPool for debugging (no connection pooling)
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG,
            poolclass=NullPool,
        )
    else:
        # Use connection pooling for production
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
        )

    # Create session maker
    async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    logger.info("Database engine initialized")

    # Import models to ensure they are registered
    from app.models import model, oauth_state, system_config, token, usage, user  # noqa: F401

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables created/verified")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to get database session.

    Yields:
        AsyncSession: Database session
    """
    if async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """Close database connections."""
    global engine

    if engine:
        await engine.dispose()
        logger.info("Database connections closed")
