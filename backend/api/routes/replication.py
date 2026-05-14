import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_editor, require_operator
from core.database import get_db
from core.security import get_cipher, mask_secret
from models import (
    Connection,
    ConnectorHealthCheck,
    ReplicationConnection,
    ReplicationDestination,
    ReplicationError,
    ReplicationEvent,
    ReplicationJob,
    ReplicationJobTable,
    ReplicationPlan,
    ReplicationRun,
    ReplicationSource,
    ReplicationTableRun,
    ReplicationWatermark,
    SnowflakePermissionCheck,
    User,
)
from services.replication_planner import create_or_update_plan, get_plan
from services.snowflake_connection import normalize_snowflake_config, snowflake_execution_readiness
from services.snowflake_readiness import check_snowflake_readiness_sync, check_snowflake_readiness_with_connector, not_configured_readiness
from services.snowflake_session_manager import SNOWFLAKE_MFA_EXPIRED_MESSAGE, snowflake_session_manager

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=4)

SUPPORTED_DISCOVERY = {"postgres", "mysql", "oracle", "redshift", "sqlserver", "snowflake"}
SUPPORTED_HEALTH = SUPPORTED_DISCOVERY | {"bigquery", "salesforce", "s3", "adls", "azureblob", "gcs", "sftp", "rest", "fivetran", "stitch"}
SECRET_KEYS = {"password", "token", "secret", "client_secret", "private_key", "passcode", "mfa_passcode"}


class ReplicationConnectionCreate(BaseModel):
    name: str = Field(min_length=1)
    connector_type: str
    role: str = "both"
    description: str = ""
    connection_id: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)


class SourceDiscoverRequest(BaseModel):
    connection_id: str
    schema_limit: int = 5
    table_limit: int = 50
    include_columns: bool = True


class ReplicationJobTablePayload(BaseModel):
    schema_name: str
    table_name: str
    target_schema: str = ""
    target_table: str = ""
    selected: bool = True
    sync_mode: Optional[str] = None
    columns: list[dict[str, Any]] = Field(default_factory=list)
    primary_key_columns: list[str] = Field(default_factory=list)
    watermark_column: Optional[str] = None


class ReplicationJobCreate(BaseModel):
    name: str = Field(min_length=1)
    source_connection_id: str
    destination_connection_id: str
    source_id: Optional[str] = None
    destination_id: Optional[str] = None
    sync_mode: str = "incremental"
    schedule: Optional[str] = None
    tables: list[ReplicationJobTablePayload] = Field(default_factory=list)


class JobTablesUpdate(BaseModel):
    tables: list[ReplicationJobTablePayload] = Field(default_factory=list)


class SnowflakePermissionRequest(BaseModel):
    connection_id: Optional[str] = None
    database: str = ""
    schema_name: str = ""
    warehouse: str = ""


class ReplicationStartRequest(BaseModel):
    execute: bool = False
    provider: str = "auto"
    wait_for_completion: bool = False


def _safe_text(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    for key in SECRET_KEYS:
        text = text.replace(key, "[redacted]")
    return text[:limit]


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _masked(values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in (values or {}).items():
        if value in (None, ""):
            out[key] = "[empty]"
        elif any(secret in key.lower() for secret in SECRET_KEYS):
            out[key] = "[set]"
        elif isinstance(value, str):
            out[key] = mask_secret(value, visible=4) if len(value) > 8 else "[set]"
        else:
            out[key] = "[set]"
    return out


def _has_credentials(connector_type: str, cfg: dict[str, Any]) -> bool:
    if not cfg:
        return False
    if connector_type in {"postgres", "mysql", "oracle", "redshift", "sqlserver", "snowflake"}:
        return bool((cfg.get("user") or cfg.get("username")) and (cfg.get("password") or cfg.get("private_key")))
    if connector_type == "bigquery":
        return bool(cfg.get("credentials_json") or cfg.get("service_account_json") or cfg.get("project_id"))
    if connector_type in {"s3", "adls", "azureblob", "gcs", "sftp", "rest"}:
        return bool(cfg)
    return bool(cfg)


def _connection_dict(row: ReplicationConnection, health: Optional[ConnectorHealthCheck] = None) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "connector_type": row.connector_type,
        "role": row.role,
        "description": row.description,
        "connection_id": row.connection_id,
        "config": row.config or {},
        "credentials": _masked(get_cipher().decrypt_dict(row.credentials) if row.credentials else {}),
        "status": row.status,
        "latest_error": row.latest_error,
        "last_tested_at": _iso(row.last_tested_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "health": _health_dict(health) if health else None,
    }


def _source_dict(row: ReplicationSource) -> dict:
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "connector_type": row.connector_type,
        "name": row.name,
        "discovery_status": row.discovery_status,
        "discovery_reason": row.discovery_reason,
        "schemas": row.schemas or [],
        "discovered_at": _iso(row.discovered_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _destination_dict(row: ReplicationDestination) -> dict:
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "connector_type": row.connector_type,
        "name": row.name,
        "database": row.database,
        "schema": row.schema,
        "warehouse": row.warehouse,
        "readiness_status": row.readiness_status,
        "latest_error": row.latest_error,
        "checked_at": _iso(row.checked_at),
    }


def _job_dict(
    row: ReplicationJob,
    source: Optional[ReplicationConnection] = None,
    dest: Optional[ReplicationConnection] = None,
    latest_run: Optional[ReplicationRun] = None,
    table_count: int = 0,
) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "source_connection_id": row.source_connection_id,
        "destination_connection_id": row.destination_connection_id,
        "source_id": row.source_id,
        "destination_id": row.destination_id,
        "source_connection_name": source.name if source else None,
        "destination_connection_name": dest.name if dest else None,
        "source_connector_type": source.connector_type if source else None,
        "destination_connector_type": dest.connector_type if dest else None,
        "sync_mode": row.sync_mode,
        "schedule": row.schedule,
        "status": row.status,
        "latest_error": row.latest_error,
        "last_sync_at": _iso(row.last_sync_at),
        "table_count": table_count,
        "latest_run": _run_dict(latest_run) if latest_run else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _table_dict(row: ReplicationJobTable) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "schema_name": row.schema_name,
        "table_name": row.table_name,
        "target_schema": row.target_schema,
        "target_table": row.target_table,
        "selected": row.selected,
        "sync_mode": row.sync_mode,
        "columns": row.columns or [],
        "primary_key_columns": row.primary_key_columns or [],
        "watermark_column": row.watermark_column,
        "status": row.status,
        "latest_error": row.latest_error,
        "last_sync_at": _iso(row.last_sync_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _plan_summary_dict(row: ReplicationPlan) -> dict:
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
    }


def _run_dict(row: ReplicationRun) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "status": row.status,
        "trigger": row.trigger,
        "attempt_number": row.attempt_number,
        "planned_tables": row.planned_tables,
        "started_at": _iso(row.started_at),
        "ended_at": _iso(row.ended_at),
        "latest_error": row.latest_error,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _table_run_dict(row: ReplicationTableRun) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "job_id": row.job_id,
        "job_table_id": row.job_table_id,
        "schema_name": row.schema_name,
        "table_name": row.table_name,
        "status": row.status,
        "latest_error": row.latest_error,
        "started_at": _iso(row.started_at),
        "ended_at": _iso(row.ended_at),
        "created_at": _iso(row.created_at),
    }


def _event_dict(row: ReplicationEvent) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "run_id": row.run_id,
        "level": row.level,
        "event_type": row.event_type,
        "message": row.message,
        "event_json": row.event_json or {},
        "created_at": _iso(row.created_at),
    }


