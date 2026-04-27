"""
UMA Platform — Migration execution gateway.

This module is the single dispatch point for job execution. API routes,
workers, and schedulers should call this instead of importing individual
engine implementations directly.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Literal

from sqlalchemy.orm import selectinload
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models import ConnectionType, Job

logger = logging.getLogger("uma.migration_orchestrator")

EngineName = Literal["real", "legacy", "auto"]

REAL_ENGINE_SOURCES = {
    ConnectionType.bigquery,
    ConnectionType.postgres,
    ConnectionType.redshift,
    ConnectionType.mysql,
}


@dataclass(frozen=True)
class EngineSelection:
    requested: str
    selected: str
    reason: str
    source_type: str
    destination_type: str


async def select_engine(job_id: str, requested: EngineName = "auto") -> EngineSelection:
    """Choose the safest available engine for a job."""
    async with AsyncSessionLocal() as db:
        job = (
            await db.execute(
                select(Job)
                .options(selectinload(Job.source_connection), selectinload(Job.dest_connection))
                .where(Job.id == job_id)
            )
        ).scalar_one_or_none()
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        if not job.source_connection or not job.dest_connection:
            raise ValueError("Job source or destination connection is missing")

        source_type = job.source_connection.type
        destination_type = job.dest_connection.type

    if requested == "legacy":
        selected = "legacy"
        reason = "Legacy engine explicitly requested"
    elif destination_type != ConnectionType.snowflake:
        selected = "legacy"
        reason = "Real engine currently writes only to Snowflake"
    elif source_type in REAL_ENGINE_SOURCES:
        selected = "real"
        reason = "Real engine supports this source-to-Snowflake path"
    else:
        selected = "legacy"
        reason = "Source is not yet implemented by the real engine"

    return EngineSelection(
        requested=requested,
        selected=selected,
        reason=reason,
        source_type=source_type.value,
        destination_type=destination_type.value,
    )


async def execute_job(job_id: str, requested_engine: EngineName = "auto") -> dict[str, Any]:
    """Execute a migration job using the selected engine."""
    selection = await select_engine(job_id, requested_engine)
    logger.info(
        "Executing job %s with %s engine (%s)",
        job_id,
        selection.selected,
        selection.reason,
    )

    if selection.selected == "real":
        from services.real_migration_engine import RealMigrationEngine

        result = await RealMigrationEngine(job_id).execute()
    else:
        from services.job_engine import JobEngine

        await JobEngine(job_id).execute()
        result = {"success": True}

    return {
        **result,
        "job_id": job_id,
        "engine": selection.selected,
        "engine_selection": asdict(selection),
    }


async def execution_capabilities() -> dict[str, Any]:
    """Return the engine support matrix for service health and diagnostics."""
    return {
        "default_engine": "auto",
        "real_engine": {
            "status": "available",
            "sources": sorted(t.value for t in REAL_ENGINE_SOURCES),
            "destination": ConnectionType.snowflake.value,
            "features": [
                "local parquet chunking",
                "full load",
                "incremental watermark loads",
                "upsert/cdc merge by primary key",
                "run/task-run history",
                "soft cancellation between tables",
            ],
        },
        "legacy_engine": {
            "status": "available",
            "role": "fallback for connector export/stage/copy paths not yet covered by the real engine",
        },
    }
