from datetime import datetime
from typing import Optional

from croniter import croniter
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_editor
from core.database import get_db
from models import Connection, ConnectionType, DestinationMode, SyncProfile, SyncRun, User
from services.managed_syncs import (
    build_task_config,
    create_or_update_managed_job,
    create_running_sync_run,
    delete_managed_job,
    mark_sync_run_failed,
    sync_mode_to_load_strategy,
)

router = APIRouter()


class SyncProfileCreate(BaseModel):
    name: str = Field(min_length=2)
    source_connection_id: str
    dest_connection_id: str
    source_dataset: str = Field(min_length=1)
    source_table: str = Field(min_length=1)
    target_schema: str = Field(min_length=1)
    target_table: str = Field(min_length=1)
    primary_key_columns: list[str] = []
    watermark_column: Optional[str] = None
    delete_flag_column: Optional[str] = None
    batch_size: int = 50000
    mode: str = "incremental"
    cadence: str = "0 2 * * *"
    schema_drift_policy: str = "warn"
    destination_mode: str = "internal"


class SyncProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2)
    source_connection_id: Optional[str] = None
    dest_connection_id: Optional[str] = None
    source_dataset: Optional[str] = None
    source_table: Optional[str] = None
    target_schema: Optional[str] = None
    target_table: Optional[str] = None
    primary_key_columns: Optional[list[str]] = None
    watermark_column: Optional[str] = None
    delete_flag_column: Optional[str] = None
    batch_size: Optional[int] = None
    mode: Optional[str] = None
    cadence: Optional[str] = None
    schema_drift_policy: Optional[str] = None
    destination_mode: Optional[str] = None
    is_active: Optional[bool] = None


ALLOWED_MODES = {"full_refresh", "incremental", "cdc"}
ALLOWED_DRIFT = {"warn", "auto_add", "block"}
ALLOWED_DEST = {"internal", "external_stage", "iceberg"}


def _next_run(cadence: str, ref: Optional[datetime] = None) -> Optional[datetime]:
    try:
        return croniter(cadence, ref or datetime.utcnow()).get_next(datetime)
    except Exception:
        return None


def _profile_dict(profile: SyncProfile, source: Optional[Connection] = None, dest: Optional[Connection] = None,
                  runs: Optional[list[SyncRun]] = None) -> dict:
    latest = runs[0] if runs else None
    next_run = _next_run(profile.cadence) if profile.is_active else None
    total_rows = sum(r.rows_synced or 0 for r in (runs or []))
    total_bytes = sum(r.bytes_synced or 0 for r in (runs or []))
    succeeded = sum(1 for r in (runs or []) if (r.status or "").upper() == "SUCCEEDED")
    failed = sum(1 for r in (runs or []) if (r.status or "").upper() == "FAILED")
    return {
        "id": profile.id,
        "name": profile.name,
        "source_connection_id": profile.source_connection_id,
        "dest_connection_id": profile.dest_connection_id,
        "job_id": profile.job_id,
        "source_dataset": profile.source_dataset,
        "source_table": profile.source_table,
        "target_schema": profile.target_schema,
        "target_table": profile.target_table,
        "task_config": profile.task_config or {},
        "source_connection_name": source.name if source else None,
        "dest_connection_name": dest.name if dest else None,
        "mode": profile.mode,
        "cadence": profile.cadence,
        "schema_drift_policy": profile.schema_drift_policy,
        "destination_mode": profile.destination_mode,
        "is_active": profile.is_active,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "next_run_at": next_run.isoformat() if next_run else None,
        "last_run": {
            "id": latest.id,
            "status": latest.status,
            "rows_synced": latest.rows_synced,
            "bytes_synced": latest.bytes_synced,
            "started_at": latest.started_at.isoformat() if latest.started_at else None,
            "ended_at": latest.ended_at.isoformat() if latest.ended_at else None,
            "error_message": latest.error_message,
        } if latest else None,
        "run_count": len(runs or []),
        "succeeded_runs": succeeded,
        "failed_runs": failed,
        "total_rows_synced": total_rows,
        "total_bytes_synced": total_bytes,
    }


async def _load_profile_context(db: AsyncSession, profile: SyncProfile):
    src = await db.get(Connection, profile.source_connection_id)
    dest = await db.get(Connection, profile.dest_connection_id)
    run_rows = await db.execute(
        select(SyncRun)
        .where(SyncRun.profile_id == profile.id)
        .order_by(SyncRun.created_at.desc())
        .limit(10)
    )
    runs = list(run_rows.scalars().all())
    return _profile_dict(profile, src, dest, runs), runs


