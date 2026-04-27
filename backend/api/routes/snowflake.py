"""
UMA Platform — Snowflake Query Execution Endpoint
Used by the Workspace SQL editor. Guards against arbitrary DDL/DML by default.
"""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_editor
from core.audit import record as audit_record, AuditAction, extract_request_context
from core.database import get_db
from core.security import get_cipher
from connectors.snowflake_connector import SnowflakeConnector
from models import Connection, ConnectionType, User, UserRole

router = APIRouter()
logger = logging.getLogger("uma.routes.snowflake")
_executor = ThreadPoolExecutor(max_workers=5)


# ═══ SQL statement guard ══════════════════════════════════════
# By default, only read-only statements are allowed. Editors+ can opt in to writes.

READ_ONLY_VERBS = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}

# Forbidden even for editors unless explicitly flagged
DANGEROUS_PATTERNS = [
    r"\bDROP\s+DATABASE\b",
    r"\bDROP\s+SCHEMA\b",
    r"\bTRUNCATE\s+TABLE\b",
    r"\bDELETE\s+FROM\b.*\bWHERE\s+1\s*=\s*1\b",
    r"\bGRANT\s+.+\s+ON\s+ACCOUNT\b",
    r"\bREVOKE\s+.+\s+ON\s+ACCOUNT\b",
    r"\bCREATE\s+ROLE\b",
    r"\bDROP\s+ROLE\b",
    r"\bALTER\s+USER\b",
    r"\bCREATE\s+USER\b",
]


def classify_sql(sql: str) -> tuple[str, str]:
    """
    Returns (category, first_verb). Category is 'read' | 'write' | 'dangerous' | 'invalid'.
    """
    # Strip comments and get first meaningful token
    cleaned = re.sub(r"--[^\n]*", "", sql)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()

    if not cleaned:
        return "invalid", ""

    first_word = cleaned.split(None, 1)[0].upper() if cleaned else ""

    # Check dangerous patterns first
    upper = cleaned.upper()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, upper):
            return "dangerous", first_word

    if first_word in READ_ONLY_VERBS:
        return "read", first_word
    return "write", first_word


# ═══ Models ═══════════════════════════════════════════════════

