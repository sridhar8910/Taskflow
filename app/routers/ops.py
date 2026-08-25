"""
Operational endpoints: /health and /metrics.

/health — checks PostgreSQL and Redis liveness using injected dependencies
  so the test suite can override them cleanly.

/metrics — returns request/error counters accumulated by MetricsMiddleware.
"""

import logging

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_redis
from app.metrics import metrics

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])


@router.get("/health", summary="Liveness/readiness check")
async def health(
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    """
    Checks:
    - PostgreSQL: executes SELECT 1
    - Redis: sends PING

    Returns 200 if all deps are healthy, 503 otherwise.
    """
    result: dict[str, str] = {"status": "ok"}
    healthy = True

    # ── PostgreSQL ─────────────────────────────────────────────────────────────
    try:
        await db.execute(text("SELECT 1"))
        result["db"] = "ok"
    except Exception as exc:
        logger.warning("Health check: PostgreSQL unavailable: %s", exc)
        result["db"] = "unavailable"
        healthy = False

    # ── Redis ──────────────────────────────────────────────────────────────────
    try:
        await redis.ping()
        result["redis"] = "ok"
    except Exception as exc:
        logger.warning("Health check: Redis unavailable: %s", exc)
        result["redis"] = "unavailable"
        healthy = False

    if not healthy:
        result["status"] = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return result


@router.get("/metrics", summary="Request and error counters")
async def get_metrics() -> dict:
    """
    Returns accumulated request and error counters.

    In production, swap for prometheus_client exposition:
      from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
      return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    """
    return metrics.snapshot()
