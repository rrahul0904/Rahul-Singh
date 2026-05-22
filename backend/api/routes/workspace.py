from __future__ import annotations

import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.snowflake import classify_sql
from connectors.snowflake_connector import SnowflakeConnector
from core.auth import get_current_user
from core.database import get_db
from core.security import get_cipher
from models import Connection, ConnectionRole, ConnectionType, User
from services.snowflake_session_manager import (
    SNOWFLAKE_MFA_EXPIRED_MESSAGE,
    snowflake_session_manager,
)

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=5)
QUERYABLE_TYPES = {ConnectionType.postgres, ConnectionType.snowflake}
SOURCE_READ_ONLY = {"read"}
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


class WorkspacePreviewRequest(BaseModel):
    database: str = ""
    schema_name: str = ""
    table: str
    limit: int = Field(default=50, ge=1, le=500)
    workspace_session_id: Optional[str] = None


class WorkspaceQueryRequest(BaseModel):
    sql: str
    database: str = ""
    schema_name: str = ""
    max_rows: int = Field(default=1000, ge=1, le=10000)
    workspace_session_id: Optional[str] = None


def _iso(value):
    return value.isoformat() + "Z" if value else None


def _role_value(conn: Connection) -> str:
    return getattr(conn.connection_role, "value", conn.connection_role or "both")


def _safe_config(conn: Connection) -> dict[str, Any]:
    credentials = get_cipher().decrypt_dict(conn.credentials) if conn.credentials else {}
    return {**(conn.config or {}), **credentials}


def _mfa_required(conn: Connection) -> bool:
    return conn.type == ConnectionType.snowflake and (conn.config or {}).get("auth_method") == "password_mfa"


def _queryable_connection_dict(conn: Connection, user: User) -> dict[str, Any]:
    role = _role_value(conn)
    active_entry = snowflake_session_manager.get_active_session(user_id=str(user.id), connection_id=conn.id, touch=False) if conn.type == ConnectionType.snowflake else None
    active = bool(active_entry)
    badges = []
    badges.append("SOURCE" if role in {"source", "both"} else "TARGET")
    badges.append(conn.type.value.upper())
    if conn.type != ConnectionType.snowflake or role == "source":
        badges.append("READ ONLY")
    if _mfa_required(conn):
        badges.append("MFA REQUIRED")
    if active:
        badges.append("SESSION ACTIVE")
    cfg = conn.config or {}
    auth_method = cfg.get("auth_method") or "password"
    return {
        "id": conn.id,
        "name": conn.name,
        "type": conn.type.value,
        "role": role,
        "badges": badges,
        "read_only": conn.type != ConnectionType.snowflake or role == "source",
        "auth_method": auth_method,
        "mfa_required": _mfa_required(conn),
        "session_active": active,
        "session": snowflake_session_manager.public(active_entry) if active_entry else None,
        "database": cfg.get("database") or cfg.get("dbname") or "",
        "schema": cfg.get("schema") or cfg.get("schema_name") or "public",
        "health": conn.health,
        "last_tested": _iso(conn.last_tested),
    }


async def _run_sync(fn):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn)


def _require_identifier(value: str, label: str) -> str:
    if not value or not IDENTIFIER_RE.match(value):
        raise HTTPException(400, f"Invalid {label}")
    return value


def _guard_read_only(sql: str) -> tuple[str, str]:
    category, verb = classify_sql(sql)
    if category not in SOURCE_READ_ONLY:
        raise HTTPException(403, "SQL Workspace is read-only for source connections. Use SELECT, SHOW, DESCRIBE, EXPLAIN, or WITH only.")
    return category, verb


def _postgres_connect(cfg: dict[str, Any]):
    import psycopg2
    return psycopg2.connect(
        host=cfg.get("host") or "localhost",
        port=int(cfg.get("port") or 5432),
        dbname=cfg.get("database") or cfg.get("dbname"),
        user=cfg.get("user") or cfg.get("username"),
        password=cfg.get("password"),
        connect_timeout=10,
    )


def _pg_fetch(conn: Connection, sql: str, params: tuple[Any, ...] = (), max_rows: int = 1000) -> dict[str, Any]:
    cfg = _safe_config(conn)
    start = time.time()
    with _postgres_connect(cfg) as pg:
        pg.set_session(readonly=True, autocommit=True)
        with pg.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            rows = cur.fetchmany(max_rows)
            cols = [desc[0] for desc in cur.description or []]
    return {
        "success": True,
        "columns": cols,
        "rows": [list(row) for row in rows],
        "row_count": len(rows),
        "execution_time_ms": int((time.time() - start) * 1000),
        "statement_type": "read",
    }


def _query_response_from_rows(rows: Any, *, execution_time_ms: int = 0, statement_type: str = "read") -> dict[str, Any]:
    if isinstance(rows, dict) and "rows" in rows and "columns" in rows:
        rows["statement_type"] = rows.get("statement_type") or statement_type
        return rows
    if not rows:
        return {
            "success": True,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": execution_time_ms,
            "statement_type": statement_type,
        }
    if isinstance(rows[0], dict):
        columns = list(rows[0].keys())
        values = [[row.get(col) for col in columns] for row in rows]
    else:
        columns = [f"column_{idx + 1}" for idx in range(len(rows[0]))]
        values = [list(row) for row in rows]
    return {
        "success": True,
        "columns": columns,
        "rows": values,
        "row_count": len(values),
        "execution_time_ms": execution_time_ms,
        "statement_type": statement_type,
    }


