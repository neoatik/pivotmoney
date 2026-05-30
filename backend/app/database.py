"""
Async SQLAlchemy 2.0 database setup.

Provides:
- ``engine``            – async engine connected to PostgreSQL via asyncpg
- ``AsyncSessionLocal`` – session factory for dependency-injected sessions
- ``Base``              – declarative base shared by all ORM models
- ``get_db``            – FastAPI dependency that yields a session per request
- ``init_db``           – creates all tables on startup (development helper)
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


settings = get_settings()

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,        # log SQL statements in debug mode
    pool_pre_ping=True,         # verify connections before handing them out
    pool_size=10,               # base connection pool size
    max_overflow=20,            # allow up to 20 extra connections under load
    pool_recycle=3600,          # recycle connections after 1 hour
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,     # keep attributes accessible after commit
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an :class:`AsyncSession` for use in FastAPI route dependencies.

    The session is automatically committed on success and rolled back on any
    unhandled exception, then closed unconditionally.

    Usage::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Table initialisation (dev / testing helper)
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """Create all tables defined via :class:`Base` if they do not exist.

    This is a lightweight alternative to running Alembic migrations and is
    primarily used during development and integration tests.  In production
    use ``alembic upgrade head`` instead.
    """
    # Import models so that their metadata is registered on Base before we
    # call create_all.  The import is here (not at module top-level) to avoid
    # circular imports at load time.
    import app.models  # noqa: F401  — registers all ORM models on Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
