"""
/health and /metrics endpoint tests.

- /health returns 200 with all deps ok when DB + Redis are healthy
- /health returns 503 when DB is unavailable
- /health returns 503 when Redis is unavailable
- /metrics counters increment on requests
- /metrics errors_total increments on 4xx responses
- /metrics excluded paths (/health, /metrics) are not counted
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset counters before/after each test to avoid cross-test contamination."""
    metrics.reset()
    yield
    metrics.reset()


# ── /health ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_all_ok(client: AsyncClient):
    """Both DB (SQLite in tests) and Redis (fakeredis) healthy → 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_db_down(client: AsyncClient):
    """DB unavailable → 503 with db=unavailable, redis still ok."""
    from sqlalchemy.exc import OperationalError

    # Patch execute on AsyncSession so SELECT 1 raises
    async def bad_execute(self, *args, **kwargs):
        raise OperationalError("connection refused", None, None)

    with patch.object(AsyncSession, "execute", bad_execute):
        resp = await client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unavailable"
    assert body["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_redis_down(client: AsyncClient, fake_redis):
    """Redis ping fails → 503 with redis=unavailable, db still ok."""
    with patch.object(
        fake_redis,
        "ping",
        new_callable=AsyncMock,
        side_effect=ConnectionError("Redis down"),
    ):
        resp = await client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "unavailable"
    assert body["db"] == "ok"


# ── /metrics ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_requests_increment(client: AsyncClient):
    """Each non-excluded request increments requests_total."""
    metrics.reset()

    await client.get("/")
    await client.get("/")

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["requests_total"] >= 2


@pytest.mark.asyncio
async def test_metrics_errors_increment(client: AsyncClient):
    """4xx responses increment errors_total."""
    metrics.reset()

    await client.get("/this-route-does-not-exist")
    await client.get("/this-route-does-not-exist")

    resp = await client.get("/metrics")
    body = resp.json()
    assert body["errors_total"] >= 2


@pytest.mark.asyncio
async def test_metrics_excluded_paths_not_counted(client: AsyncClient):
    """/health and /metrics themselves are not counted in the metrics."""
    metrics.reset()

    # Only hit excluded endpoints
    await client.get("/health")
    await client.get("/metrics")
    await client.get("/metrics")

    body = (await client.get("/metrics")).json()
    assert body["requests_total"] == 0


@pytest.mark.asyncio
async def test_metrics_structure(client: AsyncClient):
    """Response has the expected top-level keys."""
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "requests_total",
        "errors_total",
        "requests_by_route",
        "errors_by_route",
    ):
        assert key in body
