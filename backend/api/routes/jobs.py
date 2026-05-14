from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from core.database import get_db
from core.security import get_cipher
from core.auth import get_current_user, require_editor, require_operator
from models import (
    Connection,
    DestinationMode,
    Job,
    JobLog,
    JobStatus,
    JobTask,
    LoadStrategy,
    MigrationChunkManifest,
    MigrationCostActual,
    MigrationCostEstimate,
    MigrationRun,
    MigrationRunEvent,
    MigrationSchemaDriftResult,
    MigrationSnowflakeQuery,
    MigrationState,
    MigrationTaskRun,
    MigrationValidationResult,
    User,
)
from services.snowflake_session_manager import SNOWFLAKE_MFA_EXPIRED_MESSAGE, snowflake_session_manager
from services.snowflake_connection import normalize_snowflake_config, snowflake_execution_readiness

router = APIRouter()
logger = logging.getLogger("uma.routes.jobs")


def _snowflake_job_guard(cfg: Dict[str, Any], *, session_active: bool) -> dict[str, Any]:
    return snowflake_execution_readiness(normalize_snowflake_config(cfg), session_active=session_active)


class TaskCreate(BaseModel):
    source_dataset: str
    source_table: str
    target_schema: str
    target_table: str
    config: Dict[str, Any] = {}


class JobCreate(BaseModel):
    name: str
    source_connection_id: str
    dest_connection_id: str
    sf_warehouse: str = ""
    sf_database: str = ""
    sf_schema: str = ""
    sf_role: str = ""
    destination_mode: str = "internal"
    load_strategy: str = "full_load"
    file_format: str = "parquet"
    staging_area: str = "internal"
    schedule_cron: Optional[str] = None
    tasks: List[TaskCreate] = []


class JobScheduleUpdate(BaseModel):
    schedule_cron: Optional[str] = None


def _job_dict(job: Job) -> dict:
    succeeded = sum(1 for t in job.tasks if t.status.value == "SUCCEEDED")
    failed    = sum(1 for t in job.tasks if t.status.value == "FAILED")
    src_type  = job.source_connection.type.value if job.source_connection else "unknown"
    return {
        "id": job.id,
        "name": job.name,
        "source_connection_id": job.source_connection_id,
        "dest_connection_id": job.dest_connection_id,
        "source_connection_type": src_type,
        "source_connection_name": job.source_connection.name if job.source_connection else "",
        "dest_connection_name": job.dest_connection.name if job.dest_connection else "",
        "sf_warehouse": job.sf_warehouse,
        "sf_database": job.sf_database,
        "sf_schema": job.sf_schema,
        "sf_role": job.sf_role,
        "destination_mode": job.destination_mode.value,
        "load_strategy": job.load_strategy.value,
        "file_format": job.file_format,
        "staging_area": job.staging_area,
        "schedule_cron": job.schedule_cron,
        "status": job.status.value,
        "phase": job.phase,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "total_rows_exported": job.total_rows_exported,
        "total_bytes": job.total_bytes,
        "total_bytes_gb": round((job.total_bytes or 0) / 1e9, 2),
        "export_duration_s": job.export_duration_s,
        "stage_duration_s": job.stage_duration_s,
        "load_duration_s": job.load_duration_s,
        "task_count": len(job.tasks),
        "tasks_succeeded": succeeded,
        "tasks_failed": failed,
        "created_at": job.created_at.isoformat(),
    }


def _task_dict(t: JobTask) -> dict:
    return {
        "id": t.id,
        "job_id": t.job_id,
        "source_dataset": t.source_dataset,
        "source_table": t.source_table,
        "target_schema": t.target_schema,
        "target_table": t.target_table,
        "config": t.config or {},
        "status": t.status.value,
        "long_text_columns": t.long_text_columns,
        "rows_exported": t.rows_exported,
        "bytes_exported": t.bytes_exported,
        "copy_statement": t.copy_statement,
        "create_statement": t.create_statement,
        "error_message": t.error_message,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
    }


# ── IMPORTANT: static routes MUST come before /{job_id} ──────