def _error_dict(row: ReplicationError) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "run_id": row.run_id,
        "table_run_id": row.table_run_id,
        "connection_id": row.connection_id,
        "category": row.category,
        "message": row.message,
        "safe_error_message": row.safe_detail or row.message,
        "retryable": row.category in {"MFA_SESSION", "network", "control_plane"},
        "recommended_action": "Unlock Snowflake and retry." if row.category == "MFA_SESSION" else "Review the event log and retry after the blocker is resolved.",
        "created_at": _iso(row.created_at),
    }


def _health_dict(row: ConnectorHealthCheck) -> dict:
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "status": row.status,
        "checked_at": _iso(row.checked_at),
        "latency_ms": row.latency_ms,
        "message": row.message,
        "safe_error": row.safe_error,
        "details": row.details or {},
    }


async def _replication_cfg(db: AsyncSession, row: ReplicationConnection) -> dict[str, Any]:
    cipher = get_cipher()
    cfg = dict(row.config or {})
    if row.credentials:
        cfg.update(cipher.decrypt_dict(row.credentials))
    if row.connection_id:
        base = await db.get(Connection, row.connection_id)
        if base:
            cfg = {**(base.config or {}), **(cipher.decrypt_dict(base.credentials) if base.credentials else {}), **cfg}
    if row.connector_type == "snowflake":
        cfg = normalize_snowflake_config(cfg)
    return cfg


def _connector_class(connector_type: str):
    if connector_type == "postgres":
        from connectors.db_connectors import PostgreSQLConnector
        return PostgreSQLConnector
    if connector_type == "mysql":
        from connectors.db_connectors import MySQLConnector
        return MySQLConnector
    if connector_type == "oracle":
        from connectors.db_connectors import OracleConnector
        return OracleConnector
    if connector_type == "redshift":
        from connectors.redshift_connector import RedshiftConnector
        return RedshiftConnector
    if connector_type == "sqlserver":
        from connectors.sqlserver_connector import SQLServerConnector
        return SQLServerConnector
    if connector_type == "snowflake":
        from connectors.snowflake_connector import SnowflakeConnector
        return SnowflakeConnector
    if connector_type == "bigquery":
        from connectors.bigquery_connector import BigQueryConnector
        return BigQueryConnector
    if connector_type == "salesforce":
        from connectors.salesforce_connector import SalesforceConnector
        return SalesforceConnector
    if connector_type == "s3":
        from connectors.s3_connector import S3Connector
        return S3Connector
    if connector_type in {"adls", "azureblob"}:
        from connectors.azure_connector import AzureConnector
        return AzureConnector
    if connector_type == "gcs":
        from connectors.storage_connectors import GCSConnector
        return GCSConnector
    if connector_type == "sftp":
        from connectors.storage_connectors import SFTPConnector
        return SFTPConnector
    if connector_type == "rest":
        from connectors.storage_connectors import RESTConnector
        return RESTConnector
    return None


