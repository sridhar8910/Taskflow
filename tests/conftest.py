"""
Shared test fixtures.

Local runs:  SQLite in-memory (fast, no external deps).
CI runs:     Real PostgreSQL + Redis (set TEST_DATABASE_URL env var).

The TEST_DATABASE_URL env var controls which backend is used:
  - starts with "postgresql" → real PG, run Alembic migrations
  - otherwise               → aiosqlite in-memory, create_all from models
"""

import os
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.dependencies import get_redis
from app.main import app

# ── Database setup ────────────────────────────────────────────────────────────

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")

_connect_args = {"check_same_thread": False} if not _IS_POSTGRES else {}

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args=_connect_args,
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    """
    Create all tables once per test session.
    - SQLite: use SQLAlchemy create_all (fast, no Alembic needed).
    - PostgreSQL: assume `alembic upgrade head` was run before pytest
      (CI workflow does this explicitly). Just verify tables exist.
    """
    if not _IS_POSTGRES:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    if not _IS_POSTGRES:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def patch_celery_delay():
    """
    Globally patch all Celery .delay() calls in the worker module for every test.
    This prevents tests from attempting real broker connections (Redis at redis:6379).
    Individual tests that need to assert on .delay() calls can override with
    their own patch.object().
    """
    from app.worker import tasks as worker_module

    with (
        patch.object(worker_module.send_reassignment_notification, "delay"),
        patch.object(worker_module.send_overdue_notification, "delay"),
    ):
        yield


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a transactional session rolled back after each test.
    Works with both SQLite (savepoint not supported) and PostgreSQL.
    """
    async with test_engine.connect() as conn:
        if _IS_POSTGRES:
            await conn.begin()
            await conn.begin_nested()  # savepoint for rollback
        else:
            await conn.begin()

        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            yield session
            await session.rollback()


# ── Redis setup ───────────────────────────────────────────────────────────────


@pytest.fixture
def fake_redis():
    """In-memory fakeredis instance for unit tests."""
    import fakeredis

    return fakeredis.aioredis.FakeRedis(decode_responses=True)


# ── HTTP client ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, fake_redis
) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP client wired to the FastAPI app with overridden DB and Redis deps.
    """

    async def _override_get_db():
        yield db_session

    def _override_get_redis():
        return fake_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Authenticated client helper ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """
    A pre-authenticated AsyncClient for user 'testuser@example.com'.
    Attaches the Bearer token to all subsequent requests.
    """
    await client.post(
        "/auth/signup",
        json={"email": "testuser@example.com", "password": "securepass1"},
    )
    login = await client.post(
        "/auth/login", json={"email": "testuser@example.com", "password": "securepass1"}
    )
    token = login.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


async def create_user_and_token(
    client: AsyncClient, email: str, password: str = "securepass1"
) -> tuple[str, str]:
    """Helper: sign up a user and return (user_id, access_token)."""
    signup = await client.post(
        "/auth/signup", json={"email": email, "password": password}
    )
    user_id = signup.json()["id"]
    login = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    token = login.json()["access_token"]
    return user_id, token
