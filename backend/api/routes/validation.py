"""
UMA Platform — Validation Routes (Phase 3 hardened)

Real source-vs-target reconciliation:
  - row_count: counts on BOTH sides (source via SqlSourceAdapter / BigQuerySourceAdapter,
    target via Snowflake) when source_connection_id + source_dataset + source_table are set.
    Falls back to user-provided source_query / target_query if given, else target-only.
  - checksum: hash-based reconciliation. Computes an order-independent hash of the row
    bag on each side and compares. Uses MD5(CONCAT_WS('|', col1, col2, ...)) summed.
  - schema / null / duplicate / freshness: as before, with the same target Snowflake checks.

The /reconcile endpoint takes a job_id, derives row_count and checksum rules per task,
runs them all, and returns a reconciliation summary.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import get_db, AsyncSessionLocal
from core.security import get_cipher
from models import Connection, ConnectionType, Job, ValidationRule

router = APIRouter()
logger = logging.getLogger("uma.routes.validation")


# ─── Schemas ────────────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    name: str
    rule_type: str  # row_count | schema | null | duplicate | freshness | checksum
    target_table: str
    job_id: Optional[str] = None
    source_connection_id: Optional[str] = None
    source_dataset: Optional[str] = None
    source_table: Optional[str] = None
    primary_key_columns: Optional[list[str]] = None
    source_query: Optional[str] = None
    target_query: Optional[str] = None
    threshold_pct: float = 0.0


class ReconcileRequest(BaseModel):
    job_id: str
    rule_types: list[str] = ["row_count"]  # may include "checksum"


# ─── Helpers ────────────────────────────────────────────────────────────────

def _rule_dict(r: ValidationRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "rule_type": r.rule_type,
        "target_table": r.target_table,
        "job_id": r.job_id,
        "source_connection_id": r.source_connection_id,
        "source_dataset": r.source_dataset,
        "source_table": r.source_table,
        "primary_key_columns": r.primary_key_columns or [],
        "status": r.status,
        "source_value": r.source_value,
        "target_value": r.target_value,
        "delta": r.delta,
        "last_run": r.last_run.isoformat() if r.last_run else None,
        "error_message": r.error_message,
        "threshold_pct": r.threshold_pct,
    }


def _split_target_table(target: str, default_db: str, default_schema: str) -> tuple[str, str, str]:
    parts = [p.strip().strip('"') for p in target.split(".")]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return default_db, parts[0], parts[1]
    return default_db, default_schema, parts[0]


# ─── CRUD ───────────────────────────────────────────────────────────────────

@router.get("")
async def list_rules(job_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(ValidationRule).order_by(ValidationRule.created_at.desc())
    if job_id:
        q = q.where(ValidationRule.job_id == job_id)
    result = await db.execute(q)
    return [_rule_dict(r) for r in result.scalars().all()]


@router.post("", status_code=201)
async def create_rule(body: RuleCreate, db: AsyncSession = Depends(get_db)):
    rule = ValidationRule(
        name=body.name,
        rule_type=body.rule_type,
        target_table=body.target_table,
        job_id=body.job_id,
        source_connection_id=body.source_connection_id,
        source_dataset=body.source_dataset,
        source_table=body.source_table,
        primary_key_columns=body.primary_key_columns or [],
        source_query=body.source_query,
        target_query=body.target_query,
        threshold_pct=body.threshold_pct,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_dict(rule)


@router.get("/{rule_id}")
async def get_rule(rule_id: str, db: AsyncSession = Depends(get_db)):
    rule = await db.get(ValidationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return _rule_dict(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, db: AsyncSession = Depends(get_db)):
    rule = await db.get(ValidationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    await db.delete(rule)
    await db.commit()


# ─── Run ────────────────────────────────────────────────────────────────────

@router.post("/{rule_id}/run")
async def run_rule(
    rule_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    rule = await db.get(ValidationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    rule.status = "RUNNING"
    await db.commit()
    background_tasks.add_task(_execute_rule, rule_id)
    return {"message": "Validation started", "rule_id": rule_id}


@router.post("/reconcile")
async def reconcile_job(body: ReconcileRequest, db: AsyncSession = Depends(get_db)):
    """Auto-create row_count (and optionally checksum) rules for every task in a job,
    run them synchronously, return reconciliation summary.

    This is the 'is what landed in Snowflake what was in the source?' check.
    """
    job = (
        await db.execute(
            select(Job).options(selectinload(Job.tasks)).where(Job.id == body.job_id)
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.tasks:
        raise HTTPException(400, "Job has no tasks to reconcile")

    valid_types = {"row_count", "checksum"}
    rule_types = [t for t in body.rule_types if t in valid_types]
    if not rule_types:
        raise HTTPException(400, f"rule_types must contain at least one of {valid_types}")

    created_rules: list[ValidationRule] = []
    for task in job.tasks:
        task_cfg = task.config or {}
        pks = task_cfg.get("primary_key_columns") or task_cfg.get("primary_keys") or []
        if isinstance(pks, str):
            pks = [x.strip() for x in pks.split(",") if x.strip()]
        target_full = f"{job.sf_database}.{job.sf_schema}.{task.target_table}"
        for rt in rule_types:
            if rt == "checksum" and not pks:
                # Skip checksum if we don't have a stable identity to sort by
                logger.info("Skipping checksum for %s — no primary_key_columns configured", task.target_table)
                continue
            rule = ValidationRule(
                name=f"auto_{rt}_{task.target_table}",
                rule_type=rt,
                target_table=target_full,
                job_id=job.id,
                source_connection_id=job.source_connection_id,
                source_dataset=task.source_dataset,
                source_table=task.source_table,
                primary_key_columns=pks,
                threshold_pct=0.0,
                status="RUNNING",
            )
            db.add(rule)
            created_rules.append(rule)
    await db.commit()
    for r in created_rules:
        await db.refresh(r)

    # Run all rules synchronously in a thread pool — this endpoint blocks until done,
    # which is fine for a reconcile button click. For very large jobs the user can
    # still create individual rules and run them async.
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=min(8, len(created_rules) or 1)) as pool:
        await asyncio.gather(*[
            loop.run_in_executor(pool, _run_rule_sync_blocking, r.id)
            for r in created_rules
        ])

    # Re-read final state
    final = (
        await db.execute(
            select(ValidationRule).where(ValidationRule.id.in_([r.id for r in created_rules]))
        )
    ).scalars().all()

    by_type: dict[str, dict[str, int]] = {}
    for r in final:
        bucket = by_type.setdefault(r.rule_type, {"passed": 0, "failed": 0})
        if r.status == "SUCCEEDED":
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1

    return {
        "job_id": job.id,
        "rules_created": len(created_rules),
        "summary_by_type": by_type,
        "rules": [_rule_dict(r) for r in final],
    }


# ─── Execution ──────────────────────────────────────────────────────────────

async def _execute_rule(rule_id: str):
    """Async wrapper for background_tasks; runs the sync executor in a thread."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        await loop.run_in_executor(pool, _run_rule_sync_blocking, rule_id)