class QueryRequest(BaseModel):
    sql: str
    connection_id: Optional[str] = None
    warehouse: Optional[str] = None
    database: Optional[str] = None
    schema_name: Optional[str] = None
    role: Optional[str] = None
    max_rows: int = 1000
    allow_writes: bool = False

    @field_validator("sql")
    @classmethod
    def validate_sql(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError("SQL statement is empty")
        if len(v) > 100_000:
            raise ValueError("SQL statement too large (max 100KB)")
        # Block multiple statements unless explicitly allowed
        # Simple check: semicolons not inside quotes. Imperfect but catches common cases.
        stripped = v.strip().rstrip(";")
        if ";" in stripped:
            # Count semicolons that aren't inside strings
            in_string = False
            quote_char = None
            for c in stripped:
                if c in ("'", '"') and not in_string:
                    in_string = True; quote_char = c
                elif c == quote_char and in_string:
                    in_string = False; quote_char = None
                elif c == ";" and not in_string:
                    raise ValueError("Multiple SQL statements not allowed")
        return v

    @field_validator("max_rows")
    @classmethod
    def cap_rows(cls, v):
        if v < 1:
            return 100
        return min(v, 10_000)


class QueryResponse(BaseModel):
    success: bool
    columns: List[str] = []
    rows: List[List[Any]] = []
    row_count: int = 0
    execution_time_ms: int = 0
    error: Optional[str] = None
    statement_type: Optional[str] = None


async def _run_in_thread(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)


# ═══ Routes ═══════════════════════════════════════════════════


def _resolve_sf_connection(connection_id: Optional[str], db_conn: Optional[Connection], connection_payload: Optional[dict] = None) -> dict:
    if connection_payload:
        return connection_payload
    if not db_conn:
        raise HTTPException(404, "Snowflake connection not found")
    cipher = get_cipher()
    credentials = cipher.decrypt_dict(db_conn.credentials) if db_conn.credentials else {}
    cfg = {**db_conn.config, **credentials}
    if db_conn.type != ConnectionType.snowflake:
        raise HTTPException(400, "Selected connection is not Snowflake")
    return cfg

@router.get("/navigator/{connection_id}/databases")
async def navigator_databases(connection_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_databases()}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.get("/navigator/{connection_id}/schemas/{database}")
async def navigator_schemas(connection_id: str, database: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_schemas(database)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.get("/navigator/{connection_id}/tables/{database}/{schema_name}")
async def navigator_tables(connection_id: str, database: str, schema_name: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_tables(database, schema_name)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.get("/navigator/{connection_id}/describe/{database}/{schema_name}/{table}")
async def navigator_describe(connection_id: str, database: str, schema_name: str, table: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"columns": sf.describe_table(database, schema_name, table)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.get("/navigator/{connection_id}/preview/{database}/{schema_name}/{table}")
async def navigator_preview(connection_id: str, database: str, schema_name: str, table: str, limit: int = 50, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return sf.preview_table(database, schema_name, table, limit)
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.post("/diagnose")
async def diagnose_connection(body: dict, _: User = Depends(get_current_user)):
    """
    Deep Snowflake connection diagnostics.
    Runs 7 checks: format → DNS → TCP → TLS → auth → role → warehouse.
    Returns structured results suitable for sharing with network/security teams.
    """
    import socket, ssl, time, re, os
    from datetime import datetime

    cfg = body or {}
    account_raw = (cfg.get("account") or "").strip()
    checks = []

    def add(step, status, message, detail=None, duration_ms=None):
        c = {"step": step, "status": status, "message": message}
        if detail is not None:    c["detail"] = detail
        if duration_ms is not None: c["duration_ms"] = duration_ms
        checks.append(c)

    def normalize_account(raw: str):
        if not raw: return "", ""
        if "snowflakecomputing.com" in raw:
            host = raw.replace("https://", "").replace("http://", "").split("/")[0]
            return host.split(".snowflakecomputing.com")[0], host
        if "-" in raw and "." not in raw:
            return raw, f"{raw}.snowflakecomputing.com"
        if "." in raw:
            return raw, f"{raw}.snowflakecomputing.com"
        return raw, f"{raw}.snowflakecomputing.com"

    # 1. Account format
    t = time.time()
    if not account_raw:
        add("1_account_format", "fail", "Account identifier is required",
            {"hint": "Format: orgname-accountname (e.g. abcdef-xy12345) or locator.region"})
        return {"ok": False, "checks": checks, "timestamp": datetime.utcnow().isoformat()}

    normalized, hostname = normalize_account(account_raw)
    if "snowflakecomputing.com" in account_raw:
        add("1_account_format", "warn",
            "Full hostname provided — the API prefers 'orgname-accountname'",
            {"provided": account_raw, "normalized": normalized, "hostname": hostname},
            int((time.time()-t)*1000))
    else:
        add("1_account_format", "ok", f"Identifier looks valid: {normalized}",
            {"normalized": normalized, "hostname": hostname},
            int((time.time()-t)*1000))

    # 2. DNS
    t = time.time()
    resolved_ip = None
    try:
        resolved_ip = socket.gethostbyname(hostname)
        add("2_dns_resolution", "ok", f"Resolved {hostname} to {resolved_ip}",
            {"host": hostname, "ip": resolved_ip},
            int((time.time()-t)*1000))
    except socket.gaierror as e:
        add("2_dns_resolution", "fail", f"Cannot resolve {hostname}",
            {"host": hostname, "error": str(e),
             "hint": "DNS can't find this account. Check account identifier spelling."},
            int((time.time()-t)*1000))
        return {"ok": False, "checks": checks, "hostname": hostname}

    # 3. TCP
    t = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((hostname, 443))
        sock.close()
        add("3_tcp_connectivity", "ok", "TCP port 443 reachable",
            {"host": hostname, "port": 443, "ip": resolved_ip},
            int((time.time()-t)*1000))
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        add("3_tcp_connectivity", "fail", f"Cannot connect to {hostname}:443",
            {"error": str(e),
             "hint": "Blocked by corporate firewall or proxy. Share this diagnostic with your network team."},
            int((time.time()-t)*1000))
        return {"ok": False, "checks": checks, "hostname": hostname}

    # 4. TLS
    t = time.time()
    try:
        insecure_mode = os.getenv("SNOWFLAKE_INSECURE_MODE", "false").lower() == "true"
        ca_bundle = os.getenv("SNOWFLAKE_CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE")
        ctx = ssl._create_unverified_context() if insecure_mode else ssl.create_default_context(cafile=ca_bundle if ca_bundle else None)
        sock = socket.create_connection((hostname, 443), timeout=5)
        ss = ctx.wrap_socket(sock, server_hostname=hostname)
        cert = ss.getpeercert()
        ss.close()
        issuer = dict(x[0] for x in cert.get("issuer", []))
        add("4_tls_handshake", "ok",
            f"TLS handshake succeeded (issuer: {issuer.get('organizationName', 'unknown')})",
            {"tls_version": ss.version() if hasattr(ss, "version") else "unknown",
             "issuer": issuer.get("organizationName", "unknown")},
            int((time.time()-t)*1000))
    except ssl.SSLError as e:
        add("4_tls_handshake", "fail", "TLS handshake failed",
            {"error": str(e),
             "hint": "Snowflake TLS certificate validation failed. Install ca-certificates, set SNOWFLAKE_CA_BUNDLE or REQUESTS_CA_BUNDLE to your corporate CA bundle, or use SNOWFLAKE_INSECURE_MODE=true only for local dev."},
            int((time.time()-t)*1000))
        return {"ok": False, "checks": checks, "hostname": hostname}
    except Exception as e:
        add("4_tls_handshake", "warn", f"TLS check inconclusive: {type(e).__name__}",
            {"error": str(e)},
            int((time.time()-t)*1000))

    # 5. Auth
    user = cfg.get("user") or (cfg.get("credentials") or {}).get("user", "")
    password = cfg.get("password") or (cfg.get("credentials") or {}).get("password", "")
    role = cfg.get("role") or "PUBLIC"
    warehouse = cfg.get("warehouse", "")

    if not user or not password:
        add("5_authentication", "skip",
            "Username/password not provided — skipping auth check",
            {"hint": "Fill in username and password to run the full diagnostic"})
        return {"ok": True, "checks": checks, "hostname": hostname,
                "summary": "Network is healthy. Add credentials to check authentication."}

    t = time.time()
    conn = None
    try:
        import snowflake.connector
        conn = snowflake.connector.connect(
            account=normalized, user=user, password=password,
            login_timeout=10, network_timeout=10,
            session_parameters={"QUERY_TAG": "UMA_DIAGNOSE"},
        )
        add("5_authentication", "ok", f"Authenticated as {user}",
            {"account": normalized},
            int((time.time()-t)*1000))
    except Exception as e:
        err = str(e)
        hint = "Check username and password."
        if "250001" in err or "Incorrect username or password" in err:
            hint = "Wrong credentials. Password might have expired, or user might be locked."
        elif "Not authorized" in err:
            hint = "User exists but isn't authorized for this account."
        elif "User" in err and "does not exist" in err:
            hint = "User does not exist in this Snowflake account."
        elif "password has expired" in err.lower():
            hint = "Password expired. Have user log in via Snowsight to reset."
        add("5_authentication", "fail", "Authentication failed",
            {"error": err[:400], "hint": hint},
            int((time.time()-t)*1000))
        return {"ok": False, "checks": checks, "hostname": hostname}

    # 6. Role
    t = time.time()
    try:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {role}")
        cur.execute("SELECT CURRENT_ROLE()")
        actual_role = cur.fetchone()[0]
        add("6_role_access", "ok", f"Role '{actual_role}' is accessible",
            {"requested": role, "active": actual_role},
            int((time.time()-t)*1000))
    except Exception as e:
        add("6_role_access", "warn", f"Cannot use role {role}",
            {"error": str(e)[:300],
             "hint": f"User doesn't have {role}. Grant it or use a different role."},
            int((time.time()-t)*1000))

    # 7. Warehouse
    if warehouse:
        t = time.time()
        try:
            cur = conn.cursor()
            cur.execute(f"USE WAREHOUSE {warehouse}")
            cur.execute("SELECT CURRENT_WAREHOUSE(), CURRENT_WAREHOUSE_STATE()")
            row = cur.fetchone()
            add("7_warehouse_access", "ok",
                f"Warehouse '{row[0]}' ready (state: {row[1]})",
                {"warehouse": row[0], "state": row[1]},
                int((time.time()-t)*1000))
        except Exception as e:
            add("7_warehouse_access", "warn",
                f"Cannot access warehouse {warehouse}",
                {"error": str(e)[:300],
                 "hint": f"USAGE privilege on {warehouse} is required. Grant: GRANT USAGE ON WAREHOUSE {warehouse} TO ROLE {role};"},
                int((time.time()-t)*1000))
    else:
        add("7_warehouse_access", "skip", "No warehouse specified — skipping", None)

    try: conn.close()
    except Exception: pass

    has_fails = any(c["status"] == "fail" for c in checks)
    has_warns = any(c["status"] == "warn" for c in checks)

    summary = "All checks passed — connection is fully ready."
    if has_fails:
        summary = "One or more critical checks failed. Share this report with your network or Snowflake admin."
    elif has_warns:
        summary = "Connection works but has warnings. Review role/warehouse permissions."

    return {
        "ok": not has_fails, "checks": checks, "hostname": hostname,
        "account_normalized": normalized, "summary": summary,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/diagnose/download")
async def diagnose_download(body: dict, user: User = Depends(get_current_user)):
    """Returns the diagnostic as a downloadable JSON report."""
    result = await diagnose_connection(body, user)
    result["generated_by"] = user.email
    from fastapi.responses import Response
    import json as _json
    payload = _json.dumps(result, indent=2, default=str)
    filename = f"uma-snowflake-diagnostic-{result.get('account_normalized', 'unknown')}.json"
    return Response(
        content=payload, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/query", response_model=QueryResponse)
async def run_query(
    body: QueryRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute SQL against Snowflake. Reads by default; writes require editor+ role."""
    import time

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}

    # Classify the SQL
    category, verb = classify_sql(body.sql)

    if category == "invalid":
        raise HTTPException(400, "SQL statement is invalid or empty")

    if category == "dangerous":
        await audit_record(
            action=AuditAction.SNOWFLAKE_QUERY, status="denied",
            user_id=user.id, user_email=user.email,
            details={"verb": verb, "reason": "dangerous_pattern"}, **ctx,
        )
        raise HTTPException(403, f"Statement '{verb}' is not permitted (dangerous pattern detected)")

    if category == "write":
        if not body.allow_writes:
            raise HTTPException(
                400,
                f"Statement '{verb}' is a write operation. "
                "Set allow_writes=true in the request to proceed."
            )
        if user.role not in (UserRole.admin, UserRole.editor):
            await audit_record(
                action=AuditAction.SNOWFLAKE_QUERY, status="denied",
                user_id=user.id, user_email=user.email,
                details={"verb": verb, "reason": "insufficient_role"}, **ctx,
            )
            raise HTTPException(403, "Write operations require admin or editor role")

    # Find Snowflake connection
    if body.connection_id:
        conn = await db.get(Connection, body.connection_id)
    else:
        r = await db.execute(
            select(Connection).where(Connection.type == ConnectionType.snowflake).limit(1)
        )
        conn = r.scalar_one_or_none()

    if not conn:
        raise HTTPException(404, "No Snowflake connection configured. Add one in Connections.")

    # Decrypt credentials
    cipher = get_cipher()
    credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}

    sf_config = {
        "account":   conn.config.get("account", ""),
        "user":      credentials.get("user") or conn.config.get("user", ""),
        "password":  credentials.get("password", ""),
        "warehouse": body.warehouse or conn.config.get("warehouse", "COMPUTE_WH"),
        "database":  body.database  or conn.config.get("database", ""),
        "schema":    body.schema_name or conn.config.get("schema", "PUBLIC"),
        "role":      body.role or conn.config.get("role", "SYSADMIN"),
    }

    start = time.time()

    def _sync_run():
        with SnowflakeConnector(sf_config) as sf:
            return sf.run_query(body.sql)

    try:
        rows = await _run_in_thread(_sync_run)
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        logger.error(f"Snowflake query failed: {e}")
        await audit_record(
            action=AuditAction.SNOWFLAKE_QUERY, status="failure",
            user_id=user.id, user_email=user.email,
            details={"verb": verb, "category": category,
                     "connection": conn.name, "duration_ms": duration},
            error=str(e)[:500], **ctx,
        )
        return QueryResponse(success=False, error=str(e),
                             execution_time_ms=duration,
                             statement_type=category)

    duration_ms = int((time.time() - start) * 1000)

    await audit_record(
        action=AuditAction.SNOWFLAKE_QUERY, status="success",
        user_id=user.id, user_email=user.email,
        resource=f"connection:{conn.id}",
        details={
            "verb": verb, "category": category,
            "connection": conn.name, "row_count": len(rows),
            "duration_ms": duration_ms,
        }, **ctx,
    )

    if not rows:
        return QueryResponse(success=True, columns=[], rows=[], row_count=0,
                             execution_time_ms=duration_ms, statement_type=category)

    columns = list(rows[0].keys())
    rows_limited = rows[:body.max_rows]
    row_arrays = [[_safe_value(r.get(c)) for c in columns] for r in rows_limited]

    return QueryResponse(
        success=True,
        columns=columns,
        rows=row_arrays,
        row_count=len(rows),
        execution_time_ms=duration_ms,
        statement_type=category,
    )


def _safe_value(v):
    import datetime, decimal
    if v is None: return None
    if isinstance(v, (str, int, float, bool)): return v
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal): return float(v)
    if isinstance(v, bytes): return v.decode("utf-8", errors="replace")
    return str(v)


@router.get("/databases")
async def list_databases(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Connection).where(Connection.type == ConnectionType.snowflake).limit(1))
    conn = r.scalar_one_or_none()
    if not conn:
        return {"databases": []}

    cipher = get_cipher()
    credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}

    sf_config = {
        "account":   conn.config.get("account", ""),
        "user":      credentials.get("user", "") or conn.config.get("user", ""),
        "password":  credentials.get("password", ""),
        "warehouse": conn.config.get("warehouse", "COMPUTE_WH"),
        "role":      conn.config.get("role", "SYSADMIN"),
    }

    def _sync():
        with SnowflakeConnector(sf_config) as sf:
            return sf.run_query("SHOW DATABASES")
    try:
        rows = await _run_in_thread(_sync)
        return {"databases": [r.get("name") for r in rows]}
    except Exception as e:
        return {"databases": [], "error": str(e)}


@router.get("/schemas/{database}")
async def list_schemas(
    database: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate database name — prevent injection via path param
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", database):
        raise HTTPException(400, "Invalid database name")

    r = await db.execute(
        select(Connection).where(Connection.type == ConnectionType.snowflake).limit(1))
    conn = r.scalar_one_or_none()
    if not conn:
        return {"schemas": []}

    cipher = get_cipher()
    credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}

    sf_config = {
        "account":   conn.config.get("account", ""),
        "user":      credentials.get("user", "") or conn.config.get("user", ""),
        "password":  credentials.get("password", ""),
        "warehouse": conn.config.get("warehouse", "COMPUTE_WH"),
        "database":  database,
        "role":      conn.config.get("role", "SYSADMIN"),
    }

    def _sync():
        with SnowflakeConnector(sf_config) as sf:
            return sf.run_query(f"SHOW SCHEMAS IN DATABASE {database}")
    try:
        rows = await _run_in_thread(_sync)
        return {"schemas": [r.get("name") for r in rows]}
    except Exception as e:
        return {"schemas": [], "error": str(e)}
