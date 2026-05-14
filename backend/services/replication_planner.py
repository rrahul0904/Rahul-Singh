from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ReplicationDestination, ReplicationJob, ReplicationJobTable, ReplicationPlan


SUPPORTED_LOAD_MODES = {
    "FULL_LOAD",
    "INCREMENTAL_WATERMARK",
    "APPEND_ONLY",
    "MERGE_UPSERT",
    "SOFT_DELETE_AWARE",
    "CDC_FUTURE",
}
SUPPORTED_WRITE_MODES = {"CREATE_OR_REPLACE", "INSERT_ONLY", "MERGE", "STAGE_AND_MERGE"}

WATERMARK_NAMES = ("updated_at", "modified_at", "last_modified", "last_updated", "created_at", "inserted_at", "event_time")
SOFT_DELETE_NAMES = ("is_deleted", "deleted", "deleted_at", "delete_flag", "is_active")


@dataclass(frozen=True)
class TableReplicationPlan:
    source_schema: str
    source_object: str
    target_database: str
    target_schema: str
    target_object: str
    object_type: str
    primary_key_columns: list[str]
    watermark_column: str | None
    load_mode: str
    write_mode: str
    estimated_rows: int
    estimated_bytes: int
    chunk_strategy: str
    sync_frequency: str
    soft_delete_column: str | None
    schema_drift_policy: str
    initial_load_required: bool
    incremental_supported: bool
    risk_level: str
    reasoning: str


def _col_name(column: dict[str, Any]) -> str:
    return str(column.get("name") or column.get("column_name") or column.get("field") or "").strip()


def _column_names(columns: list[dict[str, Any]]) -> list[str]:
    return [name for name in (_col_name(col) for col in columns or []) if name]


def _metadata_int(table: ReplicationJobTable, key: str) -> int:
    candidates: list[Any] = []
    for source in (getattr(table, "config", None), getattr(table, "metadata", None)):
        if isinstance(source, dict):
            candidates.append(source.get(key))
    for col in table.columns or []:
        if isinstance(col, dict) and key in col:
            candidates.append(col.get(key))
    for value in candidates:
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError):
            continue
    return 0


def _infer_primary_keys(table: ReplicationJobTable) -> list[str]:
    explicit = [str(v) for v in (table.primary_key_columns or []) if str(v).strip()]
    if explicit:
        return explicit
    marked = [
        _col_name(col)
        for col in table.columns or []
        if isinstance(col, dict) and (col.get("primary_key") or col.get("is_primary_key") or col.get("pk"))
    ]
    if marked:
        return [v for v in marked if v]
    names = _column_names(table.columns or [])
    lowered = {name.lower(): name for name in names}
    for candidate in ("id", f"{table.table_name}_id", f"{table.table_name.rstrip('s')}_id"):
        if candidate.lower() in lowered:
            return [lowered[candidate.lower()]]
    return []


def _infer_watermark(table: ReplicationJobTable) -> str | None:
    if table.watermark_column:
        return table.watermark_column
    lowered = {name.lower(): name for name in _column_names(table.columns or [])}
    for candidate in WATERMARK_NAMES:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _infer_soft_delete(table: ReplicationJobTable) -> str | None:
    lowered = {name.lower(): name for name in _column_names(table.columns or [])}
    for candidate in SOFT_DELETE_NAMES:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _target_database(destination: ReplicationDestination | None) -> str:
    return (destination.database if destination else "") or "SNOWFLAKE_TARGET"


def _choose_load_write_modes(sync_mode: str, primary_keys: list[str], watermark: str | None, soft_delete: str | None) -> tuple[str, str, bool]:
    mode = (sync_mode or "").lower()
    if mode in {"cdc", "change_data_capture"}:
        return "CDC_FUTURE", "STAGE_AND_MERGE", bool(primary_keys)
    if mode in {"full", "full_load", "full_refresh", "replace"}:
        return "FULL_LOAD", "CREATE_OR_REPLACE", False
    if soft_delete and primary_keys and watermark:
        return "SOFT_DELETE_AWARE", "STAGE_AND_MERGE", True
    if primary_keys and watermark:
        return "MERGE_UPSERT", "MERGE", True
    if watermark:
        return "INCREMENTAL_WATERMARK", "INSERT_ONLY", True
    if primary_keys and mode in {"append", "append_only"}:
        return "APPEND_ONLY", "INSERT_ONLY", True
    return "FULL_LOAD", "CREATE_OR_REPLACE", False


