"""
UMA Platform — Health Endpoints
  /api/health        — basic liveness (always returns 200 if process is up)
  /api/health/live   — K8s liveness probe (same as above)
  /api/health/ready  — K8s readiness probe (checks DB + Redis)
  /api/metrics       — Prometheus metrics
"""

import logging
import os
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.config import settings
from models import Connection, Job, JobStatus, MigrationRun, SyncProfile

router = APIRouter()
logger = logging.getLogger("uma.health")

_start_time = time.time()


@router.get("/health")
async def health():
    """Basic liveness — process is up."""
    return {
        "status":      "ok",
        "service":     "UMA Platform API",
        "version":     settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "build_sha":   settings.BUILD_SHA,
        "build_time":  settings.BUILD_TIME,
        "demo_mode":   settings.DEMO_MODE_ENABLED,
        "uptime_s":    int(time.time() - _start_time),
        "timestamp":   datetime.utcnow().isoformat(),
    }


@router.get("/health/live")
async def liveness():
    """K8s liveness probe — is the process responsive?"""
    return {"status": "live"}


@router.get("/health/ready")
async def readiness(response: Response, db: AsyncSession = Depends(get_db)):
    """
    K8s readiness probe — is the app ready to serve traffic?
    Checks: DB connectivity, Redis reachability.
    Returns 503 if any critical dependency is down.
    """
    checks = {}
    healthy = True

    # DB
    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        healthy = False
        logger.error(f"DB readiness check failed: {e}")

    # Redis (optional — degrade gracefully)
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(redis_url)
            await r.ping()
            await r.close()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"degraded: {type(e).__name__}"
            # Redis outage is not fatal for readiness — queue will retry

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if healthy else "not_ready",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health/services")
async def service_health(response: Response, db: AsyncSession = Depends(get_db)):
    """
    Service-level readiness for the migration accelerator control plane.
    This verifies the pieces that have to cooperate for a migration run:
    metadata DB, Redis queue, execution engines, scheduler state, and core tables.
    """
    checks = {}
    healthy = True

    try:
        counts = (
            await db.execute(
                select(
                    func.count(distinct(Connection.id)),
                    func.count(distinct(Job.id)),
                    func.count(distinct(MigrationRun.id)),
                    func.count(distinct(SyncProfile.id)),
                )
                .select_from(Connection)
                .outerjoin(Job, Job.source_connection_id == Connection.id)
                .outerjoin(MigrationRun, MigrationRun.job_id == Job.id)
                .outerjoin(SyncProfile, SyncProfile.source_connection_id == Connection.id)
            )
        ).one()
        checks["metadata"] = {
            "status": "ok",
            "connections": int(counts[0] or 0),
            "jobs": int(counts[1] or 0),
            "migration_runs": int(counts[2] or 0),
            "sync_profiles": int(counts[3] or 0),
        }
    except Exception as e:
        checks["metadata"] = {"status": "error", "error": type(e).__name__}
        healthy = False

    try:
        running_jobs = (
            await db.execute(select(func.count(Job.id)).where(Job.status == JobStatus.running))
        ).scalar_one()
        checks["jobs"] = {"status": "ok", "running": int(running_jobs or 0)}
    except Exception as e:
        checks["jobs"] = {"status": "error", "error": type(e).__name__}
        healthy = False

    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(redis_url)
            await r.ping()
            queued = await r.llen("arq:queue")
            await r.close()
            checks["redis_queue"] = {"status": "ok", "queued": int(queued or 0)}
        except Exception as e:
            checks["redis_queue"] = {"status": "degraded", "error": type(e).__name__}
    else:
        checks["redis_queue"] = {"status": "not_configured"}

    try:
        from services.migration_orchestrator import execution_capabilities

        checks["engines"] = await execution_capabilities()
    except Exception as e:
        checks["engines"] = {"status": "error", "error": type(e).__name__}
        healthy = False

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if healthy else "degraded",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus metrics endpoint."""
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return Response(
            content="# prometheus_client not installed\n",
            media_type="text/plain",
        )