async def _record_event(
    db: AsyncSession,
    *,
    event_type: str,
    message: str,
    job_id: Optional[str] = None,
    run_id: Optional[str] = None,
    level: str = "INFO",
    event_json: Optional[dict[str, Any]] = None,
) -> None:
    db.add(ReplicationEvent(
        job_id=job_id,
        run_id=run_id,
        level=level,
        event_type=event_type,
        message=message,
        event_json=event_json or {},
    ))


async def _record_error(
    db: AsyncSession,
    *,
    message: str,
    job_id: Optional[str] = None,
    run_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    category: str = "control_plane",
    safe_detail: str = "",
) -> None:
    db.add(ReplicationError(
        job_id=job_id,
        run_id=run_id,
        connection_id=connection_id,
        category=category,
        message=_safe_text(message),
        safe_detail=_safe_text(safe_detail),
    ))


def _discover_sync(connector_type: str, cfg: dict[str, Any], schema_limit: int, table_limit: int, include_columns: bool) -> dict:
    klass = _connector_class(connector_type)
    if not klass or connector_type not in SUPPORTED_DISCOVERY:
        return {"status": "NOT_CHECKED", "reason": f"Discovery is not implemented for {connector_type}.", "schemas": []}
    schemas_out = []
    with klass(cfg) as connector:
        schemas = connector.list_schemas()[: max(1, min(schema_limit, 20))]
        remaining = max(1, min(table_limit, 200))
        for schema_name in schemas:
            tables_out = []
            for table in connector.list_tables(schema_name):
                if remaining <= 0:
                    break
                table_name = table.get("table") or table.get("name") or table.get("table_name")
                columns = []
                if include_columns and hasattr(connector, "get_table_schema") and table_name:
                    columns = connector.get_table_schema(schema_name, table_name)[:200]
                tables_out.append({
                    "schema_name": schema_name,
                    "table_name": table_name,
                    "type": table.get("type") or table.get("table_type") or "TABLE",
                    "columns": columns,
                })
                remaining -= 1
            schemas_out.append({"name": schema_name, "tables": tables_out})
            if remaining <= 0:
                break
    return {"status": "PASS", "reason": "Discovery completed with lightweight schema/table metadata.", "schemas": schemas_out}