def _chunk_strategy(load_mode: str, estimated_rows: int, estimated_bytes: int, primary_keys: list[str], watermark: str | None) -> str:
    if estimated_rows <= 0 and estimated_bytes <= 0:
        return "SINGLE_TABLE_SCAN"
    if watermark and load_mode in {"INCREMENTAL_WATERMARK", "MERGE_UPSERT", "SOFT_DELETE_AWARE"}:
        return "WATERMARK_RANGE_CHUNKS"
    if primary_keys and (estimated_rows > 5_000_000 or estimated_bytes > 1_000_000_000):
        return "PRIMARY_KEY_RANGE_CHUNKS"
    if estimated_rows > 1_000_000 or estimated_bytes > 250_000_000:
        return "SIZE_BASED_FILE_CHUNKS"
    return "SINGLE_TABLE_SCAN"


def _risk_level(load_mode: str, incremental_supported: bool, columns: list[dict[str, Any]], estimated_rows: int, estimated_bytes: int) -> str:
    if load_mode == "CDC_FUTURE":
        return "HIGH"
    if not columns:
        return "MEDIUM"
    if load_mode == "FULL_LOAD" and (estimated_rows > 10_000_000 or estimated_bytes > 5_000_000_000):
        return "HIGH"
    if not incremental_supported and load_mode != "FULL_LOAD":
        return "HIGH"
    if incremental_supported:
        return "LOW"
    return "MEDIUM"


def _reasoning(plan: TableReplicationPlan, sync_mode: str, has_columns: bool) -> str:
    parts = [f"Requested sync mode is {sync_mode or 'unspecified'}; selected load mode is {plan.load_mode}."]
    if plan.primary_key_columns:
        parts.append(f"Primary keys available: {', '.join(plan.primary_key_columns)}.")
    else:
        parts.append("No primary key metadata is available.")
    if plan.watermark_column:
        parts.append(f"Watermark column {plan.watermark_column} supports incremental planning.")
    else:
        parts.append("No watermark column was found.")
    if plan.soft_delete_column:
        parts.append(f"Soft delete column {plan.soft_delete_column} is included in the strategy.")
    if not has_columns:
        parts.append("Column metadata is missing, so the plan remains conservative.")
    return " ".join(parts)


def plan_table(table: ReplicationJobTable, job: ReplicationJob, destination: ReplicationDestination | None = None) -> TableReplicationPlan:
    primary_keys = _infer_primary_keys(table)
    watermark = _infer_watermark(table)
    soft_delete = _infer_soft_delete(table)
    estimated_rows = _metadata_int(table, "estimated_rows") or _metadata_int(table, "row_count")
    estimated_bytes = _metadata_int(table, "estimated_bytes") or _metadata_int(table, "bytes")
    load_mode, write_mode, incremental_supported = _choose_load_write_modes(
        table.sync_mode or job.sync_mode,
        primary_keys,
        watermark,
        soft_delete,
    )
    plan = TableReplicationPlan(
        source_schema=table.schema_name,
        source_object=table.table_name,
        target_database=_target_database(destination),
        target_schema=table.target_schema or table.schema_name,
        target_object=table.target_table or table.table_name,
        object_type="TABLE",
        primary_key_columns=primary_keys,
        watermark_column=watermark,
        load_mode=load_mode,
        write_mode=write_mode,
        estimated_rows=estimated_rows,
        estimated_bytes=estimated_bytes,
        chunk_strategy=_chunk_strategy(load_mode, estimated_rows, estimated_bytes, primary_keys, watermark),
        sync_frequency=job.schedule or "manual",
        soft_delete_column=soft_delete,
        schema_drift_policy="ADDITIVE_ONLY_REVIEW",
        initial_load_required=not bool(table.last_sync_at),
        incremental_supported=incremental_supported,
        risk_level="MEDIUM",
        reasoning="",
    )
    risk = _risk_level(load_mode, incremental_supported, table.columns or [], estimated_rows, estimated_bytes)
    plan = TableReplicationPlan(**{**asdict(plan), "risk_level": risk})
    return TableReplicationPlan(**{**asdict(plan), "reasoning": _reasoning(plan, table.sync_mode or job.sync_mode, bool(table.columns))})