def _normalize_task_config(payload: SyncProfileCreate | SyncProfileUpdate, existing: Optional[dict] = None) -> dict:
    base = dict(existing or {})
    if hasattr(payload, "primary_key_columns") and payload.primary_key_columns is not None:
        base["primary_key_columns"] = [c.strip() for c in payload.primary_key_columns if str(c).strip()]
    if hasattr(payload, "watermark_column") and payload.watermark_column is not None:
        base["watermark_column"] = payload.watermark_column.strip() or None
    if hasattr(payload, "delete_flag_column") and payload.delete_flag_column is not None:
        base["delete_flag_column"] = payload.delete_flag_column.strip() or None
    if hasattr(payload, "batch_size") and payload.batch_size is not None:
        base["batch_size"] = int(payload.batch_size or 50000)
    return build_task_config(
        primary_key_columns=base.get("primary_key_columns") or [],
        watermark_column=base.get("watermark_column"),
        delete_flag_column=base.get("delete_flag_column"),
        batch_size=int(base.get("batch_size") or 50000),
    )


async def _validate_sync_connections(
    db: AsyncSession, source_connection_id: str, dest_connection_id: str
) -> tuple[Connection, Connection]:
    src = await db.get(Connection, source_connection_id)
    dest = await db.get(Connection, dest_connection_id)
    if not src or not dest:
        raise HTTPException(400, "Source and destination connections must exist")
    if dest.type != ConnectionType.snowflake:
        raise HTTPException(400, "Managed syncs currently require a Snowflake destination")
    if src.type not in {ConnectionType.postgres, ConnectionType.mysql, ConnectionType.redshift, ConnectionType.bigquery}:
        raise HTTPException(400, f"Managed syncs do not yet support {src.type.value} as a source")
    return src, dest


async def _execute_profile_job(profile_id: str, job_id: str, sync_run_id: str):
    try:
        from services.migration_orchestrator import execute_job as execute_migration_job

        await execute_migration_job(job_id, "real")
    except Exception as exc:
        await mark_sync_run_failed(profile_id, sync_run_id, str(exc))


@router.get("/templates")
async def templates(_: User = Depends(get_current_user)):
    return [
        {"id": "full_refresh", "label": "Full refresh nightly", "mode": "full_refresh", "cadence": "0 2 * * *", "schema_drift_policy": "warn", "destination_mode": "internal"},
        {"id": "incremental", "label": "Incremental hourly", "mode": "incremental", "cadence": "0 * * * *", "schema_drift_policy": "warn", "destination_mode": "internal"},
        {"id": "cdc", "label": "CDC every 15 min", "mode": "cdc", "cadence": "*/15 * * * *", "schema_drift_policy": "auto_add", "destination_mode": "internal"},
    ]


