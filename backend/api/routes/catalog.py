from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.database import get_db
from models import (
    Connection,
    Job,
    JobTask,
    MigrationRunEvent,
    ReplicationError,
    ReplicationEvent,
    ReplicationJob,
    ReplicationJobTable,
    ReplicationPlan,
    ReplicationRun,
    ReplicationTableRun,
    User,
)

router = APIRouter()


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _contains(row: dict[str, Any], search: str) -> bool:
    hay = " ".join(str(v) for v in row.values() if v is not None).lower()
    return search.lower() in hay


async def _catalog_rows(db: AsyncSession) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    jobs = {j.id: j for j in (await db.execute(select(Job))).scalars().all()}
    connections = {c.id: c for c in (await db.execute(select(Connection))).scalars().all()}
    tasks = list((await db.execute(select(JobTask))).scalars().all())
    for task in tasks:
        job = jobs.get(task.job_id)
        src = connections.get(job.source_connection_id) if job else None
        dst = connections.get(job.dest_connection_id) if job else None
        cfg = task.config or {}
        rows.append({
            "id": f"migration:{task.id}",
            "table_id": f"migration:{task.id}",
            "surface": "migration",
            "source_connection_id": src.id if src else None,
            "source_connection_name": src.name if src else None,
            "source_connection_type": src.type.value if src else None,
            "target_connection_id": dst.id if dst else None,
            "database": cfg.get("database") or cfg.get("source_database") or "",
            "schema": task.source_dataset,
            "table": task.source_table,
            "object_type": cfg.get("object_type", "TABLE"),
            "target_schema": task.target_schema,
            "target_table": task.target_table,
            "column_count": len(cfg.get("columns") or []),
            "estimated_rows": task.rows_exported or cfg.get("estimated_rows") or 0,
            "estimated_bytes": int(task.bytes_exported or cfg.get("estimated_bytes") or 0),
            "latest_migration_status": task.status.value,
            "latest_replication_status": None,
            "latest_error": task.error_message,
            "last_sync_time": _iso(task.ended_at or task.started_at),
            "drift_status": cfg.get("drift_status", "NOT_CHECKED"),
            "target_mapping_status": "MAPPED" if task.target_table else "UNMAPPED",
            "columns": cfg.get("columns") or [],
        })

    rep_jobs = {j.id: j for j in (await db.execute(select(ReplicationJob))).scalars().all()}
    rep_tables = list((await db.execute(select(ReplicationJobTable))).scalars().all())
    plans = {p.job_table_id: p for p in (await db.execute(select(ReplicationPlan))).scalars().all()}
    for table in rep_tables:
        job = rep_jobs.get(table.job_id)
        plan = plans.get(table.id)
        rows.append({
            "id": f"replication:{table.id}",
            "table_id": f"replication:{table.id}",
            "surface": "replication",
            "source_connection_id": job.source_connection_id if job else None,
            "source_connection_name": None,
            "source_connection_type": None,
            "target_connection_id": job.destination_connection_id if job else None,
            "database": "",
            "schema": table.schema_name,
            "table": table.table_name,
            "object_type": plan.object_type if plan else "TABLE",
            "target_schema": table.target_schema or (plan.target_schema if plan else ""),
            "target_table": table.target_table or (plan.target_object if plan else ""),
            "column_count": len(table.columns or []),
            "estimated_rows": plan.estimated_rows if plan else 0,
            "estimated_bytes": plan.estimated_bytes if plan else 0,
            "latest_migration_status": None,
            "latest_replication_status": table.status,
            "latest_error": table.latest_error or (job.latest_error if job else ""),
            "last_sync_time": _iso(table.last_sync_at),
            "drift_status": (plan.schema_drift_policy if plan else "NOT_PLANNED"),
            "target_mapping_status": "MAPPED" if (table.target_schema and table.target_table) else "UNMAPPED",
            "load_mode": plan.load_mode if plan else table.sync_mode,
            "write_mode": plan.write_mode if plan else "",
            "primary_key_columns": table.primary_key_columns or [],
            "watermark_column": table.watermark_column,
            "columns": table.columns or [],
        })
    return rows


