from datetime import datetime
from typing import Optional

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_editor
from core.database import get_db
from models import SyncProfile, SyncRun, Connection, User

router = APIRouter()


class SyncProfileCreate(BaseModel):
    name: str = Field(min_length=2)
    source_connection_id: str
    dest_connection_id: str
    mode: str = "incremental"
    cadence: str = "0 2 * * *"
    schema_drift_policy: str = "warn"
    destination_mode: str = "internal"


class SyncProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2)
    source_connection_id: Optional[str] = None
    dest_connection_id: Optional[str] = None
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

    src = await db.get(Connection, body.source_connection_id)
    dest = await db.get(Connection, body.dest_connection_id)
    if not src or not dest:
        raise HTTPException(400, "Source and destination connections must exist")
    p = SyncProfile(**body.model_dump(), created_by=user.id)
    db.add(p)
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
    if "source_connection_id" in updates and not await db.get(Connection, updates["source_connection_id"]):
        raise HTTPException(400, "Source connection not found")
    if "dest_connection_id" in updates and not await db.get(Connection, updates["dest_connection_id"]):
        raise HTTPException(400, "Destination connection not found")

    for key, value in updates.items():
        setattr(p, key, value)
    p.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(p)
    profile, _ = await _load_profile_context(db, p)
    return profile


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(profile_id: str, _: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    p = await db.get(SyncProfile, profile_id)
    if not p:
        raise HTTPException(404, "Sync profile not found")
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
async def run_profile(profile_id: str, _: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    p = await db.get(SyncProfile, profile_id)
    if not p:
        raise HTTPException(404, "Sync profile not found")

    now = datetime.utcnow()
    base_rows = {"full_refresh": 240000, "incremental": 12500, "cdc": 3800}.get(p.mode, 12500)
    base_bytes = {"full_refresh": 734003200, "incremental": 52428800, "cdc": 9437184}.get(p.mode, 52428800)
    status = "SUCCEEDED"
    error_message = ""
    if p.schema_drift_policy == "block" and p.mode == "cdc":
        status = "FAILED"
        error_message = "Blocked by schema drift policy — destination requires manual review before continuing."
    run = SyncRun(
        profile_id=profile_id,
        status=status,
        rows_synced=0 if status == "FAILED" else base_rows,
        bytes_synced=0 if status == "FAILED" else base_bytes,
        started_at=now,
        ended_at=now,
        error_message=error_message,
    )
    db.add(run)
    p.updated_at = now
    await db.commit()
    return {"success": status == "SUCCEEDED", "run_id": run.id, "status": status, "error_message": error_message}
