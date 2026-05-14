"""
UMA Platform — Snowflake Query Execution Endpoint
Used by the Workspace SQL editor. Guards against arbitrary DDL/DML by default.
"""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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
from services.snowflake_session_manager import (
    SNOWFLAKE_MFA_EXPIRED_MESSAGE,
    snowflake_session_manager,
)
from services.snowflake_connection import snowflake_auth_method, snowflake_connect_kwargs

router = APIRouter()
logger = logging.getLogger("uma.routes.snowflake")
_executor = ThreadPoolExecutor(max_workers=5)
_WORKSPACE_SESSION_TTL_MINUTES = snowflake_session_manager.ttl_minutes


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
    workspace_session_id: Optional[str] = None
    warehouse: Optional[str] = None
    database: Optional[str] = None
    schema_name: Optional[str] = None
    role: Optional[str] = None
    auth_method: Optional[str] = None
    mfa_passcode: Optional[str] = None
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


class SnowflakeDiagnosticRequest(BaseModel):
    connection_id: Optional[str] = None
    account: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    private_key: Optional[str] = None
    private_key_passphrase: Optional[str] = None
    warehouse: Optional[str] = None
    database: Optional[str] = None
    schema_name: Optional[str] = None
    role: Optional[str] = None
    auth_method: str = "password"
    mfa_passcode: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None


class SnowflakeRuntimeAuth(BaseModel):
    workspace_session_id: Optional[str] = None
    auth_method: Optional[str] = None
    mfa_passcode: Optional[str] = None


class SnowflakeWorkspaceSessionRequest(BaseModel):
    connection_id: str
    warehouse: Optional[str] = None
    database: Optional[str] = None
    schema_name: Optional[str] = None
    role: Optional[str] = None
    auth_method: Optional[str] = "password_mfa"
    mfa_passcode: Optional[str] = None


def _normalize_snowflake_account(raw: str) -> tuple[str, str]:
    if not raw:
        return "", ""
    if "snowflakecomputing.com" in raw:
        host = raw.replace("https://", "").replace("http://", "").split("/")[0]
        return host.split(".snowflakecomputing.com")[0], host
    if "-" in raw and "." not in raw:
        return raw, f"{raw}.snowflakecomputing.com"
    if "." in raw:
        return raw, f"{raw}.snowflakecomputing.com"
    return raw, f"{raw}.snowflakecomputing.com"


def _mfa_required_error(err: str) -> bool:
    lowered = (err or "").lower()
    return "mfa with totp is required" in lowered or ("mfa" in lowered and "totp" in lowered and "required" in lowered)


def _mfa_required_message() -> str:
    return "Snowflake requires MFA/TOTP. Enter a current MFA code and rerun the diagnostic."


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


def _apply_runtime_auth(cfg: dict, auth: Optional[SnowflakeRuntimeAuth]) -> dict:
    if not auth:
        return cfg
    cfg = dict(cfg)
    if auth.auth_method:
        cfg["auth_method"] = auth.auth_method
    if auth.mfa_passcode:
        cfg["mfa_passcode"] = auth.mfa_passcode
    return cfg


def _missing_runtime_mfa(cfg: dict) -> bool:
    return cfg.get("auth_method") == "password_mfa" and not cfg.get("mfa_passcode")


def _missing_mfa_response() -> dict:
    return {"items": [], "error": _mfa_required_message()}


def _quote_identifier(value: Optional[str]) -> str:
    return '"' + (value or "").replace('"', '""') + '"'


def _get_workspace_session(session_id: str, user: User, connection_id: Optional[str] = None) -> dict[str, Any]:
    entry = snowflake_session_manager.get(session_id, user_id=str(user.id), connection_id=connection_id)
    if not entry:
        raise HTTPException(401, SNOWFLAKE_MFA_EXPIRED_MESSAGE)
    return entry


async def _run_with_workspace_session(session_id: str, user: User, connection_id: str, fn):
    entry = _get_workspace_session(session_id, user, connection_id)

    def _run():
        with entry["lock"]:
            return fn(entry["connector"])

    return await _run_in_thread(_run)


