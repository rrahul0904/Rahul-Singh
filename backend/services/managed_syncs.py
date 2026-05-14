from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from core.database import AsyncSessionLocal
from models import (
    DestinationMode,
    Job,
    JobStatus,
    JobTask,
    LoadStrategy,
    SyncProfile,
    SyncRun,
)
from services.snowflake_connection import normalize_snowflake_config


def sync_mode_to_load_strategy(mode: str) -> LoadStrategy:
    if mode == "full_refresh":
        return LoadStrategy.full_load
    if mode == "cdc":
        return LoadStrategy.cdc
    return LoadStrategy.incremental


def build_task_config(
    primary_key_columns: list[str] | None = None,
    watermark_column: Optional[str] = None,
    delete_flag_column: Optional[str] = None,
    batch_size: int = 50000,
) -> dict[str, Any]:
    return {
        "primary_key_columns": primary_key_columns or [],
        "watermark_column": watermark_column or None,
        "delete_flag_column": delete_flag_column or None,
        "batch_size": int(batch_size or 50000),
    }


def build_job_defaults(dest_config: dict[str, Any] | None) -> dict[str, str]:
    cfg = normalize_snowflake_config(dest_config)
    return {
        "sf_warehouse": (cfg.get("warehouse") or "").strip(),
        "sf_database": (cfg.get("database") or "").strip(),
        "sf_schema": (cfg.get("schema") or "").strip(),
        "sf_role": (cfg.get("role") or "").strip(),
    }


async def create_or_update_managed_job(
    profile: SyncProfile,
    dest_config: dict[str, Any] | None,
    *,
    load_strategy: LoadStrategy,
    destination_mode: DestinationMode,
    is_active: bool,
) -> str:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, profile.job_id) if profile.job_id else None
        defaults = build_job_defaults(dest_config)
        if not job:
            job = Job(
                name=profile.name,
                source_connection_id=profile.source_connection_id,
                dest_connection_id=profile.dest_connection_id,
                schedule_cron=profile.cadence if is_active else None,
                load_strategy=load_strategy,
                destination_mode=destination_mode,
                file_format="parquet",
                staging_area="internal",
                **defaults,
            )
            db.add(job)
            await db.flush()
            db.add(
                JobTask(
                    job_id=job.id,
                    source_dataset=profile.source_dataset or "",
                    source_table=profile.source_table or "",
                    target_schema=profile.target_schema or "",
                    target_table=profile.target_table or "",
                    config=profile.task_config or {},
                )
            )
        else:
            job.name = profile.name
            job.source_connection_id = profile.source_connection_id
            job.dest_connection_id = profile.dest_connection_id
            job.schedule_cron = profile.cadence if is_active else None
            job.load_strategy = load_strategy
            job.destination_mode = destination_mode
            for key, value in defaults.items():
                if not getattr(job, key, ""):
                    setattr(job, key, value)
            task = (
                await db.execute(
                    select(JobTask).where(JobTask.job_id == job.id).order_by(JobTask.id.asc())
                )
            ).scalars().first()
            if not task:
                task = JobTask(
                    job_id=job.id,
                    source_dataset=profile.source_dataset or "",
                    source_table=profile.source_table or "",
                    target_schema=profile.target_schema or "",
                    target_table=profile.target_table or "",
                    config=profile.task_config or {},
                )
                db.add(task)
            else:
                task.source_dataset = profile.source_dataset or ""
                task.source_table = profile.source_table or ""
                task.target_schema = profile.target_schema or ""
                task.target_table = profile.target_table or ""
                task.config = profile.task_config or {}
        await db.commit()
        return job.id


async def create_running_sync_run(profile_id: str) -> str:
    async with AsyncSessionLocal() as db:
        run = SyncRun(
            profile_id=profile_id,
            status="RUNNING",
            rows_synced=0,
            bytes_synced=0,
            started_at=datetime.utcnow(),
            error_message="",
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def finalize_sync_run_for_job(job_id: str, result: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as db:
        profile = (
            await db.execute(select(SyncProfile).where(SyncProfile.job_id == job_id))
        ).scalars().first()
        if not profile:
            return

        sync_run = (
            await db.execute(
                select(SyncRun)
                .where(SyncRun.profile_id == profile.id, SyncRun.status == "RUNNING")
                .order_by(SyncRun.created_at.desc())
            )
        ).scalars().first()

        if not sync_run:
            sync_run = SyncRun(
                profile_id=profile.id,
                status="RUNNING",
                rows_synced=0,
                bytes_synced=0,
                started_at=datetime.utcnow(),
                error_message="",
            )
            db.add(sync_run)
            await db.flush()

        sync_run.status = "SUCCEEDED" if result.get("success") else "FAILED"
        sync_run.rows_synced = int(result.get("rows_loaded") or 0)
        sync_run.bytes_synced = int(result.get("bytes_staged") or 0)
        sync_run.ended_at = datetime.utcnow()
        sync_run.error_message = (result.get("error") or "")[:2000]
        await db.commit()


async def mark_sync_run_failed(profile_id: str, sync_run_id: str, error_message: str) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.get(SyncRun, sync_run_id)
        if not run or run.profile_id != profile_id:
            return
        run.status = "FAILED"
        run.ended_at = datetime.utcnow()
        run.error_message = (error_message or "Managed sync execution failed")[:2000]
        await db.commit()


async def delete_managed_job(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return
        if job.status == JobStatus.running:
            raise ValueError("Cannot delete a running managed sync job")
        await db.delete(job)
        await db.commit()