def _test_sync(connector_type: str, cfg: dict[str, Any]) -> dict:
    if connector_type == "fivetran":
        import httpx
        from services.replication_execution import _basic_auth_header

        api_key = cfg.get("api_key") or cfg.get("key")
        api_secret = cfg.get("api_secret") or cfg.get("secret")
        connection_id = cfg.get("fivetran_connection_id") or cfg.get("external_connection_id")
        if not api_key or not api_secret or not connection_id:
            return {"status": "NOT_CONFIGURED", "message": "Fivetran requires api_key, api_secret, and fivetran_connection_id.", "safe_error": ""}
        response = httpx.get(
            f"{(cfg.get('base_url') or 'https://api.fivetran.com/v1').rstrip('/')}/connections/{connection_id}",
            headers={"Authorization": _basic_auth_header(api_key, api_secret), "Accept": "application/json;version=2"},
            timeout=30,
        )
        if response.status_code >= 400:
            return {"status": "FAIL", "message": "Fivetran connection status check failed.", "safe_error": _safe_text(response.text), "details": {}}
        data = response.json().get("data") or response.json()
        status = data.get("status") or {}
        setup_state = status.get("setup_state")
        return {
            "status": "PASS" if setup_state == "connected" else "WARNING",
            "message": f"Fivetran setup state: {setup_state or 'unknown'}.",
            "safe_error": "",
            "details": {"sync_state": status.get("sync_state"), "update_state": status.get("update_state")},
        }
    if connector_type == "stitch":
        import httpx

        token = cfg.get("access_token") or cfg.get("token")
        if not token:
            return {"status": "NOT_CONFIGURED", "message": "Stitch Import API requires access_token.", "safe_error": ""}
        response = httpx.get(
            f"{(cfg.get('base_url') or 'https://api.stitchdata.com').rstrip('/')}/v2/import/status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code >= 400:
            return {"status": "FAIL", "message": "Stitch Import API status check failed.", "safe_error": _safe_text(response.text), "details": {}}
        return {"status": "PASS", "message": "Stitch Import API status endpoint responded.", "safe_error": "", "details": response.json()}
    klass = _connector_class(connector_type)
    if not klass or connector_type not in SUPPORTED_HEALTH:
        return {"status": "WARNING", "message": f"Health check is not implemented for {connector_type}.", "safe_error": ""}
    with klass(cfg) as connector:
        result = connector.test_connection()
    if result.get("success"):
        return {"status": "PASS", "message": "Connection test passed.", "safe_error": "", "details": result}
    return {"status": "FAIL", "message": "Connection test failed.", "safe_error": _safe_text(result.get("error")), "details": {}}


@router.get("/overview")
async def overview(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    jobs = list((await db.execute(select(ReplicationJob))).scalars().all())
    runs = list((await db.execute(select(ReplicationRun))).scalars().all())
    table_count = await db.scalar(select(func.count(ReplicationJobTable.id))) or 0
    plan_count = await db.scalar(select(func.count(ReplicationPlan.id))) or 0
    connections = await db.scalar(select(func.count(ReplicationConnection.id))) or 0
    health_rows = list((await db.execute(select(ConnectorHealthCheck))).scalars().all())
    latest_run = max(runs, key=lambda r: r.created_at) if runs else None
    latest_error = (
        await db.execute(select(ReplicationError).order_by(ReplicationError.created_at.desc()).limit(1))
    ).scalars().first()
    return {
        "connection_count": connections,
        "job_count": len(jobs),
        "run_count": len(runs),
        "selected_table_count": table_count,
        "planned_table_count": plan_count,
        "jobs_by_status": {status: sum(1 for j in jobs if j.status == status) for status in sorted({j.status for j in jobs})},
        "runs_by_status": {status: sum(1 for r in runs if r.status == status) for status in sorted({r.status for r in runs})},
        "health_by_status": {status: sum(1 for h in health_rows if h.status == status) for status in sorted({h.status for h in health_rows})},
        "latest_run": _run_dict(latest_run) if latest_run else None,
        "latest_error": _safe_text(latest_error.message) if latest_error else "",
    }


@router.get("/connections")
async def list_connections(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = list((await db.execute(select(ReplicationConnection).order_by(ReplicationConnection.created_at.desc()))).scalars().all())
    health_rows = list((await db.execute(select(ConnectorHealthCheck).order_by(ConnectorHealthCheck.checked_at.desc()))).scalars().all())
    latest = {}
    for health in health_rows:
        latest.setdefault(health.connection_id, health)
    return [_connection_dict(row, latest.get(row.id)) for row in rows]


@router.post("/connections", status_code=201)
async def create_connection(body: ReplicationConnectionCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    if body.role not in {"source", "destination", "both"}:
        raise HTTPException(400, "role must be source, destination, or both")
    if body.connection_id and not await db.get(Connection, body.connection_id):
        raise HTTPException(400, "Linked platform connection not found")
    encrypted = get_cipher().encrypt_dict(body.credentials or {})
    row = ReplicationConnection(
        name=body.name.strip(),
        connector_type=body.connector_type.strip().lower(),
        role=body.role,
        description=body.description or "",
        connection_id=body.connection_id,
        config=body.config or {},
        credentials=encrypted,
        status="NOT_CONFIGURED",
        created_by_id=user.id,
    )
    db.add(row)
    await db.flush()
    if row.role in {"source", "both"}:
        db.add(ReplicationSource(connection_id=row.id, connector_type=row.connector_type, name=row.name))
    if row.role in {"destination", "both"} or row.connector_type == "snowflake":
        cfg = normalize_snowflake_config(row.config or {})
        db.add(ReplicationDestination(
            connection_id=row.id,
            connector_type=row.connector_type,
            name=row.name,
            database=cfg.get("database") or "",
            schema=cfg.get("schema") or "",
            warehouse=cfg.get("warehouse") or "",
        ))
    await db.commit()
    await db.refresh(row)
    return _connection_dict(row)


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str, _: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    row = await db.get(ReplicationConnection, connection_id)
    if not row:
        raise HTTPException(404, "Replication connection not found")
    cfg = await _replication_cfg(db, row)
    started = time.time()
    if not _has_credentials(row.connector_type, cfg):
        status, message, safe_error, details = "NOT_CONFIGURED", "Credentials are missing for this connector.", "", {}
    else:
        try:
            result = await asyncio.get_event_loop().run_in_executor(_executor, _test_sync, row.connector_type, cfg)
            status = result["status"]
            message = result["message"]
            safe_error = result.get("safe_error") or ""
            details = result.get("details") or {}
        except Exception as exc:
            status, message, safe_error, details = "FAIL", "Connection test failed.", _safe_text(exc), {}
    health = ConnectorHealthCheck(
        connection_id=row.id,
        status=status,
        checked_at=datetime.utcnow(),
        latency_ms=int((time.time() - started) * 1000),
        message=message,
        safe_error=safe_error,
        details=details,
    )
    row.status = status
    row.latest_error = safe_error
    row.last_tested_at = health.checked_at
    db.add(health)
    if status == "FAIL":
        await _record_error(db, connection_id=row.id, message=message, safe_detail=safe_error, category="connector_health")
    await db.commit()
    return _health_dict(health)


@router.get("/sources")
async def list_sources(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = list((await db.execute(select(ReplicationSource).order_by(ReplicationSource.created_at.desc()))).scalars().all())
    return [_source_dict(row) for row in rows]


@router.post("/sources/discover")
async def discover_source(body: SourceDiscoverRequest, _: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    conn = await db.get(ReplicationConnection, body.connection_id)
    if not conn:
        raise HTTPException(404, "Replication connection not found")
    source = (
        await db.execute(select(ReplicationSource).where(ReplicationSource.connection_id == conn.id))
    ).scalars().first()
    if not source:
        source = ReplicationSource(connection_id=conn.id, connector_type=conn.connector_type, name=conn.name)
        db.add(source)
        await db.flush()

    cfg = await _replication_cfg(db, conn)
    if not _has_credentials(conn.connector_type, cfg):
        result = {"status": "NOT_CONFIGURED", "reason": "Credentials are missing; discovery was not attempted.", "schemas": []}
    else:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                _executor,
                _discover_sync,
                conn.connector_type,
                cfg,
                body.schema_limit,
                body.table_limit,
                body.include_columns,
            )
        except Exception as exc:
            result = {"status": "FAIL", "reason": _safe_text(exc), "schemas": []}

    source.discovery_status = result["status"]
    source.discovery_reason = result["reason"]
    source.schemas = result["schemas"]
    source.discovered_at = datetime.utcnow()
    if result["status"] == "FAIL":
        await _record_error(db, connection_id=conn.id, message="Source discovery failed.", safe_detail=result["reason"], category="source_discovery")
    await db.commit()
    await db.refresh(source)
    return _source_dict(source)


@router.get("/jobs")
async def list_jobs(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    jobs = list((await db.execute(select(ReplicationJob).order_by(ReplicationJob.created_at.desc()))).scalars().all())
    conn_ids = {j.source_connection_id for j in jobs} | {j.destination_connection_id for j in jobs}
    conns = {}
    if conn_ids:
        conns = {c.id: c for c in (await db.execute(select(ReplicationConnection).where(ReplicationConnection.id.in_(list(conn_ids))))).scalars().all()}
    runs = list((await db.execute(select(ReplicationRun).order_by(ReplicationRun.created_at.desc()))).scalars().all())
    latest_runs = {}
    for run in runs:
        latest_runs.setdefault(run.job_id, run)
    counts = dict((await db.execute(select(ReplicationJobTable.job_id, func.count(ReplicationJobTable.id)).group_by(ReplicationJobTable.job_id))).all())
    return [_job_dict(j, conns.get(j.source_connection_id), conns.get(j.destination_connection_id), latest_runs.get(j.id), int(counts.get(j.id, 0))) for j in jobs]


@router.post("/jobs", status_code=201)
async def create_job(body: ReplicationJobCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    src = await db.get(ReplicationConnection, body.source_connection_id)
    dest = await db.get(ReplicationConnection, body.destination_connection_id)
    if not src:
        raise HTTPException(400, "Source replication connection not found")
    if not dest:
        raise HTTPException(400, "Destination replication connection not found")
    if src.role not in {"source", "both"}:
        raise HTTPException(400, "Selected source connection is not usable as a source")
    if dest.role not in {"destination", "both"}:
        raise HTTPException(400, "Selected destination connection is not usable as a destination")
    job = ReplicationJob(
        name=body.name.strip(),
        source_connection_id=src.id,
        destination_connection_id=dest.id,
        source_id=body.source_id,
        destination_id=body.destination_id,
        sync_mode=body.sync_mode,
        schedule=body.schedule,
        status="READY" if body.tables else "DRAFT",
        created_by_id=user.id,
    )
    db.add(job)
    await db.flush()
    for item in body.tables:
        db.add(ReplicationJobTable(
            job_id=job.id,
            schema_name=item.schema_name,
            table_name=item.table_name,
            target_schema=item.target_schema or item.schema_name,
            target_table=item.target_table or item.table_name,
            selected=item.selected,
            sync_mode=item.sync_mode or body.sync_mode,
            columns=item.columns,
            primary_key_columns=item.primary_key_columns,
            watermark_column=item.watermark_column,
        ))
    await _record_event(db, job_id=job.id, event_type="JOB_CREATED", message="Replication job created.")
    await db.commit()
    return _job_dict(job, src, dest, table_count=len(body.tables))


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(ReplicationJob, job_id)
    if not job:
        raise HTTPException(404, "Replication job not found")
    src = await db.get(ReplicationConnection, job.source_connection_id)
    dest = await db.get(ReplicationConnection, job.destination_connection_id)
    latest_run = (await db.execute(select(ReplicationRun).where(ReplicationRun.job_id == job.id).order_by(ReplicationRun.created_at.desc()).limit(1))).scalars().first()
    table_count = await db.scalar(select(func.count(ReplicationJobTable.id)).where(ReplicationJobTable.job_id == job.id)) or 0
    payload = _job_dict(job, src, dest, latest_run, int(table_count))
    payload["tables"] = await get_job_tables(job_id, _, db)
    return payload


async def _transition_job(
    db: AsyncSession,
    job: ReplicationJob,
    status: str,
    event_type: str,
    message: str,
    run: Optional[ReplicationRun] = None,
    event_json: Optional[dict[str, Any]] = None,
):
    job.status = status
    job.updated_at = datetime.utcnow()
    await _record_event(db, job_id=job.id, run_id=run.id if run else None, event_type=event_type, message=message, event_json=event_json)


@router.post("/jobs/{job_id}/start")
async def start_job(
    job_id: str,
    body: ReplicationStartRequest = ReplicationStartRequest(),
    background_tasks: BackgroundTasks = None,
    _: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ReplicationJob, job_id)
    if not job:
        raise HTTPException(404, "Replication job not found")
    dest = await db.get(ReplicationConnection, job.destination_connection_id)
    if body.execute and dest and dest.connector_type == "snowflake":
        cfg = normalize_snowflake_config({**(dest.config or {}), **(get_cipher().decrypt_dict(dest.credentials) if dest.credentials else {})})
        linked_connection_id = dest.connection_id or dest.id
        session_active = bool(snowflake_session_manager.get_active_session(user_id=str(_.id), connection_id=linked_connection_id))
        readiness = snowflake_execution_readiness(cfg, session_active=session_active)
        if readiness["missing_fields"]:
            await _record_event(
                db,
                job_id=job.id,
                event_type="SNOWFLAKE_CONFIGURATION_REQUIRED",
                level="ERROR",
                message=readiness["message"],
                event_json={"missing_fields": readiness["missing_fields"], "stage": "pre_execution"},
            )
            job.status = "FAILED"
            job.latest_error = readiness["message"]
            db.add(ReplicationError(job_id=job.id, category="configuration", message=readiness["message"], safe_detail="No data was moved."))
            await db.commit()
            raise HTTPException(409, readiness["message"])
        if readiness["requires_mfa_session"] and not readiness["session_active"]:
            await _record_event(
                db,
                job_id=job.id,
                event_type="SNOWFLAKE_SESSION_EXPIRED",
                level="ERROR",
                message=SNOWFLAKE_MFA_EXPIRED_MESSAGE,
                event_json={"stage": "pre_execution", "retryable": True, "recommended_action": "Unlock Snowflake and retry."},
            )
            job.status = "FAILED"
            job.latest_error = SNOWFLAKE_MFA_EXPIRED_MESSAGE
            db.add(ReplicationError(job_id=job.id, category="MFA_SESSION", message=SNOWFLAKE_MFA_EXPIRED_MESSAGE, safe_detail="No data was moved."))
            await db.commit()
            raise HTTPException(409, SNOWFLAKE_MFA_EXPIRED_MESSAGE)
    tables = list((await db.execute(select(ReplicationJobTable).where(ReplicationJobTable.job_id == job.id, ReplicationJobTable.selected == True))).scalars().all())
    if not tables:
        raise HTTPException(409, "Replication job has no selected tables to plan")
    attempt = (await db.scalar(select(func.count(ReplicationRun.id)).where(ReplicationRun.job_id == job.id)) or 0) + 1
    run = ReplicationRun(job_id=job.id, status="QUEUED", trigger="manual", attempt_number=int(attempt), planned_tables=len(tables))
    db.add(run)
    await db.flush()
    for table in tables:
        table.status = "PLANNED"
        db.add(ReplicationTableRun(
            run_id=run.id,
            job_id=job.id,
            job_table_id=table.id,
            schema_name=table.schema_name,
            table_name=table.table_name,
            status="PLANNED",
        ))
    if body.execute:
        await _transition_job(db, job, "QUEUED", "JOB_EXECUTION_QUEUED", "Replication run queued for real execution.", run, event_json={"provider": body.provider})
    else:
        await _transition_job(db, job, "QUEUED", "JOB_START_PLANNED", "Replication run planned; no data movement has been executed.", run)
    await db.commit()
    if body.execute:
        from services.replication_execution import execute_replication_run
        if background_tasks is not None:
            background_tasks.add_task(execute_replication_run, run.id, provider=body.provider, wait_for_completion=body.wait_for_completion, user_id=str(_.id))
        else:
            await execute_replication_run(run.id, provider=body.provider, wait_for_completion=body.wait_for_completion, user_id=str(_.id))
    return _run_dict(run)


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, _: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    job = await db.get(ReplicationJob, job_id)
    if not job:
        raise HTTPException(404, "Replication job not found")
    await _transition_job(db, job, "PAUSED", "JOB_PAUSED", "Replication job paused.")
    await db.commit()
    return _job_dict(job)


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, _: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    job = await db.get(ReplicationJob, job_id)
    if not job:
        raise HTTPException(404, "Replication job not found")
    status = "READY" if job.latest_error == "" else "READY_WITH_ERRORS"
    await _transition_job(db, job, status, "JOB_RESUMED", "Replication job resumed.")
    await db.commit()
    return _job_dict(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, _: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    job = await db.get(ReplicationJob, job_id)
    if not job:
        raise HTTPException(404, "Replication job not found")
    run = (await db.execute(select(ReplicationRun).where(ReplicationRun.job_id == job.id, ReplicationRun.status.in_(["QUEUED", "PLANNED"])).order_by(ReplicationRun.created_at.desc()).limit(1))).scalars().first()
    if run:
        run.status = "CANCELLED"
        run.ended_at = datetime.utcnow()
    await _transition_job(db, job, "CANCELLED", "JOB_CANCELLED", "Replication job cancelled.", run)
    await db.commit()
    return _job_dict(job)


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await start_job(job_id, ReplicationStartRequest(execute=True), None, user, db)


@router.get("/jobs/{job_id}/tables")
async def get_job_tables(job_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(ReplicationJob, job_id):
        raise HTTPException(404, "Replication job not found")
    rows = list((await db.execute(select(ReplicationJobTable).where(ReplicationJobTable.job_id == job_id).order_by(ReplicationJobTable.schema_name, ReplicationJobTable.table_name))).scalars().all())
    return [_table_dict(row) for row in rows]


@router.get("/jobs/{job_id}/plan")
async def get_job_plan(job_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(ReplicationJob, job_id):
        raise HTTPException(404, "Replication job not found")
    return await get_plan(db, job_id)


@router.get("/jobs/{job_id}/mapping")
async def get_job_mapping(job_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(ReplicationJob, job_id)
    if not job:
        raise HTTPException(404, "Replication job not found")
    tables = list((await db.execute(select(ReplicationJobTable).where(ReplicationJobTable.job_id == job_id).order_by(ReplicationJobTable.schema_name, ReplicationJobTable.table_name))).scalars().all())
    plans = {p.job_table_id: p for p in (await db.execute(select(ReplicationPlan).where(ReplicationPlan.job_id == job_id))).scalars().all()}

    def target_type(source_type: str) -> str:
        t = (source_type or "VARCHAR").upper()
        if any(x in t for x in ("INT", "SERIAL", "BIGINT")):
            return "NUMBER"
        if any(x in t for x in ("DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL")):
            return "NUMBER"
        if "TIMESTAMP" in t:
            return "TIMESTAMP_NTZ"
        if "DATE" in t:
            return "DATE"
        if "BOOL" in t:
            return "BOOLEAN"
        if "JSON" in t or "VARIANT" in t:
            return "VARIANT"
        return "VARCHAR"

    mappings = []
    for table in tables:
        plan = plans.get(table.id)
        columns = table.columns or []
        column_mapping = [
            {
                "source_column": col.get("name") or col.get("column_name"),
                "source_type": col.get("type") or col.get("data_type"),
                "target_column": (col.get("name") or col.get("column_name") or "").upper(),
                "snowflake_type": target_type(col.get("type") or col.get("data_type")),
                "nullable": col.get("nullable", True),
            }
            for col in columns
        ]
        mappings.append({
            "job_table_id": table.id,
            "source_schema": table.schema_name,
            "source_table": table.table_name,
            "target_schema": table.target_schema or table.schema_name,
            "target_table": table.target_table or table.table_name,
            "selected": table.selected,
            "columns": columns,
            "primary_key_columns": table.primary_key_columns or [],
            "watermark_column": table.watermark_column,
            "column_mapping": column_mapping,
            "target_exists": "NOT_CHECKED",
            "create_on_first_run": True,
            "auto_create_target_tables": False,
            "generated_ddl_status": "STAGE_FOR_REVIEW",
            "schema_drift_policy": plan.schema_drift_policy if plan else "ADDITIVE_ONLY_REVIEW",
            "load_mode": plan.load_mode if plan else table.sync_mode,
            "write_mode": plan.write_mode if plan else "",
            "uma_metadata_columns": [
                "_uma_synced_at", "_uma_loaded_at", "_uma_batch_id", "_uma_run_id",
                "_uma_replication_job_id", "_uma_source_system", "_uma_deleted", "_uma_schema_version",
            ],
            "snowflake_tags": {
                "created_by": "UMA",
                "source_connection": job.source_connection_id,
                "source_table": f"{table.schema_name}.{table.table_name}",
                "replication_job_id": job.id,
            },
        })
    return {"job_id": job_id, "mappings": mappings}


@router.get("/jobs/{job_id}/events")
async def get_job_events(job_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(ReplicationJob, job_id):
        raise HTTPException(404, "Replication job not found")
    rows = list((await db.execute(select(ReplicationEvent).where(ReplicationEvent.job_id == job_id).order_by(ReplicationEvent.created_at.desc()).limit(200))).scalars().all())
    return [_event_dict(row) for row in rows]


@router.get("/jobs/{job_id}/errors")
async def get_job_errors(job_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(ReplicationJob, job_id):
        raise HTTPException(404, "Replication job not found")
    rows = list((await db.execute(select(ReplicationError).where(ReplicationError.job_id == job_id).order_by(ReplicationError.created_at.desc()).limit(200))).scalars().all())
    return [_error_dict(row) for row in rows]


@router.post("/jobs/{job_id}/plan")
async def plan_job(job_id: str, _: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    if not await db.get(ReplicationJob, job_id):
        raise HTTPException(404, "Replication job not found")
    result = await create_or_update_plan(db, job_id)
    await _record_event(
        db,
        job_id=job_id,
        event_type="REPLICATION_PLAN_CREATED",
        message="Table-level replication plan created from persisted metadata.",
        event_json={"planned_tables": result["planned_tables"]},
    )
    await db.commit()
    return result


@router.put("/jobs/{job_id}/tables")
async def update_job_tables(job_id: str, body: JobTablesUpdate, _: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    job = await db.get(ReplicationJob, job_id)
    if not job:
        raise HTTPException(404, "Replication job not found")
    existing = {(t.schema_name, t.table_name): t for t in (await db.execute(select(ReplicationJobTable).where(ReplicationJobTable.job_id == job_id))).scalars().all()}
    requested = {(item.schema_name, item.table_name) for item in body.tables}
    for key, row in existing.items():
        if key not in requested:
            row.selected = False
            row.updated_at = datetime.utcnow()
    for item in body.tables:
        key = (item.schema_name, item.table_name)
        row = existing.get(key)
        if not row:
            row = ReplicationJobTable(job_id=job_id, schema_name=item.schema_name, table_name=item.table_name)
            db.add(row)
        row.target_schema = item.target_schema or item.schema_name
        row.target_table = item.target_table or item.table_name
        row.selected = item.selected
        row.sync_mode = item.sync_mode or job.sync_mode
        row.columns = item.columns
        row.primary_key_columns = item.primary_key_columns
        row.watermark_column = item.watermark_column
        row.updated_at = datetime.utcnow()
        if item.watermark_column:
            if not row.id:
                await db.flush()
            wm = (await db.execute(select(ReplicationWatermark).where(ReplicationWatermark.job_id == job_id, ReplicationWatermark.job_table_id == row.id))).scalars().first()
            if not wm:
                db.add(ReplicationWatermark(job_id=job_id, job_table_id=row.id, watermark_column=item.watermark_column))
            else:
                wm.watermark_column = item.watermark_column
    job.status = "READY" if body.tables else "DRAFT"
    job.updated_at = datetime.utcnow()
    await _record_event(db, job_id=job.id, event_type="JOB_TABLES_UPDATED", message="Selected replication tables updated.", event_json={"table_count": len(body.tables)})
    await db.commit()
    return await get_job_tables(job_id, _, db)


@router.get("/runs")
async def list_runs(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = list((await db.execute(select(ReplicationRun).order_by(ReplicationRun.created_at.desc()).limit(100))).scalars().all())
    return [_run_dict(row) for row in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(ReplicationRun, run_id)
    if not row:
        raise HTTPException(404, "Replication run not found")
    return _run_dict(row)


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(ReplicationRun, run_id):
        raise HTTPException(404, "Replication run not found")
    rows = list((await db.execute(select(ReplicationEvent).where(ReplicationEvent.run_id == run_id).order_by(ReplicationEvent.created_at.asc()))).scalars().all())
    return [_event_dict(row) for row in rows]


@router.get("/runs/{run_id}/tables")
async def get_run_tables(run_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(ReplicationRun, run_id):
        raise HTTPException(404, "Replication run not found")
    rows = list((await db.execute(select(ReplicationTableRun).where(ReplicationTableRun.run_id == run_id).order_by(ReplicationTableRun.schema_name, ReplicationTableRun.table_name))).scalars().all())
    return [_table_run_dict(row) for row in rows]


@router.get("/snowflake/readiness")
async def snowflake_readiness(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    checks = list((await db.execute(select(SnowflakePermissionCheck).order_by(SnowflakePermissionCheck.checked_at.desc()).limit(10))).scalars().all())
    latest = checks[0] if checks else None
    destinations = list((await db.execute(select(ReplicationDestination).order_by(ReplicationDestination.created_at.desc()))).scalars().all())
    return {
        "status": latest.status if latest else "NOT_CHECKED",
        "message": latest.message if latest else "No Snowflake permission check has been recorded.",
        "latest_check": _permission_dict(latest) if latest else None,
        "destinations": [_destination_dict(row) for row in destinations],
    }


def _permission_dict(row: SnowflakePermissionCheck) -> dict:
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "status": row.status,
        "checked_at": _iso(row.checked_at),
        "database": row.database,
        "schema": row.schema,
        "warehouse": row.warehouse,
        "missing_permissions": row.missing_permissions or [],
        "message": row.message,
        "safe_error": row.safe_error,
        "details": row.details or {},
    }


@router.post("/snowflake/check-permissions")
async def check_snowflake_permissions(body: SnowflakePermissionRequest, _: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    conn = await db.get(ReplicationConnection, body.connection_id) if body.connection_id else None
    if not conn and not body.connection_id:
        conn = (
            await db.execute(
                select(ReplicationConnection)
                .where(ReplicationConnection.connector_type == "snowflake")
                .order_by(ReplicationConnection.updated_at.desc())
                .limit(1)
            )
        ).scalars().first()
    if not conn:
        result = not_configured_readiness("Select a Snowflake replication connection before checking permissions.")
    else:
        cfg = await _replication_cfg(db, conn)
        if conn.connector_type != "snowflake":
            result = not_configured_readiness("Selected connection is not Snowflake.")
            result["status"] = "FAIL"
            result["safe_error"] = "Connector type mismatch."
        else:
            cfg = {**cfg, "database": body.database or cfg.get("database"), "schema": body.schema_name or cfg.get("schema"), "warehouse": body.warehouse or cfg.get("warehouse")}
            linked_connection_id = conn.connection_id or conn.id
            if cfg.get("auth_method") == "password_mfa":
                entry = snowflake_session_manager.get_active_session(user_id=str(_.id), connection_id=linked_connection_id)
                if not entry:
                    result = not_configured_readiness("Snowflake MFA session expired. Unlock Snowflake and retry.")
                    result["status"] = "WARNING"
                    result["details"]["mfa_required"] = True
                else:
                    def _check_active():
                        with entry["lock"]:
                            return check_snowflake_readiness_with_connector(entry["connector"])
                    result = await asyncio.get_event_loop().run_in_executor(_executor, _check_active)
            else:
                result = await asyncio.get_event_loop().run_in_executor(_executor, check_snowflake_readiness_sync, cfg)
    check = SnowflakePermissionCheck(
        connection_id=conn.id if conn else body.connection_id,
        status=result["status"],
        database=body.database or (conn.config or {}).get("database", "") if conn else body.database,
        schema=body.schema_name or (conn.config or {}).get("schema", "") if conn else body.schema_name,
        warehouse=body.warehouse or (conn.config or {}).get("warehouse", "") if conn else body.warehouse,
        missing_permissions=result.get("missing_permissions") or [],
        message=result["message"],
        safe_error=result.get("safe_error") or "",
        details=result.get("details") or {},
    )
    db.add(check)
    if conn:
        dest = (
            await db.execute(select(ReplicationDestination).where(ReplicationDestination.connection_id == conn.id))
        ).scalars().first()
        if dest:
            dest.readiness_status = check.status
            dest.latest_error = check.safe_error
            dest.checked_at = check.checked_at
    await db.commit()
    return _permission_dict(check)
