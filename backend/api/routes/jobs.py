from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from core.database import get_db
from models import Job, JobTask, JobLog, JobStatus, LoadStrategy, DestinationMode, Connection, MigrationRun, MigrationTaskRun, MigrationState

router = APIRouter()
logger = logging.getLogger("uma.routes.jobs")


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
async def get_stats(db: AsyncSession = Depends(get_db)):
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
async def create_job(body: JobCreate, db: AsyncSession = Depends(get_db)):
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
    sf_warehouse = (body.sf_warehouse or dst_cfg.get("warehouse") or "").strip()
    sf_database = (body.sf_database or dst_cfg.get("database") or "").strip()
    sf_schema = (body.sf_schema or dst_cfg.get("schema") or "").strip()
    sf_role = (body.sf_role or dst_cfg.get("role") or "").strip()

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
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
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
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    if job.status == JobStatus.running:
        raise HTTPException(409, "Job is already running")

    if engine not in {"auto", "real", "legacy"}:
        raise HTTPException(400, "engine must be one of: auto, real, legacy")

    from services.migration_orchestrator import execute_job as execute_migration_job, select_engine

    selection = await select_engine(job_id, engine)
    background_tasks.add_task(execute_migration_job, job_id, engine)
    return {
        "message": "Migration execution started",
        "job_id": job_id,
        "engine": selection.selected,
        "engine_selection": selection.__dict__,
    }


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
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
async def execute_job_real_now(job_id: str, db: AsyncSession = Depends(get_db)):
    """Run the selected engine synchronously; useful for local smoke testing and debugging."""
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    if job.status == JobStatus.running:
        raise HTTPException(409, "Job is already running")
    from services.migration_orchestrator import execute_job as execute_migration_job
    result = await execute_migration_job(job_id, "real")
    if not result.get("success"):
        raise HTTPException(500, result)
    return result


@router.get("/{job_id}/runs")
async def get_job_runs(job_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
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
async def get_run_detail(job_id: str, run_id: str, db: AsyncSession = Depends(get_db)):
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
    }


@router.get("/{job_id}/state")
async def get_job_state(job_id: str, db: AsyncSession = Depends(get_db)):
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
        "last_successful_run_id": s.last_successful_run_id,
        "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
        "metadata": s.state_json or {},
    } for s in states]


@router.put("/{job_id}/schedule")
async def update_schedule(
    job_id: str,
    body: JobScheduleUpdate,
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
async def list_tasks(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobTask).where(JobTask.job_id == job_id))
    return [_task_dict(t) for t in result.scalars().all()]


@router.post("/{job_id}/tasks")
async def add_task(job_id: str, body: TaskCreate, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    task = JobTask(job_id=job_id, **body.dict())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task_dict(task)


@router.delete("/{job_id}/tasks/{task_id}", status_code=204)
async def delete_task(job_id: str, task_id: str, db: AsyncSession = Depends(get_db)):
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
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    if job.status == JobStatus.running:
        raise HTTPException(409, "Cannot delete a running job")
    await db.delete(job)
    await db.commit()
