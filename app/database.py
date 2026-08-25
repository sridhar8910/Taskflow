from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# ── Async engine — used by FastAPI routes ─────────────────────────────────────
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Sync engine — used by Celery worker tasks ─────────────────────────────────
# Celery tasks are synchronous; using the async engine from a worker thread
# would require an event loop per task, which is unnecessarily complex.
# The engine is created lazily so that importing this module in tests (which
# use SQLite) doesn't attempt to load psycopg2 on import.

_sync_engine = None
_SyncSessionLocal = None


def _get_sync_engine():
    global _sync_engine, _SyncSessionLocal
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.sync_database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        _SyncSessionLocal = sessionmaker(
            _sync_engine,
            class_=Session,
            expire_on_commit=False,
        )
    return _sync_engine, _SyncSessionLocal


def get_sync_db() -> Session:
    """Return a new synchronous DB session for use in Celery tasks."""
    _, session_factory = _get_sync_engine()
    return session_factory()
