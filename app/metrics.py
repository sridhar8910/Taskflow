"""
In-process request/error metrics.

Intentionally simple: module-level counters updated by MetricsMiddleware.
Resets on process restart. In production, swap for prometheus_client.

Thread-safety note: CPython's GIL makes simple integer increments atomic
for practical purposes, but we use a lock to be explicit and correct.
"""

import threading
from collections import defaultdict


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests_total: int = 0
        self.errors_total: int = 0
        # Per-route breakdown: {method_path: count}
        self._requests_by_route: dict[str, int] = defaultdict(int)
        self._errors_by_route: dict[str, int] = defaultdict(int)

    def record_request(self, method: str, path: str) -> None:
        with self._lock:
            self.requests_total += 1
            self._requests_by_route[f"{method} {path}"] += 1

    def record_error(self, method: str, path: str) -> None:
        with self._lock:
            self.errors_total += 1
            self._errors_by_route[f"{method} {path}"] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests_total": self.requests_total,
                "errors_total": self.errors_total,
                "requests_by_route": dict(self._requests_by_route),
                "errors_by_route": dict(self._errors_by_route),
            }

    def reset(self) -> None:
        """Reset all counters — used in tests."""
        with self._lock:
            self.requests_total = 0
            self.errors_total = 0
            self._requests_by_route.clear()
            self._errors_by_route.clear()


# Singleton used throughout the app
metrics = _Metrics()
