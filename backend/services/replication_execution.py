from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_cipher
from models import (
    Connection,
    DestinationMode,
    Job,
    JobTask,
    LoadStrategy,
    ReplicationConnection,
    ReplicationEvent,
    ReplicationJob,
    ReplicationJobTable,
    ReplicationRun,
    ReplicationTableRun,
)
from services.snowflake_connection import normalize_snowflake_config
from services.snowflake_session_manager import SNOWFLAKE_MFA_EXPIRED_MESSAGE, snowflake_session_manager


class ReplicationExecutionError(Exception):
    pass


def _safe_error(value: Any, limit: int = 1000) -> str:
    text = str(value or "")
    for marker in ("password", "secret", "token", "api_key", "api_secret", "Authorization", "mfa_passcode", "passcode"):
        text = text.replace(marker, "[redacted]")
    return text[:limit]


async def _connection_config(db: AsyncSession, conn: ReplicationConnection) -> dict[str, Any]:
    cfg = dict(conn.config or {})
    cipher = get_cipher()
    if conn.credentials:
        cfg.update(cipher.decrypt_dict(conn.credentials))
    if conn.connection_id:
        linked = await db.get(Connection, conn.connection_id)
        if linked:
            cfg = {
                **(linked.config or {}),
                **(cipher.decrypt_dict(linked.credentials) if linked.credentials else {}),
                **cfg,
            }
    return cfg


async def _event(
    db: AsyncSession,
    *,
    job_id: str,
    run_id: str,
    event_type: str,
    message: str,
    level: str = "INFO",
    event_json: Optional[dict[str, Any]] = None,
) -> None:
    db.add(ReplicationEvent(
        job_id=job_id,
        run_id=run_id,
        event_type=event_type,
        level=level,
        message=message,
        event_json=event_json or {},
    ))


def _basic_auth_header(api_key: str, api_secret: str) -> str:
    token = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    return f"Basic {token}"