def plan_to_dict(row: ReplicationPlan | TableReplicationPlan) -> dict[str, Any]:
    if isinstance(row, TableReplicationPlan):
        return asdict(row)
    return {
        "id": row.id,
        "job_id": row.job_id,
        "job_table_id": row.job_table_id,
        "source_schema": row.source_schema,
        "source_object": row.source_object,
        "target_database": row.target_database,
        "target_schema": row.target_schema,
        "target_object": row.target_object,
        "object_type": row.object_type,
        "primary_key_columns": row.primary_key_columns or [],
        "watermark_column": row.watermark_column,
        "load_mode": row.load_mode,
        "write_mode": row.write_mode,
        "estimated_rows": row.estimated_rows or 0,
        "estimated_bytes": row.estimated_bytes or 0,
        "chunk_strategy": row.chunk_strategy,
        "sync_frequency": row.sync_frequency,
        "soft_delete_column": row.soft_delete_column,
        "schema_drift_policy": row.schema_drift_policy,
        "initial_load_required": bool(row.initial_load_required),
        "incremental_supported": bool(row.incremental_supported),
        "risk_level": row.risk_level,
        "reasoning": row.reasoning,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def create_or_update_plan(db: AsyncSession, job_id: str) -> dict[str, Any]:
    job = await db.get(ReplicationJob, job_id)
    if not job:
        raise ValueError("Replication job not found")
    destination = None
    if job.destination_id:
        destination = await db.get(ReplicationDestination, job.destination_id)
    if not destination:
        destination = (
            await db.execute(select(ReplicationDestination).where(ReplicationDestination.connection_id == job.destination_connection_id))
        ).scalars().first()
    tables = list(
        (
            await db.execute(
                select(ReplicationJobTable)
                .where(ReplicationJobTable.job_id == job.id, ReplicationJobTable.selected == True)
                .order_by(ReplicationJobTable.schema_name, ReplicationJobTable.table_name)
            )
        ).scalars().all()
    )
    existing = {
        row.job_table_id: row
        for row in (
            await db.execute(select(ReplicationPlan).where(ReplicationPlan.job_id == job.id))
        ).scalars().all()
    }
    output: list[ReplicationPlan] = []
    for table in tables:
        planned = plan_table(table, job, destination)
        row = existing.get(table.id)
        if not row:
            row = ReplicationPlan(job_id=job.id, job_table_id=table.id)
            db.add(row)
        for key, value in asdict(planned).items():
            setattr(row, key, value)
        row.updated_at = datetime.utcnow()
        output.append(row)
    await db.commit()
    return {
        "job_id": job.id,
        "planned_tables": len(output),
        "plans": [plan_to_dict(row) for row in output],
        "supported_load_modes": sorted(SUPPORTED_LOAD_MODES),
        "supported_write_modes": sorted(SUPPORTED_WRITE_MODES),
    }


async def get_plan(db: AsyncSession, job_id: str) -> dict[str, Any]:
    rows = list(
        (
            await db.execute(
                select(ReplicationPlan)
                .where(ReplicationPlan.job_id == job_id)
                .order_by(ReplicationPlan.source_schema, ReplicationPlan.source_object)
            )
        ).scalars().all()
    )
    return {"job_id": job_id, "planned_tables": len(rows), "plans": [plan_to_dict(row) for row in rows]}
