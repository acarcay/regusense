"""
Database Session Management for ReguSense.

Provides the single async SQLAlchemy engine and session factory for
PostgreSQL. The engine is created lazily on first use so that importing
this module never requires a configured database.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import settings

# IMPORTANT: Schema changes MUST go through Alembic migrations.
# Do NOT call Base.metadata.create_all() in production.
# To apply migrations: alembic upgrade head

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _resolve_database_url() -> str:
    """Resolve the database URL from settings or the plain DATABASE_URL env var."""
    url = settings.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "Database is not configured. Set REGUSENSE_DATABASE_URL in .env "
            "(see .env.example), e.g. "
            "postgresql+asyncpg://user:password@localhost:5432/regusense"
        )
    return url


def get_engine() -> AsyncEngine:
    """Return the shared async engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _resolve_database_url(),
            echo=False,  # Set to True for SQL debugging
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # Drop stale connections
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared session factory, creating it on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Usage:
        async with get_async_session() as session:
            result = await session.execute(select(Speaker))
    """
    session = get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def __getattr__(name: str):
    # Backward compatibility: `async_engine` used to be a module-level object.
    if name == "async_engine":
        return get_engine()
    if name == "async_session_factory":
        return get_session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