async def _execute_fivetran(
    db: AsyncSession,
    job: ReplicationJob,
    run: ReplicationRun,
    source: ReplicationConnection,
    *,
    wait_for_completion: bool,
) -> dict[str, Any]:
    cfg = await _connection_config(db, source)
    api_key = cfg.get("api_key") or cfg.get("key")
    api_secret = cfg.get("api_secret") or cfg.get("secret")
    connection_id = cfg.get("fivetran_connection_id") or cfg.get("external_connection_id")
    base_url = (cfg.get("base_url") or "https://api.fivetran.com/v1").rstrip("/")
    force = bool(cfg.get("force", True))
    poll_seconds = min(int(cfg.get("poll_seconds") or 10), 60)
    max_polls = min(int(cfg.get("max_polls") or 30), 360)

    if not api_key or not api_secret or not connection_id:
        raise ReplicationExecutionError("Fivetran requires api_key, api_secret, and fivetran_connection_id.")

    headers = {
        "Authorization": _basic_auth_header(api_key, api_secret),
        "Accept": "application/json;version=2",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        trigger = await client.post(
            f"{base_url}/connections/{connection_id}/sync",
            headers=headers,
            json={"force": force},
        )
        if trigger.status_code >= 400:
            raise ReplicationExecutionError(f"Fivetran sync trigger failed: {trigger.status_code} {_safe_error(trigger.text)}")

        await _event(
            db,
            job_id=job.id,
            run_id=run.id,
            event_type="FIVETRAN_SYNC_TRIGGERED",
            message="Fivetran accepted the manual sync request.",
            event_json={"connection_id": connection_id, "force": force},
        )

        if not wait_for_completion:
            return {"status": "RUNNING", "message": "Fivetran sync was triggered and is running externally."}

        latest = None
        for _ in range(max_polls):
            detail = await client.get(f"{base_url}/connections/{connection_id}", headers=headers)
            if detail.status_code >= 400:
                raise ReplicationExecutionError(f"Fivetran status poll failed: {detail.status_code} {_safe_error(detail.text)}")
            payload = detail.json()
            latest = payload.get("data") or payload
            status = latest.get("status") or {}
            sync_state = status.get("sync_state")
            setup_state = status.get("setup_state")
            if sync_state in {"scheduled", "paused", "rescheduled"}:
                if setup_state == "broken":
                    raise ReplicationExecutionError("Fivetran connection setup is broken.")
                return {
                    "status": "SUCCEEDED",
                    "message": "Fivetran sync completed according to connection status.",
                    "external_status": status,
                    "succeeded_at": status.get("succeeded_at"),
                }
            await asyncio.sleep(poll_seconds)

        return {"status": "RUNNING", "message": "Fivetran sync is still running externally.", "external_status": latest.get("status") if latest else {}}


async def _execute_stitch_import(
    db: AsyncSession,
    job: ReplicationJob,
    run: ReplicationRun,
    source: ReplicationConnection,
) -> dict[str, Any]:
    cfg = await _connection_config(db, source)
    access_token = cfg.get("access_token") or cfg.get("token")
    client_id = cfg.get("client_id")
    base_url = (cfg.get("base_url") or "https://api.stitchdata.com").rstrip("/")
    records = cfg.get("records") or []

    if not access_token or not client_id:
        raise ReplicationExecutionError("Stitch Import API requires access_token and client_id.")
    if not records:
        raise ReplicationExecutionError("Stitch Import API execution requires a non-empty records array in the connection config.")

    prepared = []
    for record in records:
        item = dict(record)
        item.setdefault("client_id", client_id)
        item.setdefault("action", "upsert")
        if "sequence" not in item:
            item["sequence"] = int(datetime.utcnow().timestamp())
        prepared.append(item)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base_url}/v2/import/push",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=prepared,
        )
        if response.status_code >= 400:
            raise ReplicationExecutionError(f"Stitch Import API push failed: {response.status_code} {_safe_error(response.text)}")
        payload = response.json()

    await _event(
        db,
        job_id=job.id,
        run_id=run.id,
        event_type="STITCH_IMPORT_PUSHED",
        message="Stitch Import API accepted the record batch.",
        event_json={"record_count": len(prepared), "response": payload},
    )
    return {"status": "SUCCEEDED", "message": "Stitch Import API accepted the record batch.", "records_sent": len(prepared)}


def _load_strategy(value: str) -> LoadStrategy:
    if value == "full_refresh":
        return LoadStrategy.full_load
    if value == "cdc":
        return LoadStrategy.cdc
    return LoadStrategy.incremental


async def _execute_uma_snowflake(db: AsyncSession, job: ReplicationJob, run: ReplicationRun, user_id: str | None = None) -> dict[str, Any]:
    source = await db.get(ReplicationConnection, job.source_connection_id)
    dest = await db.get(ReplicationConnection, job.destination_connection_id)
    if not source or not dest or not source.connection_id or not dest.connection_id:
        raise ReplicationExecutionError("UMA Snowflake execution requires source and destination replication connections linked to platform connections.")

    linked_source = await db.get(Connection, source.connection_id)
    linked_dest = await db.get(Connection, dest.connection_id)
    if not linked_source or not linked_dest:
        raise ReplicationExecutionError("Linked platform source or destination connection is missing.")
    dest_cfg_full = {
        **(linked_dest.config or {}),
        **(get_cipher().decrypt_dict(linked_dest.credentials) if linked_dest.credentials else {}),
    }
    if dest_cfg_full.get("auth_method") == "password_mfa" and not (
        user_id and snowflake_session_manager.get_active_session(user_id=str(user_id), connection_id=linked_dest.id)
    ):
        raise ReplicationExecutionError(SNOWFLAKE_MFA_EXPIRED_MESSAGE)

    tables = list((await db.execute(
        select(ReplicationJobTable).where(ReplicationJobTable.job_id == job.id, ReplicationJobTable.selected == True)
    )).scalars().all())
    if not tables:
        raise ReplicationExecutionError("Replication job has no selected tables to execute.")

    dest_cfg = normalize_snowflake_config(linked_dest.config or {})
    migration_job = Job(
        name=f"replication:{job.id}:{run.id}",
        source_connection_id=linked_source.id,
        dest_connection_id=linked_dest.id,
        sf_warehouse=dest_cfg.get("warehouse") or "",
        sf_database=dest_cfg.get("database") or "",
        sf_schema=dest_cfg.get("schema") or "",
        sf_role=dest_cfg.get("role") or "",
        destination_mode=DestinationMode.internal,
        load_strategy=_load_strategy(job.sync_mode),
        file_format="parquet",
        staging_area="internal",
    )
    db.add(migration_job)
    await db.flush()
    for table in tables:
        db.add(JobTask(
            job_id=migration_job.id,
            source_dataset=table.schema_name,
            source_table=table.table_name,
            target_schema=table.target_schema or table.schema_name,
            target_table=table.target_table or table.table_name,
            config={
                "primary_key_columns": table.primary_key_columns or [],
                "watermark_column": table.watermark_column,
            },
        ))
    await db.commit()

    from services.migration_orchestrator import execute_job

    result = await execute_job(migration_job.id, "real", user_id=user_id)
    if not result.get("success"):
        raise ReplicationExecutionError(result.get("error") or "UMA Snowflake execution failed.")
    return {"status": "SUCCEEDED", "message": "UMA Snowflake execution completed.", "migration_job_id": migration_job.id, "result": result}