@router.post("/workspace-session")
async def create_workspace_session(
    body: SnowflakeWorkspaceSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await db.get(Connection, body.connection_id)
    cfg = _resolve_sf_connection(body.connection_id, conn)
    overrides = {
        "auth_method": body.auth_method or cfg.get("auth_method") or "password",
        "mfa_passcode": body.mfa_passcode,
        "warehouse": body.warehouse,
        "database": body.database,
        "schema": body.schema_name,
        "role": body.role,
    }
    cfg = {**cfg, **{k: v for k, v in overrides.items() if v not in (None, "")}}
    if _missing_runtime_mfa(cfg):
        raise HTTPException(400, _mfa_required_message())

    def _sync_open():
        sf = SnowflakeConnector(cfg)
        try:
            sf.connect()
            metadata = sf.test_connection()
            if not metadata.get("success"):
                raise RuntimeError(metadata.get("diagnostic") or metadata.get("error") or "Snowflake session test failed")
            return sf, metadata
        except Exception:
            sf.disconnect()
            raise

    try:
        connector, metadata = await _run_in_thread(_sync_open)
    except Exception as e:
        err = str(e)
        detail = _mfa_required_message() if _mfa_required_error(err) else err
        raise HTTPException(400, detail)

    public_session = snowflake_session_manager.create(
        user_id=str(user.id),
        connection_id=body.connection_id,
        connector=connector,
        metadata=metadata,
    )

    return {
        "session_id": public_session["session_id"],
        "created_at": public_session["created_at"],
        "expires_at": public_session["expires_at"],
        "last_used_at": public_session["last_used_at"],
        "status": public_session["status"],
        "ttl_minutes": _WORKSPACE_SESSION_TTL_MINUTES,
        "metadata": public_session["metadata"],
    }


@router.delete("/workspace-session/{session_id}")
async def close_workspace_session(session_id: str, user: User = Depends(get_current_user)):
    closed = snowflake_session_manager.close(session_id, user_id=str(user.id))
    if not closed:
        raise HTTPException(403, "Snowflake workspace session does not belong to this user.")
    return {"closed": True}


@router.get("/workspace-session/status")
async def workspace_session_status(
    connection_id: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    return {
        "sessions": snowflake_session_manager.status_for_user(
            user_id=str(user.id),
            connection_id=connection_id,
        )
    }


@router.post("/workspace-session/{session_id}/heartbeat")
async def workspace_session_heartbeat(session_id: str, user: User = Depends(get_current_user)):
    status = snowflake_session_manager.heartbeat(session_id, user_id=str(user.id))
    if not status:
        raise HTTPException(401, SNOWFLAKE_MFA_EXPIRED_MESSAGE)
    return status


@router.get("/navigator/{connection_id}/databases")
async def navigator_databases(connection_id: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    if _missing_runtime_mfa(cfg):
        return _missing_mfa_response()
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_databases()}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.post("/navigator/{connection_id}/databases")
async def navigator_databases_with_auth(connection_id: str, body: SnowflakeRuntimeAuth, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.workspace_session_id:
        return await _run_with_workspace_session(
            body.workspace_session_id,
            user,
            connection_id,
            lambda sf: {"items": sf.list_databases()},
        )
    conn = await db.get(Connection, connection_id)
    cfg = _apply_runtime_auth(_resolve_sf_connection(connection_id, conn), body)
    if _missing_runtime_mfa(cfg):
        return _missing_mfa_response()
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_databases()}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.get("/navigator/{connection_id}/schemas/{database}")
async def navigator_schemas(connection_id: str, database: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    if _missing_runtime_mfa(cfg):
        return _missing_mfa_response()
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_schemas(database)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.post("/navigator/{connection_id}/schemas/{database}")
async def navigator_schemas_with_auth(connection_id: str, database: str, body: SnowflakeRuntimeAuth, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.workspace_session_id:
        return await _run_with_workspace_session(
            body.workspace_session_id,
            user,
            connection_id,
            lambda sf: {"items": sf.list_schemas(database)},
        )
    conn = await db.get(Connection, connection_id)
    cfg = _apply_runtime_auth(_resolve_sf_connection(connection_id, conn), body)
    if _missing_runtime_mfa(cfg):
        return _missing_mfa_response()
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_schemas(database)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.get("/navigator/{connection_id}/tables/{database}/{schema_name}")
async def navigator_tables(connection_id: str, database: str, schema_name: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    if _missing_runtime_mfa(cfg):
        return _missing_mfa_response()
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_tables(database, schema_name)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.post("/navigator/{connection_id}/tables/{database}/{schema_name}")
async def navigator_tables_with_auth(connection_id: str, database: str, schema_name: str, body: SnowflakeRuntimeAuth, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.workspace_session_id:
        return await _run_with_workspace_session(
            body.workspace_session_id,
            user,
            connection_id,
            lambda sf: {"items": sf.list_tables(database, schema_name)},
        )
    conn = await db.get(Connection, connection_id)
    cfg = _apply_runtime_auth(_resolve_sf_connection(connection_id, conn), body)
    if _missing_runtime_mfa(cfg):
        return _missing_mfa_response()
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"items": sf.list_tables(database, schema_name)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.get("/navigator/{connection_id}/describe/{database}/{schema_name}/{table}")
async def navigator_describe(connection_id: str, database: str, schema_name: str, table: str, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    if _missing_runtime_mfa(cfg):
        return {"columns": [], "error": _mfa_required_message()}
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"columns": sf.describe_table(database, schema_name, table)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.post("/navigator/{connection_id}/describe/{database}/{schema_name}/{table}")
async def navigator_describe_with_auth(connection_id: str, database: str, schema_name: str, table: str, body: SnowflakeRuntimeAuth, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.workspace_session_id:
        return await _run_with_workspace_session(
            body.workspace_session_id,
            user,
            connection_id,
            lambda sf: {"columns": sf.describe_table(database, schema_name, table)},
        )
    conn = await db.get(Connection, connection_id)
    cfg = _apply_runtime_auth(_resolve_sf_connection(connection_id, conn), body)
    if _missing_runtime_mfa(cfg):
        return {"columns": [], "error": _mfa_required_message()}
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return {"columns": sf.describe_table(database, schema_name, table)}
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.get("/navigator/{connection_id}/preview/{database}/{schema_name}/{table}")
async def navigator_preview(connection_id: str, database: str, schema_name: str, table: str, limit: int = 50, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(Connection, connection_id)
    cfg = _resolve_sf_connection(connection_id, conn)
    if _missing_runtime_mfa(cfg):
        return {"columns": [], "rows": [], "error": _mfa_required_message()}
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return sf.preview_table(database, schema_name, table, limit)
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.post("/navigator/{connection_id}/preview/{database}/{schema_name}/{table}")
async def navigator_preview_with_auth(connection_id: str, database: str, schema_name: str, table: str, body: SnowflakeRuntimeAuth, limit: int = 50, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.workspace_session_id:
        return await _run_with_workspace_session(
            body.workspace_session_id,
            user,
            connection_id,
            lambda sf: sf.preview_table(database, schema_name, table, limit),
        )
    conn = await db.get(Connection, connection_id)
    cfg = _apply_runtime_auth(_resolve_sf_connection(connection_id, conn), body)
    if _missing_runtime_mfa(cfg):
        return {"columns": [], "rows": [], "error": _mfa_required_message()}
    def _run():
        with SnowflakeConnector(cfg) as sf:
            return sf.preview_table(database, schema_name, table, limit)
    return await asyncio.get_event_loop().run_in_executor(_executor, _run)

@router.post("/diagnose")
async def diagnose_connection(body: SnowflakeDiagnosticRequest, _: User = Depends(get_current_user)):
    """
    Deep Snowflake connection diagnostics.
    Runs 7 checks: format → DNS → TCP → TLS → auth → role → warehouse.
    Returns structured results suitable for sharing with network/security teams.
    """
    import socket, ssl, time, re, os
    from datetime import datetime

    cfg = body.model_dump(exclude_none=True) if isinstance(body, SnowflakeDiagnosticRequest) else (body or {})
    account_raw = (cfg.get("account") or "").strip()
    checks = []

    def add(step, status, message, detail=None, duration_ms=None):
        c = {"step": step, "status": status, "message": message}
        if detail is not None:    c["detail"] = detail
        if duration_ms is not None: c["duration_ms"] = duration_ms
        checks.append(c)

    # 1. Account format
    t = time.time()
    if not account_raw:
        add("1_account_format", "fail", "Account identifier is required",
            {"hint": "Format: orgname-accountname (e.g. abcdef-xy12345) or locator.region"})
        return {"ok": False, "checks": checks, "timestamp": datetime.utcnow().isoformat()}

    normalized, hostname = _normalize_snowflake_account(account_raw)
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
    private_key = cfg.get("private_key") or (cfg.get("credentials") or {}).get("private_key", "")
    private_key_passphrase = cfg.get("private_key_passphrase") or (cfg.get("credentials") or {}).get("private_key_passphrase", "")
    role = cfg.get("role") or "PUBLIC"
    warehouse = cfg.get("warehouse", "")
    auth_method = snowflake_auth_method({**cfg, "private_key": private_key})
    mfa_passcode = cfg.get("mfa_passcode")

    if not user or (auth_method in {"key_pair", "private_key", "jwt"} and not private_key) or (auth_method not in {"key_pair", "private_key", "jwt"} and not password):
        add("5_authentication", "skip",
            "Authentication secret not provided — skipping auth check",
            {"hint": "Fill in username plus password or private key to run the full diagnostic"})
        return {"ok": True, "checks": checks, "hostname": hostname,
                "summary": "Network is healthy. Add credentials to check authentication."}

    if auth_method == "password_mfa" and not mfa_passcode:
        add("5_authentication", "fail", "MFA/TOTP passcode is required",
            {"hint": _mfa_required_message()},
            0)
        return {"ok": False, "checks": checks, "hostname": hostname}

    t = time.time()
    conn = None
    try:
        import snowflake.connector
        ca_bundle = os.getenv("SNOWFLAKE_CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")
        if ca_bundle:
            os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
            os.environ["SSL_CERT_FILE"] = ca_bundle
        connect_kwargs = snowflake_connect_kwargs(
            {
                **cfg,
                "account": normalized,
                "user": user,
                "password": password,
                "private_key": private_key,
                "private_key_passphrase": private_key_passphrase,
                "auth_method": auth_method,
                "mfa_passcode": mfa_passcode,
            },
            query_tag="UMA_DIAGNOSE",
            login_timeout=10,
            network_timeout=10,
        )
        conn = snowflake.connector.connect(**connect_kwargs)
        add("5_authentication", "ok", f"Authenticated as {user}",
            {"account": normalized},
            int((time.time()-t)*1000))
    except Exception as e:
        err = str(e)
        hint = "Check username and password."
        if _mfa_required_error(err):
            hint = _mfa_required_message()
        elif "250001" in err or "Incorrect username or password" in err:
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


@router.post("/readiness")
async def snowflake_readiness(body: SnowflakeDiagnosticRequest, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Snowflake readiness for Password and Password + MFA diagnostics.
    This endpoint only runs a tiny metadata query and never persists credentials.
    """
    import os, time

    cfg = body.model_dump(exclude_none=True) if isinstance(body, SnowflakeDiagnosticRequest) else (body or {})
    if cfg.get("connection_id"):
        conn = await db.get(Connection, cfg["connection_id"])
        if not conn or conn.type != ConnectionType.snowflake:
            return {"status": "NOT_CONFIGURED", "message": "Selected connection is not Snowflake."}
        stored = _resolve_sf_connection(cfg["connection_id"], conn)
        cfg = {**stored, **{k: v for k, v in cfg.items() if v not in (None, "")}}
    credentials = cfg.get("credentials") or {}
    account_raw = (cfg.get("account") or "").strip()
    normalized, _ = _normalize_snowflake_account(account_raw)
    user = cfg.get("user") or credentials.get("user", "")
    password = cfg.get("password") or credentials.get("password", "")
    warehouse = cfg.get("warehouse", "")
    database = cfg.get("database", "")
    schema_name = cfg.get("schema_name") or cfg.get("schema") or ""
    role = cfg.get("role") or ""
    auth_method = cfg.get("auth_method") or "password"
    mfa_passcode = cfg.get("mfa_passcode")

    if not normalized or not user:
        return {
            "status": "NOT_CONFIGURED",
            "message": "Snowflake connection not configured: account and username required.",
        }

    if auth_method == "password_mfa" and cfg.get("connection_id"):
        entry = snowflake_session_manager.get_active_session(user_id=str(_.id), connection_id=cfg["connection_id"])
        if not entry:
            return {
                "status": "WARNING",
                "message": "Snowflake MFA session expired. Unlock Snowflake and retry.",
            }
        from services.snowflake_readiness import check_snowflake_readiness_with_connector
        def _active_check():
            with entry["lock"]:
                return check_snowflake_readiness_with_connector(entry["connector"])
        return await _run_in_thread(_active_check)

    missing_runtime = not password or not warehouse or (auth_method == "password_mfa" and not mfa_passcode)
    if missing_runtime:
        return {
            "status": "NOT_CONFIGURED",
            "message": "Snowflake connection not configured or MFA session expired. Unlock Snowflake and retry.",
        }

    start = time.time()

    def _sync_check():
        import snowflake.connector

        ca_bundle = os.getenv("SNOWFLAKE_CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")
        if ca_bundle:
            os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
            os.environ["SSL_CERT_FILE"] = ca_bundle
        connect_kwargs = dict(
            account=normalized,
            user=user,
            password=password,
            warehouse=warehouse,
            database=database,
            schema=schema_name,
            role=role,
            login_timeout=10,
            network_timeout=10,
            session_parameters={"QUERY_TAG": "UMA_READINESS"},
        )
        if auth_method == "password_mfa" and mfa_passcode:
            connect_kwargs["passcode"] = mfa_passcode
        conn = snowflake.connector.connect(**{k: v for k, v in connect_kwargs.items() if v not in (None, "")})
        try:
            cur = conn.cursor()
            cur.execute("SELECT CURRENT_ACCOUNT(), CURRENT_REGION(), CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE();")
            row = cur.fetchone()
            return row
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        row = await _run_in_thread(_sync_check)
    except Exception as e:
        err = str(e)
        if _mfa_required_error(err):
            return {
                "status": "WARNING",
                "message": _mfa_required_message(),
                "duration_ms": int((time.time() - start) * 1000),
            }
        return {
            "status": "FAIL",
            "message": "Snowflake readiness check failed.",
            "error": err[:400],
            "duration_ms": int((time.time() - start) * 1000),
        }

    return {
        "status": "CONFIGURED",
        "message": "Snowflake connection configured.",
        "account": row[0] if row else None,
        "region": row[1] if row else None,
        "user": row[2] if row else None,
        "role": row[3] if row else None,
        "warehouse": row[4] if row else None,
        "duration_ms": int((time.time() - start) * 1000),
    }


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

    start = time.time()

    active_session_id = body.workspace_session_id
    if not active_session_id:
        active = snowflake_session_manager.get_active_session(user_id=str(user.id), connection_id=str(conn.id))
        if active:
            active_session_id = active["session_id"]

    if active_session_id:
        entry = _get_workspace_session(active_session_id, user, str(conn.id))

        def _sync_run():
            with entry["lock"]:
                sf = entry["connector"]
                if body.role:
                    sf.execute(f"USE ROLE {_quote_identifier(body.role)}")
                if body.warehouse:
                    sf.execute(f"USE WAREHOUSE {_quote_identifier(body.warehouse)}")
                if body.database:
                    sf.execute(f"USE DATABASE {_quote_identifier(body.database)}")
                if body.schema_name:
                    sf.execute(f"USE SCHEMA {_quote_identifier(body.schema_name)}")
                return sf.run_query(body.sql)
    else:
        # Decrypt credentials only for one-off query calls. Workspace queries should use
        # the live session opened by /workspace-session so MFA is not requested per call.
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
        if body.auth_method:
            sf_config["auth_method"] = body.auth_method
        if body.mfa_passcode:
            sf_config["mfa_passcode"] = body.mfa_passcode
        if _missing_runtime_mfa(sf_config):
            return QueryResponse(
                success=False,
                error=SNOWFLAKE_MFA_EXPIRED_MESSAGE,
                statement_type=category,
            )

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