@router.get("/overview")
async def overview(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profiles = list((await db.execute(select(SyncProfile))).scalars().all())
    runs = list((await db.execute(select(SyncRun))).scalars().all())
    run_map: dict[str, list[SyncRun]] = {}
    for run in runs:
        run_map.setdefault(run.profile_id, []).append(run)
    total_rows = sum(r.rows_synced or 0 for r in runs)
    total_bytes = sum(r.bytes_synced or 0 for r in runs)
    active = sum(1 for p in profiles if p.is_active)
    succeeded = sum(1 for r in runs if (r.status or "").upper() == "SUCCEEDED")
    failed = sum(1 for r in runs if (r.status or "").upper() == "FAILED")
    by_mode = {}
    for p in profiles:
        by_mode[p.mode] = by_mode.get(p.mode, 0) + 1
    latest_run = max(runs, key=lambda r: r.created_at) if runs else None
    next_runs = sorted(
        [nr for nr in (_next_run(p.cadence) if p.is_active else None for p in profiles) if nr],
        key=lambda d: d,
    )
    return {
        "profile_count": len(profiles),
        "active_profiles": active,
        "paused_profiles": len(profiles) - active,
        "run_count": len(runs),
        "succeeded_runs": succeeded,
        "failed_runs": failed,
        "rows_synced": total_rows,
        "bytes_synced": total_bytes,
        "by_mode": by_mode,
        "latest_run_at": latest_run.created_at.isoformat() if latest_run else None,
        "next_run_at": next_runs[0].isoformat() if next_runs else None,
    }


@router.get("/profiles")
async def list_profiles(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profiles = list((await db.execute(select(SyncProfile).order_by(SyncProfile.created_at.desc()))).scalars().all())
    src_ids = {p.source_connection_id for p in profiles}
    dst_ids = {p.dest_connection_id for p in profiles}
    conns = {}
    if src_ids or dst_ids:
        conn_rows = await db.execute(select(Connection).where(Connection.id.in_(list(src_ids | dst_ids))))
        conns = {c.id: c for c in conn_rows.scalars().all()}
    runs = list((await db.execute(select(SyncRun).order_by(SyncRun.created_at.desc()))).scalars().all())
    run_map: dict[str, list[SyncRun]] = {}
    for run in runs:
        run_map.setdefault(run.profile_id, []).append(run)
    return [_profile_dict(p, conns.get(p.source_connection_id), conns.get(p.dest_connection_id), run_map.get(p.id, [])[:10]) for p in profiles]


@router.post("/profiles")
async def create_profile(body: SyncProfileCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    if body.mode not in ALLOWED_MODES:
        raise HTTPException(400, "Invalid sync mode")
    if body.schema_drift_policy not in ALLOWED_DRIFT:
        raise HTTPException(400, "Invalid schema drift policy")
    if body.destination_mode not in ALLOWED_DEST:
        raise HTTPException(400, "Invalid destination mode")
    if _next_run(body.cadence) is None:
        raise HTTPException(400, "Invalid cron cadence")
    _, dest = await _validate_sync_connections(db, body.source_connection_id, body.dest_connection_id)
    task_config = _normalize_task_config(body)
    p = SyncProfile(
        name=body.name,
        source_connection_id=body.source_connection_id,
        dest_connection_id=body.dest_connection_id,
        source_dataset=body.source_dataset.strip(),
        source_table=body.source_table.strip(),
        target_schema=body.target_schema.strip(),
        target_table=body.target_table.strip(),
        task_config=task_config,
        mode=body.mode,
        cadence=body.cadence,
        schema_drift_policy=body.schema_drift_policy,
        destination_mode=body.destination_mode,
        created_by=user.id,
    )
    db.add(p)
    await db.flush()
    p.job_id = await create_or_update_managed_job(
        p,
        dest.config,
        load_strategy=sync_mode_to_load_strategy(body.mode),
        destination_mode=DestinationMode(body.destination_mode),
        is_active=True,
    )
    await db.commit()
    await db.refresh(p)
    profile, _ = await _load_profile_context(db, p)
    return profile


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(SyncProfile, profile_id)
    if not p:
        raise HTTPException(404, "Sync profile not found")
    profile, runs = await _load_profile_context(db, p)
    profile["recent_runs"] = [
        {
            "id": row.id,
            "status": row.status,
            "rows_synced": row.rows_synced,
            "bytes_synced": row.bytes_synced,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "error_message": row.error_message,
        }
        for row in runs
    ]
    return profile


@router.patch("/profiles/{profile_id}")
async def update_profile(profile_id: str, body: SyncProfileUpdate, _: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    p = await db.get(SyncProfile, profile_id)
    if not p:
        raise HTTPException(404, "Sync profile not found")

    updates = body.model_dump(exclude_unset=True)
    if "mode" in updates and updates["mode"] not in ALLOWED_MODES:
        raise HTTPException(400, "Invalid sync mode")
    if "schema_drift_policy" in updates and updates["schema_drift_policy"] not in ALLOWED_DRIFT:
        raise HTTPException(400, "Invalid schema drift policy")
    if "destination_mode" in updates and updates["destination_mode"] not in ALLOWED_DEST:
        raise HTTPException(400, "Invalid destination mode")
    if "cadence" in updates and _next_run(updates["cadence"]) is None:
        raise HTTPException(400, "Invalid cron cadence")

    src_id = updates.get("source_connection_id", p.source_connection_id)
    dst_id = updates.get("dest_connection_id", p.dest_connection_id)
    _, dest = await _validate_sync_connections(db, src_id, dst_id)

    for key, value in updates.items():
        setattr(p, key, value)
    if any(k in updates for k in ("primary_key_columns", "watermark_column", "delete_flag_column", "batch_size")):
        p.task_config = _normalize_task_config(body, p.task_config or {})
    elif not p.task_config:
        p.task_config = _normalize_task_config(body, {})
    p.updated_at = datetime.utcnow()

    p.job_id = await create_or_update_managed_job(
        p,
        dest.config,
        load_strategy=sync_mode_to_load_strategy(p.mode),
        destination_mode=DestinationMode(p.destination_mode),
        is_active=p.is_active,
    )
    await db.commit()
    await db.refresh(p)
    profile, _ = await _load_profile_context(db, p)
    return profile


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(profile_id: str, _: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    p = await db.get(SyncProfile, profile_id)
    if not p:
        raise HTTPException(404, "Sync profile not found")
    job_id = p.job_id
    if job_id:
        try:
            await delete_managed_job(job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    await db.delete(p)
    await db.commit()


@router.get("/profiles/{profile_id}/runs")
async def get_runs(profile_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(SyncProfile, profile_id):
        raise HTTPException(404, "Sync profile not found")
    r = await db.execute(select(SyncRun).where(SyncRun.profile_id == profile_id).order_by(SyncRun.created_at.desc()))
    return [{
        "id": row.id, "status": row.status,
        "rows_synced": row.rows_synced, "bytes_synced": row.bytes_synced,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in r.scalars()]


@router.post("/profiles/{profile_id}/run")
async def run_profile(
    profile_id: str,
    background_tasks: BackgroundTasks,
    _: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    p = await db.get(SyncProfile, profile_id)
    if not p:
        raise HTTPException(404, "Sync profile not found")
    if not p.job_id:
        raise HTTPException(409, "Sync profile is not bound to a managed migration job")
    sync_run_id = await create_running_sync_run(profile_id)
    p.updated_at = datetime.utcnow()
    await db.commit()
    background_tasks.add_task(_execute_profile_job, profile_id, p.job_id, sync_run_id)
    return {"success": True, "run_id": sync_run_id, "status": "RUNNING", "job_id": p.job_id}
