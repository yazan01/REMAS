from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import APIError, api_error_handler, validation_error_handler
from app.core.observability import MetricsMiddleware, metrics
from app.db.session import engine, init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Real Estate Maturity Assessment (REMAS). All content endpoints return "
        "Arabic and English side by side so the client can switch language "
        "without a round-trip."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Response-Time"],
)
if settings.metrics_enabled:
    app.add_middleware(MetricsMiddleware)

app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness — the process is up. Deliberately does no I/O, so a slow database
    never takes the container down."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/health/ready", tags=["meta"])
def readiness() -> dict:
    """Readiness — the dependencies this instance needs to serve traffic."""
    checks: dict[str, str] = {}
    ready = True

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
        ready = False

    try:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.storage_dir / ".readiness"
        probe.write_bytes(b"ok")
        probe.unlink()
        checks["storage"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["storage"] = f"error: {type(exc).__name__}"
        ready = False

    checks["evidence_encryption"] = (
        "on" if settings.encrypt_evidence and settings.evidence_master_key else "off"
    )

    from app.services.ai import ocr
    from app.services.ai.provider import get_provider

    checks["ai_provider"] = get_provider().info.name
    checks["ocr_provider"] = ocr.available_provider() or "none"

    return {"status": "ready" if ready else "degraded", "checks": checks}


@app.get("/metrics", tags=["meta"])
def prometheus_metrics() -> Response:
    """Prometheus exposition. The availability and performance NFRs need a
    scrape target, not a log grep."""
    if not settings.metrics_enabled:
        return Response(status_code=404)
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/metrics/summary", tags=["meta"])
def metrics_summary() -> dict:
    """Human-readable read of the performance NFR: p95 across all routes."""
    return {
        "p50_seconds": metrics.overall_percentile(0.50),
        "p95_seconds": metrics.overall_percentile(0.95),
        "p99_seconds": metrics.overall_percentile(0.99),
        "target_p95_seconds": 3.0,
        "requests": sum(metrics.requests.values()),
    }