async def execute_replication_run(
    run_id: str,
    *,
    provider: str = "auto",
    wait_for_completion: bool = False,
    user_id: str | None = None,
) -> None:
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        run = await db.get(ReplicationRun, run_id)
        if not run:
            return
        job = await db.get(ReplicationJob, run.job_id)
        if not job:
            return
        source = await db.get(ReplicationConnection, job.source_connection_id)
        if not source:
            run.status = "FAILED"
            run.latest_error = "Source replication connection is missing."
            await db.commit()
            return

        chosen = provider
        if chosen == "auto":
            if source.connector_type == "fivetran":
                chosen = "fivetran"
            elif source.connector_type == "stitch":
                chosen = "stitch"
            else:
                chosen = "uma_snowflake"

        run.status = "RUNNING"
        run.started_at = datetime.utcnow()
        job.status = "RUNNING"
        await _event(db, job_id=job.id, run_id=run.id, event_type="REPLICATION_EXECUTION_STARTED", message=f"Execution provider: {chosen}", event_json={"provider": chosen})
        await db.commit()

        try:
            if chosen == "fivetran":
                result = await _execute_fivetran(db, job, run, source, wait_for_completion=wait_for_completion)
            elif chosen == "stitch":
                result = await _execute_stitch_import(db, job, run, source)
            elif chosen == "uma_snowflake":
                result = await _execute_uma_snowflake(db, job, run, user_id=user_id)
            else:
                raise ReplicationExecutionError(f"Unknown replication execution provider: {chosen}")

            run.status = result["status"]
            if result["status"] == "SUCCEEDED":
                run.ended_at = datetime.utcnow()
                job.status = "SUCCEEDED"
                job.last_sync_at = run.ended_at
                table_status = "SUCCEEDED"
            else:
                job.status = result["status"]
                table_status = "RUNNING"
            table_runs = list((await db.execute(select(ReplicationTableRun).where(ReplicationTableRun.run_id == run.id))).scalars().all())
            for table_run in table_runs:
                table_run.status = table_status
            await _event(db, job_id=job.id, run_id=run.id, event_type="REPLICATION_EXECUTION_UPDATED", message=result["message"], event_json=result)
        except Exception as exc:
            safe = _safe_error(exc)
            run.status = "FAILED"
            run.ended_at = datetime.utcnow()
            run.latest_error = safe
            job.status = "FAILED"
            job.latest_error = safe
            table_runs = list((await db.execute(select(ReplicationTableRun).where(ReplicationTableRun.run_id == run.id))).scalars().all())
            for table_run in table_runs:
                table_run.status = "FAILED"
                table_run.latest_error = safe
            await _event(db, job_id=job.id, run_id=run.id, event_type="REPLICATION_EXECUTION_FAILED", message=safe, level="ERROR")
        finally:
            job.updated_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            await db.commit()
