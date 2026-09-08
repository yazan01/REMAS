"""Request metrics and health probes.

The availability NFR asks the vendor to state monitoring and incident response.
This is the monitoring surface: a Prometheus-compatible `/metrics` endpoint and
liveness/readiness probes, with no extra dependency — the exposition format is a
few lines of text, and pulling in a client library for it would be more moving
parts than the job needs.

Latency is recorded as a histogram so the "95% of actions within 3 seconds"
target can be read straight off the metrics, rather than inferred from an
average that hides the tail.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# Buckets chosen around the NFR thresholds: 2s for auto-save, 3s for standard
# page and API actions.
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0)


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.latency: dict[tuple[str, str], list[int]] = defaultdict(
            lambda: [0] * (len(BUCKETS) + 1)
        )
        self.latency_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.latency_count: dict[tuple[str, str], int] = defaultdict(int)
        self.samples: dict[tuple[str, str], list[float]] = defaultdict(list)
        self.started_at = time.time()

    def observe(self, method: str, route: str, status_code: int, seconds: float) -> None:
        key = (method, route)
        with self._lock:
            self.requests[(method, route, status_code)] += 1
            self.latency_sum[key] += seconds
            self.latency_count[key] += 1
            for index, edge in enumerate(BUCKETS):
                if seconds <= edge:
                    self.latency[key][index] += 1
                    break
            else:
                self.latency[key][-1] += 1
            # A bounded reservoir, so p95 can be computed without a TSDB.
            reservoir = self.samples[key]
            reservoir.append(seconds)
            if len(reservoir) > 500:
                del reservoir[0]

    def percentile(self, method: str, route: str, pct: float) -> float | None:
        values = sorted(self.samples.get((method, route), []))
        if not values:
            return None
        index = min(int(len(values) * pct), len(values) - 1)
        return values[index]

    def overall_percentile(self, pct: float) -> float | None:
        values = sorted(v for reservoir in self.samples.values() for v in reservoir)
        if not values:
            return None
        index = min(int(len(values) * pct), len(values) - 1)
        return values[index]

    def render(self) -> str:
        lines = [
            "# HELP remas_uptime_seconds Seconds since process start",
            "# TYPE remas_uptime_seconds gauge",
            f"remas_uptime_seconds {time.time() - self.started_at:.1f}",
            "# HELP remas_requests_total HTTP requests by method, route and status",
            "# TYPE remas_requests_total counter",
        ]
        with self._lock:
            for (method, route, code), count in sorted(self.requests.items()):
                lines.append(
                    f'remas_requests_total{{method="{method}",route="{route}",status="{code}"}} {count}'
                )
            lines += [
                "# HELP remas_request_duration_seconds Request latency",
                "# TYPE remas_request_duration_seconds histogram",
            ]
            for (method, route), buckets in sorted(self.latency.items()):
                cumulative = 0
                for index, edge in enumerate(BUCKETS):
                    cumulative += buckets[index]
                    lines.append(
                        f'remas_request_duration_seconds_bucket{{method="{method}",'
                        f'route="{route}",le="{edge}"}} {cumulative}'
                    )
                cumulative += buckets[-1]
                lines.append(
                    f'remas_request_duration_seconds_bucket{{method="{method}",'
                    f'route="{route}",le="+Inf"}} {cumulative}'
                )
                lines.append(
                    f'remas_request_duration_seconds_sum{{method="{method}",'
                    f'route="{route}"}} {self.latency_sum[(method, route)]:.4f}'
                )
                lines.append(
                    f'remas_request_duration_seconds_count{{method="{method}",'
                    f'route="{route}"}} {self.latency_count[(method, route)]}'
                )
        return "\n".join(lines) + "\n"


metrics = Metrics()


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started

        # Group by route template, not by URL, so ids do not explode the labels.
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        metrics.observe(request.method, path, response.status_code, elapsed)
        response.headers["X-Response-Time"] = f"{elapsed * 1000:.1f}ms"
        return response