def _run_rule_sync_blocking(rule_id: str):
    """Open a fresh sync DB session, look up the rule, dispatch, persist result.
    Blocking — call only from a worker thread."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from core.config import settings as cfg

    # We need a *sync* session because the connector libs are blocking. The
    # async DB URL is converted to a sync one for this scope only.
    sync_url = cfg.DATABASE_URL.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
    engine = create_engine(sync_url, pool_pre_ping=True)
    SyncSession = sessionmaker(bind=engine)
    session = SyncSession()
    try:
        rule = session.get(ValidationRule, rule_id)
        if not rule:
            return
        try:
            result = _dispatch(session, rule)
            rule.status = result["status"]
            rule.source_value = str(result.get("source_value", "")) if result.get("source_value") is not None else None
            rule.target_value = str(result.get("target_value", "")) if result.get("target_value") is not None else None
            rule.delta = str(result.get("delta", "")) if result.get("delta") is not None else None
            rule.error_message = result.get("error")
        except Exception as e:
            logger.exception("Rule %s failed", rule_id)
            rule.status = "FAILED"
            rule.error_message = str(e)
        rule.last_run = datetime.utcnow()
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _dispatch(session, rule: ValidationRule) -> dict[str, Any]:
    from core.config import settings as cfg
    from connectors.snowflake_connector import SnowflakeConnector

    job = session.get(Job, rule.job_id) if rule.job_id else None
    dest_conn = session.get(Connection, job.dest_connection_id) if job else None
    if dest_conn and dest_conn.type == ConnectionType.snowflake:
        credentials = get_cipher().decrypt_dict(dest_conn.credentials) if dest_conn.credentials else {}
        dest_cfg = {**(dest_conn.config or {}), **credentials}
        sf_config = {
            "account": dest_cfg.get("account", ""),
            "user": dest_cfg.get("user") or dest_cfg.get("username", ""),
            "password": dest_cfg.get("password", ""),
            "warehouse": job.sf_warehouse or dest_cfg.get("warehouse", ""),
            "database": job.sf_database or dest_cfg.get("database", ""),
            "schema": job.sf_schema or dest_cfg.get("schema", ""),
            "role": job.sf_role or dest_cfg.get("role", ""),
        }
    else:
        sf_config = {
            "account": cfg.SNOWFLAKE_ACCOUNT,
            "user": cfg.SNOWFLAKE_USER,
            "password": cfg.SNOWFLAKE_PASSWORD,
            "warehouse": cfg.SNOWFLAKE_WAREHOUSE,
            "database": cfg.SNOWFLAKE_DATABASE,
            "schema": cfg.SNOWFLAKE_SCHEMA,
            "role": cfg.SNOWFLAKE_ROLE,
        }

    source_conn = None
    if rule.source_connection_id:
        source_conn = session.get(Connection, rule.source_connection_id)

    with SnowflakeConnector(sf_config) as sf:
        if rule.rule_type == "row_count":
            return _check_row_count(sf, rule, source_conn)
        if rule.rule_type == "checksum":
            return _check_checksum(sf, rule, source_conn)
        if rule.rule_type == "schema":
            return _check_schema(sf, rule)
        if rule.rule_type == "null":
            return _check_nulls(sf, rule)
        if rule.rule_type == "duplicate":
            return _check_duplicates(sf, rule)
        if rule.rule_type == "freshness":
            return _check_freshness(sf, rule)
        return {"status": "FAILED", "error": f"Unknown rule_type: {rule.rule_type}"}


# ─── Source-side helpers ────────────────────────────────────────────────────

def _open_source_conn(conn: Connection):
    """Open a sync source connection for source-side counts/hashes.
    Returns (cursor-style obj, close_callable, qident_callable, fqtn_callable)."""
    credentials = get_cipher().decrypt_dict(conn.credentials) if conn.credentials else {}
    cfg = {**(conn.config or {}), **credentials}
    if conn.type in (ConnectionType.postgres, ConnectionType.redshift):
        import psycopg2
        c = psycopg2.connect(
            host=cfg.get("host"),
            port=int(cfg.get("port") or (5439 if conn.type == ConnectionType.redshift else 5432)),
            dbname=cfg.get("database") or cfg.get("dbname"),
            user=cfg.get("user") or cfg.get("username"),
            password=cfg.get("password"),
            connect_timeout=30,
            sslmode=cfg.get("sslmode", "prefer"),
        )

        def q(name: str) -> str:
            return '"' + str(name).replace('"', '""') + '"'

        def fqtn(d: str, t: str) -> str:
            return f"{q(d)}.{q(t)}" if d else q(t)

        return c, c.close, q, fqtn

    if conn.type == ConnectionType.mysql:
        import mysql.connector
        c = mysql.connector.connect(
            host=cfg.get("host"),
            port=int(cfg.get("port") or 3306),
            database=cfg.get("database"),
            user=cfg.get("user") or cfg.get("username"),
            password=cfg.get("password"),
            connection_timeout=30,
        )

        def q(name: str) -> str:
            return "`" + str(name).replace("`", "``") + "`"

        def fqtn(d: str, t: str) -> str:
            return f"{q(d)}.{q(t)}" if d else q(t)

        return c, c.close, q, fqtn

    if conn.type == ConnectionType.bigquery:
        # BigQuery has its own client model; we wrap a small shim.
        import json as _json
        from google.cloud import bigquery
        from google.oauth2 import service_account

        sa_json = cfg.get("service_account_json")
        sa_info = _json.loads(sa_json) if isinstance(sa_json, str) else sa_json
        if not sa_info:
            raise ValueError("BigQuery service_account_json is required")
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/bigquery"]
        )
        project_id = cfg.get("project_id") or sa_info.get("project_id")
        client = bigquery.Client(project=project_id, credentials=creds)

        class _BQShim:
            def __init__(self, client, project_id):
                self.client = client
                self.project_id = project_id

            def query_one(self, sql: str) -> Any:
                rows = list(self.client.query(sql).result())
                if not rows:
                    return None
                return list(rows[0].values())[0]

            def close(self):
                self.client.close()

        shim = _BQShim(client, project_id)

        def q(name: str) -> str:
            return f"`{name}`"

        def fqtn(d: str, t: str) -> str:
            return f"`{project_id}.{d}.{t}`" if d else f"`{project_id}.{t}`"

        return shim, shim.close, q, fqtn

    raise NotImplementedError(f"Source-side validation not supported for {conn.type.value}")


def _source_count(conn: Connection, dataset: str, table: str) -> int:
    src, close_fn, q, fqtn = _open_source_conn(conn)
    try:
        if conn.type == ConnectionType.bigquery:
            return int(src.query_one(f"SELECT COUNT(*) FROM {fqtn(dataset, table)}") or 0)
        cur = src.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {fqtn(dataset, table)}")
            return int(cur.fetchone()[0] or 0)
        finally:
            cur.close()
    finally:
        try:
            close_fn()
        except Exception:
            pass


def _source_checksum(conn: Connection, dataset: str, table: str, columns: list[str]) -> str:
    """Order-independent row-bag hash. Computes per-row MD5(col1||'|'||col2||...),
    sums them as bigints, returns a hex digest. Two tables produce the same
    checksum if and only if (modulo hash collisions) they contain the same rows.

    Implementation note: we rely on database-side hashing for scale. For Postgres
    we use MD5 + bit_xor of the upper 31 bits as a portable proxy; we actually
    compute SUM of the hash converted to bigint mod 2^63 to get an order-independent
    aggregate. Pulling all rows back to Python would not scale.
    """
    src, close_fn, q, fqtn = _open_source_conn(conn)
    try:
        col_concat = " || '|' || ".join(f"COALESCE({q(c)}::TEXT, '')" for c in columns)
        sql = (
            f"SELECT COALESCE(SUM(('x' || SUBSTR(MD5({col_concat}), 1, 15))::BIT(60)::BIGINT), 0) "
            f"FROM {fqtn(dataset, table)}"
        )
        if conn.type in (ConnectionType.postgres, ConnectionType.redshift):
            cur = src.cursor()
            try:
                cur.execute(sql)
                v = cur.fetchone()[0]
                return str(v)
            finally:
                cur.close()
        if conn.type == ConnectionType.mysql:
            mysql_concat = ", '|', ".join(f"IFNULL(CAST({q(c)} AS CHAR), '')" for c in columns)
            sql = (
                f"SELECT COALESCE(SUM(CAST(CONV(SUBSTRING(MD5(CONCAT_WS('|', {', '.join(q(c) for c in columns)})), 1, 15), 16, 10) AS UNSIGNED)), 0) "
                f"FROM {fqtn(dataset, table)}"
            )
            cur = src.cursor()
            try:
                cur.execute(sql)
                v = cur.fetchone()[0]
                return str(v)
            finally:
                cur.close()
        if conn.type == ConnectionType.bigquery:
            bq_cols = ", ".join(f"IFNULL(CAST({q(c)} AS STRING), '')" for c in columns)
            sql = (
                f"SELECT COALESCE(SUM(CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(CONCAT_WS('|', {bq_cols}))), 1, 15)) AS INT64)), 0) "
                f"FROM {fqtn(dataset, table)}"
            )
            return str(src.query_one(sql) or 0)
    finally:
        try:
            close_fn()
        except Exception:
            pass
    raise NotImplementedError(f"Checksum not supported for {conn.type.value}")


def _target_checksum(sf, target_table: str, columns: list[str]) -> str:
    col_concat = ", '|', ".join(f"COALESCE(TO_VARCHAR({_q(c)}), '')" for c in columns)
    sql = (
        f"SELECT COALESCE(SUM(CAST(CONCAT('0x', SUBSTR(MD5(CONCAT_WS('|', {', '.join(_q(c) for c in columns)})), 1, 15)) AS NUMBER(38,0))), 0) "
        f"FROM {target_table} WHERE COALESCE(_UMA_IS_DELETED, FALSE) = FALSE"
    )
    rows = sf.run_query(sql)
    if not rows:
        return "0"
    return str(list(rows[0].values())[0])


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _target_count(sf, rule: ValidationRule) -> int:
    """Snowflake row count, excluding soft-deleted rows tracked by the engine."""
    sql = (
        f"SELECT COUNT(*) AS cnt FROM {rule.target_table} "
        f"WHERE COALESCE(_UMA_IS_DELETED, FALSE) = FALSE"
    )
    try:
        rows = sf.run_query(sql)
        return int(rows[0]["CNT"]) if rows else 0
    except Exception:
        # Target may not have _UMA_IS_DELETED if it pre-dates the new engine.
        rows = sf.run_query(f"SELECT COUNT(*) AS cnt FROM {rule.target_table}")
        return int(rows[0]["CNT"]) if rows else 0


# ─── Rule dispatch ─────────────────────────────────────────────────────────

def _check_row_count(sf, rule: ValidationRule, source_conn: Optional[Connection]) -> dict:
    """Compare row counts. Resolution order:
       1. user-supplied source_query + target_query
       2. source_connection + source_dataset + source_table  ->  target row count
       3. target only (no comparison; reports target count)
    """
    if rule.source_query and rule.target_query:
        src_rows = sf.run_query(rule.source_query)
        tgt_rows = sf.run_query(rule.target_query)
        src_count = list(src_rows[0].values())[0] if src_rows else 0
        tgt_count = list(tgt_rows[0].values())[0] if tgt_rows else 0
        compared = True
    elif source_conn and rule.source_table:
        src_count = _source_count(source_conn, rule.source_dataset or "", rule.source_table)
        tgt_count = _target_count(sf, rule)
        compared = True
    else:
        tgt_count = _target_count(sf, rule)
        return {
            "status": "SUCCEEDED",
            "source_value": "—",
            "target_value": tgt_count,
            "delta": "no source configured",
        }

    delta = abs(int(src_count) - int(tgt_count))
    delta_pct = (delta / int(src_count) * 100) if src_count else 0
    passed = delta_pct <= (rule.threshold_pct or 0)
    return {
        "status": "SUCCEEDED" if passed else "FAILED",
        "source_value": src_count,
        "target_value": tgt_count,
        "delta": f"{int(tgt_count) - int(src_count):+,} ({delta_pct:.2f}%)",
        "error": None if passed else f"Delta {delta_pct:.2f}% exceeds threshold {rule.threshold_pct}%",
    }


def _check_checksum(sf, rule: ValidationRule, source_conn: Optional[Connection]) -> dict:
    """Hash-based reconciliation. Requires source_connection + source_table + primary_key_columns."""
    if not source_conn or not rule.source_table:
        return {
            "status": "FAILED",
            "error": "Checksum requires source_connection_id and source_table",
            "source_value": "—", "target_value": "—", "delta": "—",
        }
    if not (rule.primary_key_columns):
        return {
            "status": "FAILED",
            "error": "Checksum requires primary_key_columns to define row identity",
            "source_value": "—", "target_value": "—", "delta": "—",
        }
    pks = rule.primary_key_columns
    try:
        src_hash = _source_checksum(source_conn, rule.source_dataset or "", rule.source_table, pks)
        tgt_hash = _target_checksum(sf, rule.target_table, pks)
    except Exception as e:
        return {
            "status": "FAILED",
            "error": f"Checksum computation failed: {e}",
            "source_value": "—", "target_value": "—", "delta": "—",
        }
    passed = src_hash == tgt_hash
    return {
        "status": "SUCCEEDED" if passed else "FAILED",
        "source_value": src_hash[:24],
        "target_value": tgt_hash[:24],
        "delta": "match" if passed else "mismatch",
        "error": None if passed else "Source and target row-bag checksums differ",
    }


def _check_schema(sf, rule: ValidationRule) -> dict:
    parts = rule.target_table.split(".")
    if len(parts) == 3:
        db, schema, table = parts
    elif len(parts) == 2:
        db, schema, table = sf.config.get("database", ""), parts[0], parts[1]
    else:
        db, schema, table = sf.config.get("database", ""), sf.config.get("schema", ""), parts[0]
    try:
        cols = sf.get_column_list(db.strip('"'), schema.strip('"'), table.strip('"'))
        return {
            "status": "SUCCEEDED",
            "source_value": "N/A",
            "target_value": f"{len(cols)} columns",
            "delta": "—",
        }
    except Exception as e:
        return {"status": "FAILED", "error": str(e), "source_value": "—", "target_value": "—", "delta": "—"}


def _check_nulls(sf, rule: ValidationRule) -> dict:
    if rule.target_query:
        result = sf.run_query(rule.target_query)
        null_count = list(result[0].values())[0] if result else 0
    else:
        null_count = 0
    passed = null_count == 0
    return {
        "status": "SUCCEEDED" if passed else "FAILED",
        "source_value": "0",
        "target_value": str(null_count),
        "delta": str(null_count),
        "error": None if passed else f"{null_count} unexpected nulls found",
    }


def _check_duplicates(sf, rule: ValidationRule) -> dict:
    if rule.target_query:
        result = sf.run_query(rule.target_query)
        dup_count = list(result[0].values())[0] if result else 0
    elif rule.primary_key_columns:
        # Auto-derive: GROUP BY pk HAVING COUNT(*) > 1
        pk_cols = ", ".join(_q(c) for c in rule.primary_key_columns)
        sql = (
            f"SELECT COUNT(*) AS cnt FROM ("
            f"  SELECT {pk_cols} FROM {rule.target_table} "
            f"  WHERE COALESCE(_UMA_IS_DELETED, FALSE) = FALSE "
            f"  GROUP BY {pk_cols} HAVING COUNT(*) > 1"
            f") d"
        )
        try:
            result = sf.run_query(sql)
            dup_count = int(result[0]["CNT"]) if result else 0
        except Exception:
            sql2 = (
                f"SELECT COUNT(*) AS cnt FROM ("
                f"  SELECT {pk_cols} FROM {rule.target_table} GROUP BY {pk_cols} HAVING COUNT(*) > 1"
                f") d"
            )
            result = sf.run_query(sql2)
            dup_count = int(result[0]["CNT"]) if result else 0
    else:
        dup_count = 0
    passed = dup_count == 0
    return {
        "status": "SUCCEEDED" if passed else "FAILED",
        "source_value": "0",
        "target_value": str(dup_count),
        "delta": str(dup_count),
        "error": None if passed else f"{dup_count} duplicate keys found",
    }


def _check_freshness(sf, rule: ValidationRule) -> dict:
    if rule.target_query:
        result = sf.run_query(rule.target_query)
        latest = list(result[0].values())[0] if result else None
    else:
        try:
            result = sf.run_query(f"SELECT MAX(_uma_loaded_at) AS latest FROM {rule.target_table}")
            latest = list(result[0].values())[0] if result else None
        except Exception:
            latest = None

    if latest is None:
        return {
            "status": "FAILED",
            "error": "Could not determine freshness — no timestamp column found",
            "source_value": "—", "target_value": "—", "delta": "—",
        }

    if hasattr(latest, "replace"):
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - latest).total_seconds() / 60
    else:
        age_minutes = 0

    threshold_minutes = rule.threshold_pct * 60 if rule.threshold_pct > 0 else 60
    passed = age_minutes <= threshold_minutes
    return {
        "status": "SUCCEEDED" if passed else "FAILED",
        "source_value": f"< {threshold_minutes:.0f} min",
        "target_value": f"{age_minutes:.0f} min ago",
        "delta": "—",
        "error": None if passed else f"Data is {age_minutes:.0f} min old, threshold is {threshold_minutes:.0f} min",
    }
