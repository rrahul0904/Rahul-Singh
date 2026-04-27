"""
UMA Platform — Schema Drift Routes
Live detection and auto-fix for schema drift between source and Snowflake.
"""

import asyncio
import logging
from typing import List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth import require_editor, get_current_user
from core.security import get_cipher
from models import Connection, ConnectionType, Job, JobTask, User
from connectors.snowflake_connector import SnowflakeConnector
from services.cdc_engine import SchemaDriftDetector

router = APIRouter()
logger = logging.getLogger("uma.routes.drift")
_executor = ThreadPoolExecutor(max_workers=5)


class DriftCheckRequest(BaseModel):
    job_id:       str
    source_table: str


class ApplyFixRequest(BaseModel):
    job_id:        str
    source_table:  str
    apply_actions: List[str]  # e.g. ["add_column:NEW_COL"]


async def _run_in_thread(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)


@router.post("/check")
async def check_drift(
    body: DriftCheckRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run a live schema drift check between the source and Snowflake."""
    job = await db.get(Job, body.job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Find the corresponding task
    task_r = await db.execute(
        select(JobTask).where(
            JobTask.job_id == body.job_id,
            JobTask.source_table == body.source_table,
        )
    )
    task = task_r.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found for this table")

    src_conn  = await db.get(Connection, job.source_connection_id)
    dest_conn = await db.get(Connection, job.dest_connection_id)

    # Get the current source schema
    source_schema = await _run_in_thread(_get_source_schema, src_conn, task)

    # Build SF config and run drift detector
    sf_cfg = _sf_config(dest_conn)

    def _detect():
        with SnowflakeConnector(sf_cfg) as sf:
            detector = SchemaDriftDetector(sf)
            return detector.detect_drift(
                source_schema=source_schema,
                database=job.sf_database,
                schema=job.sf_schema,
                table=task.target_table,
            )

    try:
        result = await _run_in_thread(_detect)
    except Exception as e:
        logger.exception(f"Drift check failed: {e}")
        raise HTTPException(500, f"Drift check failed: {e}")

    return {
        **result.to_dict(),
        "source_schema": source_schema,
        "job_id": body.job_id,
        "source_table": body.source_table,
    }


@router.post("/apply")
async def apply_drift_fix(
    body: ApplyFixRequest,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    """Apply auto-fix ALTER TABLE statements to resolve detected drift."""
    job = await db.get(Job, body.job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    task_r = await db.execute(
        select(JobTask).where(
            JobTask.job_id == body.job_id,
            JobTask.source_table == body.source_table,
        )
    )
    task = task_r.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    src_conn  = await db.get(Connection, job.source_connection_id)
    dest_conn = await db.get(Connection, job.dest_connection_id)

    source_schema = await _run_in_thread(_get_source_schema, src_conn, task)
    sf_cfg = _sf_config(dest_conn)

    def _apply():
        with SnowflakeConnector(sf_cfg) as sf:
            detector = SchemaDriftDetector(sf)
            result = detector.detect_drift(
                source_schema=source_schema,
                database=job.sf_database,
                schema=job.sf_schema,
                table=task.target_table,
            )
            if not result.has_drift:
                return {"applied": [], "message": "No drift detected"}

            # Only apply additions — type changes / removals require manual review
            executed = detector.apply_drift(
                drift_result=result,
                database=job.sf_database,
                schema=job.sf_schema,
                table=task.target_table,
                source_schema=source_schema,
                auto_add=True,
            )
            return {"applied": executed, "drifts_processed": len(result.drifts)}

    try:
        result = await _run_in_thread(_apply)
    except Exception as e:
        logger.exception(f"Drift apply failed: {e}")
        raise HTTPException(500, f"Drift apply failed: {e}")

    return result


# ─── Ad-hoc drift check (no job required) ────────────────────

class AdHocDriftRequest(BaseModel):
    source_connection_id:   str
    source_dataset:         str
    source_table:           str
    dest_connection_id:     str
    target_database:        str
    target_schema:          str
    target_table:           str


@router.post("/check-adhoc")
async def check_drift_adhoc(
    body: AdHocDriftRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run drift detection between any source table and any Snowflake target.
    No Job required — useful for exploratory drift analysis.
    """
    src = await db.get(Connection, body.source_connection_id)
    dst = await db.get(Connection, body.dest_connection_id)
    if not src or not dst:
        raise HTTPException(404, "Source or destination connection not found")

    # Build a fake JobTask-like object for the helper
    class _FakeTask:
        source_dataset = body.source_dataset
        source_table   = body.source_table
    fake_task = _FakeTask()

    try:
        source_schema = await _run_in_thread(_get_source_schema, src, fake_task)
    except Exception as e:
        logger.exception(f"Source schema fetch failed: {e}")
        raise HTTPException(400, f"Could not fetch source schema: {str(e)[:300]}")

    sf_cfg = _sf_config(dst)

    def _detect():
        with SnowflakeConnector(sf_cfg) as sf:
            detector = SchemaDriftDetector(sf)
            return detector.detect_drift(
                source_schema=source_schema,
                database=body.target_database,
                schema=body.target_schema,
                table=body.target_table,
            )

    try:
        result = await _run_in_thread(_detect)
    except Exception as e:
        logger.exception(f"Drift check failed: {e}")
        raise HTTPException(500, f"Drift check failed: {str(e)[:300]}")

    return {
        **result.to_dict(),
        "source_schema": source_schema,
        "source": {"connection": src.name, "table": body.source_table},
        "target": {"database": body.target_database, "schema": body.target_schema, "table": body.target_table},
    }


# ─── Helpers ──────────────────────────────────────────────────

def _sf_config(conn: Connection) -> Dict:
    credentials = get_cipher().decrypt_dict(conn.credentials) if conn.credentials else {}
    return {
        "account":   conn.config.get("account", ""),
        "user":      credentials.get("user", "") or conn.config.get("user", ""),
        "password":  credentials.get("password", ""),
        "warehouse": conn.config.get("warehouse", "COMPUTE_WH"),
        "database":  conn.config.get("database", ""),
        "schema":    conn.config.get("schema", ""),
        "role":      conn.config.get("role", "SYSADMIN"),
    }


def _get_source_schema(src_conn: Connection, task: JobTask) -> List[Dict]:
    """Dispatch to the right connector to get a live schema."""
    credentials = get_cipher().decrypt_dict(src_conn.credentials) if src_conn.credentials else {}
    cfg = {**src_conn.config, **credentials}
    t = src_conn.type

    if t == ConnectionType.bigquery:
        from connectors.bigquery_connector import BigQueryConnector
        with BigQueryConnector(cfg) as c:
            return c.get_table_schema(task.source_dataset, task.source_table)

    if t == ConnectionType.redshift:
        from connectors.redshift_connector import RedshiftConnector
        with RedshiftConnector(cfg) as c:
            return c.get_table_schema(task.source_dataset, task.source_table)

    if t == ConnectionType.sqlserver:
        from connectors.sqlserver_connector import SQLServerConnector
        with SQLServerConnector(cfg) as c:
            return c.get_table_schema(
                src_conn.config.get("schema", "dbo"), task.source_table)

    if t == ConnectionType.salesforce:
        from connectors.salesforce_connector import SalesforceConnector
        with SalesforceConnector(cfg) as c:
            return c.get_object_schema(task.source_table)

    if t in (ConnectionType.postgres, ConnectionType.mysql,
              ConnectionType.oracle, ConnectionType.teradata,
              ConnectionType.synapse):
        from connectors.db_connectors import (
            PostgreSQLConnector, MySQLConnector, OracleConnector,
            TeradataConnector, SynapseConnector
        )
        klass = {
            ConnectionType.postgres:  PostgreSQLConnector,
            ConnectionType.mysql:     MySQLConnector,
            ConnectionType.oracle:    OracleConnector,
            ConnectionType.teradata:  TeradataConnector,
            ConnectionType.synapse:   SynapseConnector,
        }[t]
        with klass(cfg) as c:
            return c.get_table_schema(task.source_dataset, task.source_table)

    # Default: empty schema — the drift check will be a no-op
    return []