@router.get("/stats/summary")
async def get_stats(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate job stats for the dashboard."""
    result = await db.execute(select(func.count(Job.id), func.sum(Job.total_bytes)))
    row = result.one()
    total_jobs  = row[0] or 0
    total_bytes = row[1] or 0

    status_result = await db.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status)
    )
    by_status = {r[0].value: r[1] for r in status_result}

    return {
        "total_jobs": total_jobs,
        "total_gb": round(total_bytes / 1e9, 1),
        "by_status": by_status,
    }


@router.get("")
async def list_jobs(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Job)
        .options(
            selectinload(Job.tasks),
            selectinload(Job.source_connection),
            selectinload(Job.dest_connection),
        )
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        q = q.where(Job.status == status)
    result = await db.execute(q)
    jobs = result.scalars().unique().all()
    return [_job_dict(j) for j in jobs]


@router.post("", status_code=201)
async def create_job(
    body: JobCreate,
    _user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    src = await db.get(Connection, body.source_connection_id)
    dst = await db.get(Connection, body.dest_connection_id)
    if not src: raise HTTPException(400, "Source connection not found")
    if not dst: raise HTTPException(400, "Destination connection not found")

    try:
        dest_mode  = DestinationMode(body.destination_mode)
        load_strat = LoadStrategy(body.load_strategy)
    except ValueError as e:
        raise HTTPException(400, str(e))

    dst_cfg = dst.config or {}
    decrypted = get_cipher().decrypt_dict(dst.credentials) if dst.credentials else {}
    dst_cfg_full = normalize_snowflake_config({**dst_cfg, **decrypted})
    sf_warehouse = (body.sf_warehouse or dst_cfg_full.get("warehouse") or "").strip()
    sf_database = (body.sf_database or dst_cfg_full.get("database") or "").strip()
    sf_schema = (body.sf_schema or dst_cfg_full.get("schema") or "").strip()
    sf_role = (body.sf_role or dst_cfg_full.get("role") or "").strip()
    if dst.type == ConnectionType.snowflake:
        readiness = _snowflake_job_guard(
            {
                **dst_cfg_full,
                "warehouse": sf_warehouse,
                "database": sf_database,
                "schema": sf_schema,
                "role": sf_role,
            },
            session_active=False,
        )
        if readiness["missing_fields"]:
            raise HTTPException(400, readiness["message"])

    job = Job(
        name=body.name,
        source_connection_id=body.source_connection_id,
        dest_connection_id=body.dest_connection_id,
        sf_warehouse=sf_warehouse,
        sf_database=sf_database,
        sf_schema=sf_schema,
        sf_role=sf_role,
        destination_mode=dest_mode,
        load_strategy=load_strat,
        file_format=body.file_format,
        staging_area=body.staging_area,
        schedule_cron=body.schedule_cron,
    )
    db.add(job)
    await db.flush()

    for t in body.tasks:
        db.add(JobTask(
            job_id=job.id,
            source_dataset=t.source_dataset,
            source_table=t.source_table,
            target_schema=t.target_schema,
            target_table=t.target_table,
            config=t.config or {},
        ))

    await db.commit()
    # Reload with relationships
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.tasks), selectinload(Job.source_connection), selectinload(Job.dest_connection))
        .where(Job.id == job.id)
    )
    job = result.scalar_one()
    return _job_dict(job)


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.tasks), selectinload(Job.source_connection), selectinload(Job.dest_connection))
        .where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job: raise HTTPException(404, "Job not found")
    return _job_dict(job)


@router.post("/{job_id}/execute")
async def execute_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    engine: str = "auto",
    _user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    dest_conn = await db.get(Connection, job.dest_connection_id)
    if dest_conn and dest_conn.type.value == "snowflake":
        cfg = {
            **(dest_conn.config or {}),
            **(get_cipher().decrypt_dict(dest_conn.credentials) if dest_conn.credentials else {}),
        }
        session_active = bool(
            snowflake_session_manager.get_active_session(user_id=str(_user.id), connection_id=dest_conn.id)
        )
        readiness = _snowflake_job_guard(cfg, session_active=session_active)
        if readiness["missing_fields"]:
            job.status = JobStatus.failed
            job.phase = "REQUIRES_CONFIGURATION"
            db.add(JobLog(
                job_id=job.id,
                level="ERROR",
                event="SNOWFLAKE_CONFIGURATION_REQUIRED",
                message=readiness["message"],
                detail=f"missing_fields={','.join(readiness['missing_fields'])}",
            ))
            await db.commit()
            raise HTTPException(409, readiness["message"])
        if readiness["requires_mfa_session"] and not readiness["session_active"]:
            job.status = JobStatus.failed
            job.phase = "SNOWFLAKE_SESSION_REQUIRED"
            db.add(JobLog(
                job_id=job.id,
                level="ERROR",
                event="SNOWFLAKE_SESSION_EXPIRED",
                message=SNOWFLAKE_MFA_EXPIRED_MESSAGE,
                detail="retryable=true; recommended_action=Unlock Snowflake and retry.",
            ))
            await db.commit()
            raise HTTPException(409, SNOWFLAKE_MFA_EXPIRED_MESSAGE)

    if engine not in {"auto", "real", "legacy"}:
        raise HTTPException(400, "engine must be one of: auto, real, legacy")

    from services.job_run_locks import acquire_job_run_lease, new_holder_id
    from services.migration_orchestrator import execute_job as execute_migration_job, select_engine

    selection = await select_engine(job_id, engine)
    lease = await acquire_job_run_lease(job_id, new_holder_id("api"))
    if not lease:
        raise HTTPException(409, "Job is already running")
    background_tasks.add_task(execute_migration_job, job_id, engine, lease.holder_id, str(_user.id))
    return {
        "message": "Migration execution started",
        "job_id": job_id,
        "engine": selection.selected,
        "engine_selection": selection.__dict__,
    }


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    _user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """Mark a running job as CANCELLED. The engine polls this status between
    tables and stops at the next checkpoint. Already-running table operations
    are NOT interrupted mid-stream — this is a soft cancel."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.running:
        raise HTTPException(409, f"Cannot cancel a job in status {job.status.value}")
    job.status = JobStatus.cancelled
    job.phase = "CANCEL_REQUESTED"
    job.updated_at = datetime.utcnow()
    db.add(JobLog(
        job_id=job.id, level="INFO", event="CANCEL_REQUESTED",
        message="Cancellation requested by user — engine will stop at next checkpoint",
    ))
    await db.commit()
    return {"job_id": job.id, "status": job.status.value}


@router.post("/{job_id}/execute-real")
async def execute_job_real_now(
    job_id: str,
    _user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """Run the selected engine synchronously; useful for local smoke testing and debugging."""
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    dest_conn = await db.get(Connection, job.dest_connection_id)
    if dest_conn and dest_conn.type.value == "snowflake":
        cfg = {
            **(dest_conn.config or {}),
            **(get_cipher().decrypt_dict(dest_conn.credentials) if dest_conn.credentials else {}),
        }
        session_active = bool(
            snowflake_session_manager.get_active_session(user_id=str(_user.id), connection_id=dest_conn.id)
        )
        readiness = _snowflake_job_guard(cfg, session_active=session_active)
        if readiness["missing_fields"]:
            job.status = JobStatus.failed
            job.phase = "REQUIRES_CONFIGURATION"
            db.add(JobLog(
                job_id=job.id,
                level="ERROR",
                event="SNOWFLAKE_CONFIGURATION_REQUIRED",
                message=readiness["message"],
                detail=f"missing_fields={','.join(readiness['missing_fields'])}",
            ))
            await db.commit()
            raise HTTPException(409, readiness["message"])
        if readiness["requires_mfa_session"] and not readiness["session_active"]:
            job.status = JobStatus.failed
            job.phase = "SNOWFLAKE_SESSION_REQUIRED"
            db.add(JobLog(
                job_id=job.id,
                level="ERROR",
                event="SNOWFLAKE_SESSION_EXPIRED",
                message=SNOWFLAKE_MFA_EXPIRED_MESSAGE,
                detail="retryable=true; recommended_action=Unlock Snowflake and retry.",
            ))
            await db.commit()
            raise HTTPException(409, SNOWFLAKE_MFA_EXPIRED_MESSAGE)
    from services.job_run_locks import acquire_job_run_lease, new_holder_id, release_job_run_lease
    from services.migration_orchestrator import execute_job as execute_migration_job

    lease = await acquire_job_run_lease(job_id, new_holder_id("api"))
    if not lease:
        raise HTTPException(409, "Job is already running")
    try:
        result = await execute_migration_job(job_id, "real", lease.holder_id, str(_user.id))
    finally:
        await release_job_run_lease(job_id, lease.holder_id)
    if result.get("conflict"):
        raise HTTPException(409, "Job is already running")
    if not result.get("success"):
        raise HTTPException(500, result)
    return result


@router.get("/{job_id}/runs")
async def get_job_runs(
    job_id: str,
    limit: int = 50,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run history for a job, newest first. Includes per-run task-run aggregates."""
    if not await db.get(Job, job_id):
        raise HTTPException(404, "Job not found")
    runs = (
        await db.execute(
            select(MigrationRun)
            .where(MigrationRun.job_id == job_id)
            .order_by(MigrationRun.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    if not runs:
        return []
    # Bulk-fetch task-run counts so we don't N+1
    run_ids = [r.id for r in runs]
    task_count_rows = (
        await db.execute(
            select(MigrationTaskRun.run_id, MigrationTaskRun.status, func.count(MigrationTaskRun.id))
            .where(MigrationTaskRun.run_id.in_(run_ids))
            .group_by(MigrationTaskRun.run_id, MigrationTaskRun.status)
        )
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for run_id, status, n in task_count_rows:
        counts.setdefault(run_id, {})[status] = int(n)

    out = []
    for r in runs:
        c = counts.get(r.id, {})
        duration_s = None
        if r.started_at and r.ended_at:
            duration_s = (r.ended_at - r.started_at).total_seconds()
        out.append({
            "id": r.id,
            "status": r.status,
            "mode": r.mode,
            "attempt_number": r.attempt_number,
            "rows_extracted": r.rows_extracted,
            "rows_loaded": r.rows_loaded,
            "rows_merged": r.rows_merged,
            "rows_deleted": r.rows_deleted,
            "bytes_staged": r.bytes_staged,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "duration_s": duration_s,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "task_counts": {
                "succeeded": c.get("SUCCEEDED", 0),
                "failed": c.get("FAILED", 0),
                "running": c.get("RUNNING", 0),
                "total": sum(c.values()),
            },
        })
    return out


@router.get("/{job_id}/runs/{run_id}")
async def get_run_detail(
    job_id: str,
    run_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Single run plus its per-table task-runs."""
    run = (
        await db.execute(
            select(MigrationRun).where(
                MigrationRun.id == run_id, MigrationRun.job_id == job_id
            )
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    task_runs = (
        await db.execute(
            select(MigrationTaskRun)
            .where(MigrationTaskRun.run_id == run_id)
            .order_by(MigrationTaskRun.started_at.asc().nullslast())
        )
    ).scalars().all()
    chunks = (
        await db.execute(
            select(MigrationChunkManifest)
            .where(MigrationChunkManifest.run_id == run_id)
            .order_by(MigrationChunkManifest.task_id.asc(), MigrationChunkManifest.chunk_index.asc())
        )
    ).scalars().all()
    validations = (
        await db.execute(
            select(MigrationValidationResult)
            .where(MigrationValidationResult.run_id == run_id)
            .order_by(MigrationValidationResult.created_at.asc())
        )
    ).scalars().all()
    events = (
        await db.execute(
            select(MigrationRunEvent)
            .where(MigrationRunEvent.run_id == run_id)
            .order_by(MigrationRunEvent.created_at.asc())
        )
    ).scalars().all()
    drift = (
        await db.execute(
            select(MigrationSchemaDriftResult)
            .where(MigrationSchemaDriftResult.run_id == run_id)
            .order_by(MigrationSchemaDriftResult.created_at.asc())
        )
    ).scalars().all()

    duration_s = None
    if run.started_at and run.ended_at:
        duration_s = (run.ended_at - run.started_at).total_seconds()
    return {
        "run": {
            "id": run.id,
            "job_id": run.job_id,
            "status": run.status,
            "mode": run.mode,
            "attempt_number": run.attempt_number,
            "rows_extracted": run.rows_extracted,
            "rows_loaded": run.rows_loaded,
            "rows_merged": run.rows_merged,
            "rows_deleted": run.rows_deleted,
            "bytes_staged": run.bytes_staged,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "duration_s": duration_s,
            "error_message": run.error_message,
        },
        "task_runs": [{
            "id": tr.id,
            "task_id": tr.task_id,
            "table_key": tr.table_key,
            "target_table": tr.target_table,
            "status": tr.status,
            "rows_extracted": tr.rows_extracted,
            "rows_loaded": tr.rows_loaded,
            "rows_merged": tr.rows_merged,
            "rows_deleted": tr.rows_deleted,
            "bytes_staged": tr.bytes_staged,
            "batch_count": tr.batch_count,
            "watermark_start": tr.watermark_start,
            "watermark_end": tr.watermark_end,
            "started_at": tr.started_at.isoformat() if tr.started_at else None,
            "ended_at": tr.ended_at.isoformat() if tr.ended_at else None,
            "duration_s": (
                (tr.ended_at - tr.started_at).total_seconds()
                if tr.started_at and tr.ended_at else None
            ),
            "error_message": tr.error_message,
        } for tr in task_runs],
        "chunk_manifest": [{
            "id": c.id,
            "task_id": c.task_id,
            "table_key": c.table_key,
            "chunk_index": c.chunk_index,
            "state": c.state,
            "stage_table": c.stage_table,
            "row_count": c.row_count,
            "bytes_staged": c.bytes_staged,
            "watermark_start": c.watermark_start,
            "watermark_end": c.watermark_end,
            "primary_key_end": c.primary_key_end,
            "error_message": c.error_message,
        } for c in chunks],
        "validation_results": [{
            "id": v.id,
            "task_id": v.task_id,
            "table_key": v.table_key,
            "rule_type": v.rule_type,
            "severity": v.severity,
            "status": v.status,
            "source_value": v.source_value,
            "target_value": v.target_value,
            "delta": v.delta,
            "message": v.message,
            "result_json": v.result_json or {},
            "created_at": v.created_at.isoformat() if v.created_at else None,
        } for v in validations],
        "events": [{
            "id": e.id,
            "task_id": e.task_id,
            "table_key": e.table_key,
            "phase": e.phase,
            "event": e.event,
            "level": e.level,
            "message": e.message,
            "rows_extracted": e.rows_extracted,
            "rows_loaded": e.rows_loaded,
            "rows_merged": e.rows_merged,
            "rows_deleted": e.rows_deleted,
            "chunk_count": e.chunk_count,
            "error_category": e.error_category,
            "event_json": e.event_json or {},
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events],
        "schema_drift": [{
            "id": d.id,
            "task_id": d.task_id,
            "table_key": d.table_key,
            "drift_type": d.drift_type,
            "column_name": d.column_name,
            "source_type": d.source_type,
            "target_type": d.target_type,
            "source_nullable": d.source_nullable,
            "target_nullable": d.target_nullable,
            "severity": d.severity,
            "action_taken": d.action_taken,
            "result_json": d.result_json or {},
            "created_at": d.created_at.isoformat() if d.created_at else None,
        } for d in drift],
    }


@router.get("/{job_id}/runs/{run_id}/cost")
async def get_run_cost(
    job_id: str,
    run_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = (
        await db.execute(
            select(MigrationRun).where(
                MigrationRun.id == run_id, MigrationRun.job_id == job_id
            )
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    estimates = (
        await db.execute(
            select(MigrationCostEstimate)
            .where(MigrationCostEstimate.job_id == job_id, MigrationCostEstimate.run_id == run_id)
            .order_by(MigrationCostEstimate.created_at.asc())
        )
    ).scalars().all()
    actual = (
        await db.execute(
            select(MigrationCostActual).where(
                MigrationCostActual.job_id == job_id,
                MigrationCostActual.run_id == run_id,
            )
        )
    ).scalar_one_or_none()
    queries = (
        await db.execute(
            select(MigrationSnowflakeQuery)
            .where(MigrationSnowflakeQuery.job_id == job_id, MigrationSnowflakeQuery.run_id == run_id)
            .order_by(MigrationSnowflakeQuery.created_at.asc())
        )
    ).scalars().all()
    return {
        "job_id": job_id,
        "run_id": run_id,
        "estimates": [{
            "id": e.id,
            "table_name": e.table_name,
            "estimated_rows": e.estimated_rows,
            "estimated_source_bytes": e.estimated_source_bytes,
            "estimated_compressed_bytes": e.estimated_compressed_bytes,
            "estimated_runtime_seconds": e.estimated_runtime_seconds,
            "estimated_credits": e.estimated_credits,
            "estimated_cost": e.estimated_cost,
            "currency": e.currency,
            "confidence_level": e.confidence_level,
            "assumptions": e.assumptions or {},
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in estimates],
        "actual": None if not actual else {
            "id": actual.id,
            "warehouse_credits": actual.warehouse_credits,
            "query_attributed_credits": actual.query_attributed_credits,
            "cloud_services_credits": actual.cloud_services_credits,
            "cortex_credits": actual.cortex_credits,
            "snowpark_credits": actual.snowpark_credits,
            "storage_cost": actual.storage_cost,
            "total_estimated_cost": actual.total_estimated_cost,
            "total_actual_cost": actual.total_actual_cost,
            "cost_variance_percent": actual.cost_variance_percent,
            "status": actual.status,
            "reconciled_at": actual.reconciled_at.isoformat() if actual.reconciled_at else None,
        },
        "queries": [{
            "id": q.id,
            "task_id": q.task_id,
            "table_name": q.table_name,
            "phase": q.phase,
            "query_id": q.query_id,
            "query_tag": q.query_tag,
            "warehouse_name": q.warehouse_name,
            "status": q.status,
            "credits_attributed": q.credits_attributed,
            "actual_cost": q.actual_cost,
            "created_at": q.created_at.isoformat() if q.created_at else None,
        } for q in queries],
    }


@router.get("/{job_id}/state")
async def get_job_state(
    job_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await db.get(Job, job_id):
        raise HTTPException(404, "Job not found")
    states = (await db.execute(select(MigrationState).where(MigrationState.job_id == job_id))).scalars().all()
    return [{
        "id": s.id,
        "job_id": s.job_id,
        "task_id": s.task_id,
        "table_key": s.table_key,
        "strategy": s.strategy,
        "primary_key_columns": s.primary_key_columns,
        "watermark_column": s.watermark_column,
        "last_watermark_value": s.last_watermark_value,
        "last_primary_key_value": (s.state_json or {}).get("last_primary_key_value"),
        "last_successful_run_id": s.last_successful_run_id,
        "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
        "metadata": s.state_json or {},
    } for s in states]


@router.put("/{job_id}/schedule")
async def update_schedule(
    job_id: str,
    body: JobScheduleUpdate,
    _user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the cron schedule for a job."""
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    job.schedule_cron = body.schedule_cron
    job.updated_at = datetime.utcnow()
    await db.commit()
    return {"job_id": job_id, "schedule_cron": job.schedule_cron}


@router.get("/{job_id}/tasks")
async def list_tasks(
    job_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(JobTask).where(JobTask.job_id == job_id))
    return [_task_dict(t) for t in result.scalars().all()]


@router.post("/{job_id}/tasks")
async def add_task(
    job_id: str,
    body: TaskCreate,
    _user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    task = JobTask(job_id=job_id, **body.dict())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task_dict(task)


@router.delete("/{job_id}/tasks/{task_id}", status_code=204)
async def delete_task(
    job_id: str,
    task_id: str,
    _user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(JobTask, task_id)
    if not task or task.job_id != job_id:
        raise HTTPException(404, "Task not found")
    await db.delete(task)
    await db.commit()


@router.get("/{job_id}/logs")
async def get_logs(
    job_id: str,
    level: Optional[str] = None,
    task_ref: Optional[str] = None,
    limit: int = 200,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(JobLog)
        .where(JobLog.job_id == job_id)
        .order_by(JobLog.created_at.desc())
        .limit(limit)
    )
    if level:    q = q.where(JobLog.level == level)
    if task_ref: q = q.where(JobLog.task_ref == task_ref)
    result = await db.execute(q)
    return [{
        "id": l.id, "job_id": l.job_id, "task_ref": l.task_ref,
        "level": l.level.value, "event": l.event, "message": l.message,
        "detail": l.detail, "created_at": l.created_at.isoformat(),
    } for l in result.scalars().all()]


@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    _user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    if job.status == JobStatus.running:
        raise HTTPException(409, "Cannot delete a running job")
    await db.delete(job)
    await db.commit()