def _sf_entry(conn: Connection, user: User, session_id: Optional[str]):
    if session_id:
        entry = snowflake_session_manager.get(session_id, user_id=str(user.id), connection_id=conn.id)
    else:
        entry = snowflake_session_manager.get_active_session(user_id=str(user.id), connection_id=conn.id)
    if entry:
        return entry
    if _mfa_required(conn):
        raise HTTPException(401, SNOWFLAKE_MFA_EXPIRED_MESSAGE)
    cfg = _safe_config(conn)
    sf = SnowflakeConnector({**cfg, "client_session_keep_alive": True})
    sf.connect()
    return snowflake_session_manager.create(user_id=str(user.id), connection_id=conn.id, connector=sf, metadata={"temporary": True, "auth_method": cfg.get("auth_method", "password")})


async def _with_snowflake(conn: Connection, user: User, session_id: Optional[str], fn):
    entry = _sf_entry(conn, user, session_id)
    if "connector" not in entry:
        entry = snowflake_session_manager.get(entry["session_id"], user_id=str(user.id), connection_id=conn.id)
    def _run():
        with entry["lock"]:
            return fn(entry["connector"])
    return await _run_sync(_run)


@router.get("/connections")
async def workspace_connections(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = list((await db.execute(select(Connection).order_by(Connection.created_at.desc()))).scalars().all())
    return [_queryable_connection_dict(row, user) for row in rows if row.type in QUERYABLE_TYPES]


@router.get("/{connection_id}/databases")
async def list_databases(connection_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    if not conn or conn.type not in QUERYABLE_TYPES:
        raise HTTPException(404, "Queryable connection not found")
    if conn.type == ConnectionType.postgres:
        cfg = conn.config or {}
        return {"items": [cfg.get("database") or cfg.get("dbname") or "postgres"]}
    return await _with_snowflake(conn, user, None, lambda sf: {"items": sf.list_databases()})


@router.get("/{connection_id}/schemas")
async def list_schemas(connection_id: str, database: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    if not conn or conn.type not in QUERYABLE_TYPES:
        raise HTTPException(404, "Queryable connection not found")
    if conn.type == ConnectionType.postgres:
        result = await _run_sync(lambda: _pg_fetch(conn, "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg_%' AND schema_name <> 'information_schema' ORDER BY schema_name", max_rows=500))
        return {"items": [row[0] for row in result["rows"]]}
    return await _with_snowflake(conn, user, None, lambda sf: {"items": sf.list_schemas(database)})


@router.get("/{connection_id}/tables")
async def list_tables(connection_id: str, database: str = "", schema_name: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    if not conn or conn.type not in QUERYABLE_TYPES:
        raise HTTPException(404, "Queryable connection not found")
    schema = schema_name or (conn.config or {}).get("schema") or "public"
    if conn.type == ConnectionType.postgres:
        result = await _run_sync(lambda: _pg_fetch(conn, "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name", (schema,), max_rows=1000))
        return {"items": [row[0] for row in result["rows"]]}
    return await _with_snowflake(conn, user, None, lambda sf: {"items": sf.list_tables(database, schema)})


@router.get("/{connection_id}/tables/{table}/columns")
async def table_columns(connection_id: str, table: str, database: str = "", schema_name: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    if not conn or conn.type not in QUERYABLE_TYPES:
        raise HTTPException(404, "Queryable connection not found")
    schema = schema_name or (conn.config or {}).get("schema") or "public"
    if conn.type == ConnectionType.postgres:
        result = await _run_sync(lambda: _pg_fetch(conn, "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (schema, table), max_rows=1000))
        return {"columns": [{"name": row[0], "type": row[1]} for row in result["rows"]]}
    return await _with_snowflake(conn, user, None, lambda sf: {"columns": [{"name": c.get("name") or c.get("COLUMN_NAME"), "type": c.get("type") or c.get("DATA_TYPE")} for c in sf.describe_table(database, schema, table)]})


@router.post("/{connection_id}/preview")
async def preview_table(connection_id: str, body: WorkspacePreviewRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    if not conn or conn.type not in QUERYABLE_TYPES:
        raise HTTPException(404, "Queryable connection not found")
    schema = body.schema_name or (conn.config or {}).get("schema") or "public"
    table = _require_identifier(body.table, "table")
    if conn.type == ConnectionType.postgres:
        schema = _require_identifier(schema, "schema")
        return await _run_sync(lambda: _pg_fetch(conn, f'SELECT * FROM "{schema}"."{table}" LIMIT %s', (body.limit,), max_rows=body.limit))
    return await _with_snowflake(conn, user, body.workspace_session_id, lambda sf: sf.preview_table(body.database, schema, table, body.limit))


@router.post("/{connection_id}/query")
async def run_query(connection_id: str, body: WorkspaceQueryRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    if not conn or conn.type not in QUERYABLE_TYPES:
        raise HTTPException(404, "Queryable connection not found")
    category, verb = _guard_read_only(body.sql)
    if conn.type == ConnectionType.postgres:
        result = await _run_sync(lambda: _pg_fetch(conn, body.sql, max_rows=body.max_rows))
        result["statement_type"] = verb
        return result

    def _run(sf: SnowflakeConnector):
        if body.database:
            sf.execute(f'USE DATABASE "{body.database.replace(chr(34), chr(34) + chr(34))}"')
        if body.schema_name:
            sf.execute(f'USE SCHEMA "{body.schema_name.replace(chr(34), chr(34) + chr(34))}"')
        return sf.run_query(body.sql)

    start = time.time()
    rows = await _with_snowflake(conn, user, body.workspace_session_id, _run)
    return _query_response_from_rows(
        rows,
        execution_time_ms=int((time.time() - start) * 1000),
        statement_type=verb or category,
    )