@router.get("/tables")
async def list_catalog_tables(
    search: str = "",
    connection_id: str = "",
    database: str = "",
    schema: str = "",
    status: str = "",
    object_type: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    sort: str = "schema",
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await _catalog_rows(db)
    if search:
        rows = [row for row in rows if _contains(row, search)]
    if connection_id:
        rows = [row for row in rows if row.get("source_connection_id") == connection_id or row.get("target_connection_id") == connection_id]
    if database:
        rows = [row for row in rows if row.get("database") == database]
    if schema:
        rows = [row for row in rows if row.get("schema") == schema]
    if object_type:
        rows = [row for row in rows if str(row.get("object_type", "")).upper() == object_type.upper()]
    if status:
        rows = [
            row for row in rows
            if str(row.get("latest_migration_status") or row.get("latest_replication_status") or "").upper() == status.upper()
        ]
    reverse = sort.startswith("-")
    key = sort[1:] if reverse else sort
    rows.sort(key=lambda row: str(row.get(key) or ""), reverse=reverse)
    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size}


@router.get("/tables/summary")
async def catalog_summary(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await _catalog_rows(db)
    def status(row):
        return str(row.get("latest_migration_status") or row.get("latest_replication_status") or "").upper()
    return {
        "total_tables": len(rows),
        "ready": sum(1 for row in rows if status(row) in {"PENDING", "READY", "PLANNED", "NOT_STARTED"}),
        "running": sum(1 for row in rows if status(row) in {"RUNNING", "QUEUED"}),
        "succeeded": sum(1 for row in rows if status(row) in {"SUCCEEDED", "SUCCESS"}),
        "failed": sum(1 for row in rows if status(row) == "FAILED" or row.get("latest_error")),
        "drift_detected": sum(1 for row in rows if str(row.get("drift_status", "")).upper() in {"DRIFT_DETECTED", "BLOCKING", "WARNING"}),
        "unmapped": sum(1 for row in rows if row.get("target_mapping_status") != "MAPPED"),
    }


@router.get("/tables/{table_id}")
async def catalog_table_detail(table_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await _catalog_rows(db)
    row = next((item for item in rows if item["table_id"] == table_id), None)
    if not row:
        raise HTTPException(404, "Catalog table not found")
    return row


@router.get("/tables/{table_id}/columns")
async def catalog_table_columns(table_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await catalog_table_detail(table_id, _user, db)
    return {"columns": row.get("columns") or []}


@router.get("/tables/{table_id}/runs")
async def catalog_table_runs(table_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    surface, _, raw_id = table_id.partition(":")
    if surface == "replication":
        runs = list((await db.execute(select(ReplicationTableRun).where(ReplicationTableRun.job_table_id == raw_id).order_by(ReplicationTableRun.created_at.desc()).limit(50))).scalars().all())
        return {"runs": [{
            "id": row.id,
            "run_id": row.run_id,
            "job_id": row.job_id,
            "table_id": row.job_table_id,
            "status": row.status,
            "stage": "TABLE_RUN",
            "latest_error": row.latest_error,
            "created_at": _iso(row.created_at),
            "started_at": _iso(row.started_at),
            "ended_at": _iso(row.ended_at),
        } for row in runs]}
    return {"runs": []}


@router.get("/tables/{table_id}/lineage")
async def catalog_table_lineage(table_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await catalog_table_detail(table_id, _user, db)
    status = row.get("latest_replication_status") or row.get("latest_migration_status") or "UNKNOWN"
    failed = str(status).upper() == "FAILED" or bool(row.get("latest_error"))
    return {
        "nodes": [
            {"id": f"source:{row['schema']}.{row['table']}", "label": f"{row['schema']}.{row['table']}", "type": "source", "status": "DISCOVERED"},
            {"id": f"target:{row.get('target_schema')}.{row.get('target_table')}", "label": f"{row.get('target_schema')}.{row.get('target_table')}", "type": "target", "status": row.get("target_mapping_status")},
        ],
        "edges": [
            {
                "source": f"source:{row['schema']}.{row['table']}",
                "target": f"target:{row.get('target_schema')}.{row.get('target_table')}",
                "status": "FAILED" if failed else status,
                "stage": "replication" if row["surface"] == "replication" else "migration",
                "message": row.get("latest_error") or "Catalog metadata edge",
                "recommended_action": "Open logs/events and retry after blocker is resolved." if failed else "Monitor next run.",
                "linked_table_id": table_id,
                "last_updated": row.get("last_sync_time"),
            }
        ],
        "timeline": [
            {"event": "discovered", "status": "COMPLETE", "timestamp": row.get("last_sync_time")},
            {"event": "mapped", "status": row.get("target_mapping_status"), "timestamp": row.get("last_sync_time")},
            {"event": "target checked", "status": "NOT_CHECKED", "timestamp": None},
            {"event": "failed" if failed else "latest status", "status": "FAILED" if failed else status, "timestamp": row.get("last_sync_time")},
        ],
    }
