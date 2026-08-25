"""
MetricsMiddleware — counts requests and errors per route.

Excluded paths: /health and /metrics themselves, to avoid polluting
the counters with operational traffic.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.metrics import metrics

_EXCLUDED_PATHS = {"/health", "/metrics"}


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        response = await call_next(request)

        metrics.record_request(request.method, request.url.path)
        if response.status_code >= 400:
            metrics.record_error(request.method, request.url.path)

        return response
