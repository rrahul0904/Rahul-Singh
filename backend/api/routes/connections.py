"""
UMA Platform — Connections Route (Hardened)
Encrypted credentials at rest, auth, audit logging.
"""

import asyncio
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_editor
from core.audit import record as audit_record, AuditAction, extract_request_context
from core.database import get_db
from core.security import get_cipher, mask_secret
from models import Connection, ConnectionRole, ConnectionType, User
from services.snowflake_connection import normalize_snowflake_config, snowflake_execution_readiness

router = APIRouter()
logger = logging.getLogger("uma.routes.connections")
_pool = ThreadPoolExecutor(max_workers=4)
EPHEMERAL_CREDENTIAL_FIELDS = {"mfa_passcode", "passcode", "totp", "totp_passcode"}

def _capabilities(
    *,
    connection_test: bool,
    metadata_discovery: bool,
    full_load: bool,
    incremental_sync: bool,
    cdc: bool,
    sql_conversion: bool,
    validation: bool,
) -> dict[str, bool]:
    return {
        "connection_test": connection_test,
        "metadata_discovery": metadata_discovery,
        "full_load": full_load,
        "incremental_sync": incremental_sync,
        "cdc": cdc,
        "sql_conversion": sql_conversion,
        "validation": validation,
    }


CONNECTOR_REGISTRY = [
    {
        "key": "postgres",
        "display_name": "PostgreSQL",
        "status": "GOLDEN_PATH",
        "source": True,
        "target": False,
        "capabilities": _capabilities(connection_test=True, metadata_discovery=True, full_load=True, incremental_sync=True, cdc=False, sql_conversion=True, validation=True),
        "known_limitations": ["CDC is cursor/incremental only unless log-based CDC is configured externally.", "Full-load cutover remains validation-gated."],
    },
    {
        "key": "snowflake",
        "display_name": "Snowflake",
        "status": "GOLDEN_PATH",
        "source": True,
        "target": True,
        "capabilities": _capabilities(connection_test=True, metadata_discovery=True, full_load=True, incremental_sync=True, cdc=False, sql_conversion=False, validation=True),
        "known_limitations": ["Target execution is guarded by role, safety mode, and workspace confirmation.", "True CDC is not claimed for Snowflake targets."],
    },
    {
        "key": "mysql",
        "display_name": "MySQL",
        "status": "BETA",
        "source": True,
        "target": False,
        "capabilities": _capabilities(connection_test=True, metadata_discovery=True, full_load=True, incremental_sync=True, cdc=False, sql_conversion=True, validation=True),
        "known_limitations": ["Incremental sync depends on a stable watermark or primary key.", "No log-based CDC in this local prototype."],
    },
    {
        "key": "redshift",
        "display_name": "Redshift",
        "status": "BETA",
        "source": True,
        "target": False,
        "capabilities": _capabilities(connection_test=True, metadata_discovery=True, full_load=True, incremental_sync=True, cdc=False, sql_conversion=True, validation=True),
        "known_limitations": ["Distribution and sort-key tuning requires review.", "CDC is not implemented."],
    },
    {
        "key": "bigquery",
        "display_name": "BigQuery",
        "status": "PREVIEW",
        "source": True,
        "target": False,
        "capabilities": _capabilities(connection_test=True, metadata_discovery=True, full_load=True, incremental_sync=False, cdc=False, sql_conversion=True, validation=True),
        "known_limitations": ["Nested/repeated fields require VARIANT or flattening review.", "Incremental sync is not proven end to end."],
    },
    *[
        {
            "key": key,
            "display_name": display,
            "status": "PREVIEW",
            "source": True,
            "target": False,
            "capabilities": _capabilities(connection_test=True, metadata_discovery=True, full_load=False, incremental_sync=False, cdc=False, sql_conversion=True, validation=False),
            "known_limitations": ["Migration execution is not yet proven end to end for this connector.", "Use for discovery and conversion analysis only."],
        }
        for key, display in [
            ("sqlserver", "SQL Server"),
            ("oracle", "Oracle"),
            ("teradata", "Teradata"),
            ("synapse", "Synapse"),
        ]
    ],
    *[
        {
            "key": key,
            "display_name": display,
            "status": "CONNECTOR_ONLY",
            "source": True,
            "target": target,
            "capabilities": _capabilities(connection_test=True, metadata_discovery=True, full_load=False, incremental_sync=False, cdc=False, sql_conversion=False, validation=False),
            "known_limitations": ["Connector is available for connectivity or file/object discovery.", "No production-grade migration execution path is claimed."],
        }
        for key, display, target in [
            ("salesforce", "Salesforce", False),
            ("zendesk", "Zendesk", False),
            ("hubspot", "HubSpot", False),
            ("stripe", "Stripe", False),
            ("jira", "Jira", False),
            ("s3", "Amazon S3", True),
            ("adls", "ADLS Gen2", True),
            ("gcs", "GCS", True),
            ("sftp", "SFTP", False),
            ("flatfile", "Flat Files", False),
            ("kafka", "Kafka", False),
            ("kinesis", "Kinesis", False),
            ("rest", "REST/GraphQL", False),
        ]
    ],
    *[
        {
            "key": key,
            "display_name": display,
            "status": "COMING_SOON",
            "source": True,
            "target": False,
            "capabilities": _capabilities(connection_test=False, metadata_discovery=False, full_load=False, incremental_sync=False, cdc=False, sql_conversion=False, validation=False),
            "known_limitations": ["Not implemented in the local pilot build."],
        }
        for key, display in [
            ("netsuite", "NetSuite"),
            ("workday", "Workday"),
            ("ga4", "Google Analytics"),
        ]
    ],
]


class ConnectionCreate(BaseModel):
    name: str
    type: str
    connection_role: str = "both"
    description: Optional[str] = ""
    credentials: Dict[str, Any] = {}
    config: Dict[str, Any] = {}
    auth_method: Optional[str] = None
    mfa_passcode: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("Name must be 1-255 characters")
        return v

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        try:
            ConnectionType(v)
        except ValueError:
            raise ValueError(f"Unknown connection type: {v}")
        return v

    @field_validator("connection_role")
    @classmethod
    def validate_connection_role(cls, v):
        try:
            ConnectionRole(v)
        except ValueError:
            raise ValueError("connection_role must be source, target, or both")
        return v


class ConnectionUpdate(BaseModel):
    name:        Optional[str] = None
    connection_role: Optional[str] = None
    description: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None
    config:      Optional[Dict[str, Any]] = None
    auth_method: Optional[str] = None
    mfa_passcode: Optional[str] = None


class ConnectionTestRequest(BaseModel):
    auth_method: Optional[str] = None
    mfa_passcode: Optional[str] = None


def _strip_ephemeral_credentials(values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not values:
        return {}
    return {k: v for k, v in values.items() if k not in EPHEMERAL_CREDENTIAL_FIELDS}


def _mfa_required_error(err: str) -> bool:
    lowered = (err or "").lower()
    return "mfa with totp is required" in lowered or ("mfa" in lowered and "totp" in lowered and "required" in lowered)


def _mfa_required_message() -> str:
    return "Snowflake requires MFA/TOTP. Enter a current MFA code and rerun the diagnostic."


def _safe_conn(conn: Connection) -> dict:
    """Never return raw credentials. Show masked hints only."""
    cipher = get_cipher()
    credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}
    cfg = conn.config or {}
    if conn.type == ConnectionType.snowflake:
        cfg = normalize_snowflake_config(cfg)
        credentials = normalize_snowflake_config(credentials)
    username = credentials.get("user") or credentials.get("username") or cfg.get("user") or cfg.get("username") or ""
    database = cfg.get("database") or cfg.get("dbname") or ""
    schema = cfg.get("schema") or cfg.get("schema_name") or ""
    host = cfg.get("host") or cfg.get("hostname") or ""
    port = cfg.get("port") or ""
    safe_details = {
        "connection_name": conn.name,
        "type": conn.type.value,
        "host": host,
        "port": port,
        "database": database,
        "schema": schema,
        "username": username,
        "password_hidden": bool(credentials.get("password")),
        "private_key_hidden": bool(credentials.get("private_key") or credentials.get("private_key_pem")),
        "auth_method": cfg.get("auth_method") or ("key_pair" if credentials.get("private_key") or credentials.get("private_key_pem") else "password"),
        "docker_service": cfg.get("docker_service", ""),
        "docker_container": cfg.get("docker_container", ""),
        "number_of_tables": cfg.get("table_count"),
        "estimated_size": cfg.get("estimated_size") or cfg.get("estimated_size_gb"),
        "health_status": conn.health,
        "safe_copy_command": (
            f"psql -h {host} -p {port} -U <username> -d {database}"
            if conn.type == ConnectionType.postgres and database and host and port else ""
        ),
    }

    # Build a masked preview of credentials (e.g. "user: ab*****", "password: ****")
    credentials_masked = {}
    for k, v in credentials.items():
        if isinstance(v, str) and v:
            if k.lower() in ("user", "username", "email", "client_id", "account_id", "iam_role"):
                credentials_masked[k] = mask_secret(v, visible=4) if len(v) > 8 else "[set]"
            else:
                credentials_masked[k] = "[set]"
        else:
            credentials_masked[k] = "[empty]"

    return {
        "id":              conn.id,
        "name":            conn.name,
        "type":            conn.type.value,
        "connection_role": getattr(conn.connection_role, "value", conn.connection_role or "both"),
        "description":     conn.description,
        "config":          conn.config,
        "credentials":     credentials_masked,
        "safe_details":    safe_details,
        "execution_readiness": (
            snowflake_execution_readiness({**cfg, **credentials})
            if conn.type == ConnectionType.snowflake
            else None
        ),
        "health":          conn.health,
        "last_tested":     conn.last_tested.isoformat() if conn.last_tested else None,
        "created_at":      conn.created_at.isoformat(),
        "updated_at":      conn.updated_at.isoformat() if conn.updated_at else None,
    }


# ─── Routes ───────────────────────────────────────────────────

@router.get("")
async def list_connections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Connection).order_by(Connection.created_at.desc()))
    return [_safe_conn(c) for c in result.scalars()]


@router.get("/registry-status")
async def get_registry_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Connection))
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"configured_count": 0, "source_count": 0, "target_count": 0})

    for conn in result.scalars():
        key = conn.type.value
        role = getattr(conn.connection_role, "value", conn.connection_role or "both")
        counts[key]["configured_count"] += 1
        if role in ("source", "both"):
            counts[key]["source_count"] += 1
        if role in ("target", "both"):
            counts[key]["target_count"] += 1

    return [
        {
            "connector_key": item["key"],
            "display_name": item["display_name"],
            "status": item["status"],
            "maturity": item["status"],
            "capabilities": item.get("capabilities", {}),
            "known_limitations": item.get("known_limitations", []),
            "configured_count": counts[item["key"]]["configured_count"],
            "source_count": counts[item["key"]]["source_count"],
            "target_count": counts[item["key"]]["target_count"],
            "has_configured_connection": counts[item["key"]]["configured_count"] > 0,
        }
        for item in CONNECTOR_REGISTRY
    ]


@router.get("/{connection_id}")
async def get_connection(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await db.get(Connection, connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")
    return _safe_conn(conn)


@router.post("")
async def create_connection(
    body: ConnectionCreate,
    request: Request,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    cipher = get_cipher()
    credentials = _strip_ephemeral_credentials(body.credentials)
    config = _strip_ephemeral_credentials(body.config)
    if body.auth_method:
        config["auth_method"] = body.auth_method
    if body.type == ConnectionType.snowflake.value:
        credentials = normalize_snowflake_config(credentials)
        config = normalize_snowflake_config(config)
    encrypted = cipher.encrypt_dict(credentials)

    conn = Connection(
        name=body.name,
        type=ConnectionType(body.type),
        connection_role=ConnectionRole(body.connection_role),
        description=body.description or "",
        credentials=encrypted,
        config=config,
        health="unknown",
        created_by_id=user.id,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.CONNECTION_CREATED, status="success",
        user_id=user.id, user_email=user.email,
        resource=f"connection:{conn.id}",
        details={"name": conn.name, "type": conn.type.value}, **ctx,
    )

    return _safe_conn(conn)


@router.put("/{connection_id}")
async def update_connection(
    connection_id: str,
    body: ConnectionUpdate,
    request: Request,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    conn = await db.get(Connection, connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")

    cipher = get_cipher()
    changes = []

    if body.name is not None:
        conn.name = body.name; changes.append("name")
    if body.connection_role is not None:
        try:
            conn.connection_role = ConnectionRole(body.connection_role)
        except ValueError:
            raise HTTPException(400, "connection_role must be source, target, or both")
        changes.append("connection_role")
    if body.description is not None:
        conn.description = body.description; changes.append("description")
    if body.config is not None:
        config = _strip_ephemeral_credentials(body.config)
        if body.auth_method:
            config["auth_method"] = body.auth_method
        if conn.type == ConnectionType.snowflake:
            config = normalize_snowflake_config(config)
        conn.config = config; changes.append("config")
    if body.credentials is not None:
        # Re-encrypt the full set
        credentials = _strip_ephemeral_credentials(body.credentials)
        if conn.type == ConnectionType.snowflake:
            credentials = normalize_snowflake_config(credentials)
        conn.credentials = cipher.encrypt_dict(credentials)
        changes.append("credentials")

    conn.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(conn)

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.CONNECTION_UPDATED, status="success",
        user_id=user.id, user_email=user.email,
        resource=f"connection:{conn.id}",
        details={"fields_changed": changes}, **ctx,
    )

    return _safe_conn(conn)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str,
    request: Request,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    conn = await db.get(Connection, connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")

    name = conn.name
    await db.delete(conn)
    await db.commit()

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.CONNECTION_DELETED, status="success",
        user_id=user.id, user_email=user.email,
        resource=f"connection:{connection_id}",
        details={"name": name}, **ctx,
    )


@router.post("/test-credentials")
async def test_credentials(
    body: ConnectionCreate,
    user: User = Depends(get_current_user),
):
    """
    Test connection credentials WITHOUT saving them. Used by the New Connection dialog.
    Returns a detailed diagnostic result.
    """
    import time
    start = time.time()

    try:
        conn_type = ConnectionType(body.type)
    except ValueError:
        return {"success": False, "error": f"Unknown connection type: {body.type}",
                "duration_ms": 0}

    cfg = {
        **_strip_ephemeral_credentials(body.config),
        **_strip_ephemeral_credentials(body.credentials),
    }
    if body.auth_method:
        cfg["auth_method"] = body.auth_method
    if body.mfa_passcode:
        cfg["mfa_passcode"] = body.mfa_passcode
    if conn_type == ConnectionType.snowflake:
        cfg = normalize_snowflake_config(cfg)

    if (
        conn_type == ConnectionType.snowflake
        and cfg.get("auth_method") == "password_mfa"
        and not cfg.get("mfa_passcode")
    ):
        return {
            "success": False,
            "error": "Missing MFA/TOTP passcode for Snowflake Password + MFA test.",
            "diagnostic": _mfa_required_message(),
            "duration_ms": int((time.time() - start) * 1000),
        }

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            _pool, _sync_test, conn_type, cfg
        )
    except Exception as e:
        logger.exception(f"Pre-save test failed: {e}")
        return {
            "success": False,
            "error": f"{type(e).__name__}: {str(e)[:500]}",
            "duration_ms": int((time.time() - start) * 1000),
        }

    result["duration_ms"] = int((time.time() - start) * 1000)
    if conn_type == ConnectionType.snowflake:
        result["execution_readiness"] = snowflake_execution_readiness(cfg, session_active=False)
    # Add helpful diagnostics
    if not result.get("success"):
        err = result.get("error", "").lower()
        if _mfa_required_error(err):
            result["diagnostic"] = _mfa_required_message()
        elif "authentication" in err or "login" in err or "password" in err or "250001" in err:
            result["diagnostic"] = "Authentication failed. Check username, password, role, and account identifier. For 250001/Snowflake backend errors, verify SYSTEM$ALLOWLIST endpoints and outbound TLS/firewall access."
        elif "network" in err or "timeout" in err or "unreachable" in err:
            result["diagnostic"] = "Network/connectivity issue. Check account identifier format, corporate proxy/TLS trust, and Snowflake allowlist/firewall access."
        elif "not authorized" in err or "access denied" in err:
            result["diagnostic"] = "Authorization failed. Check role permissions in Snowflake."
        elif "account" in err and ("invalid" in err or "identifier" in err):
            result["diagnostic"] = "Account identifier format is wrong. Should be 'orgname-accountname' or 'xy12345.us-east-1'."
        else:
            result["diagnostic"] = "Check credentials and network connectivity to your account."

    return result


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: str,
    request: Request,
    body: Optional[ConnectionTestRequest] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test a stored connection — decrypts credentials, attempts to connect."""
    conn = await db.get(Connection, connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")

    cipher = get_cipher()
    credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}
    cfg = {**conn.config, **credentials}
    if body and body.auth_method:
        cfg["auth_method"] = body.auth_method
    if body and body.mfa_passcode:
        cfg["mfa_passcode"] = body.mfa_passcode
    if conn.type == ConnectionType.snowflake:
        cfg = normalize_snowflake_config(cfg)

    if (
        conn.type == ConnectionType.snowflake
        and cfg.get("auth_method") == "password_mfa"
        and not cfg.get("mfa_passcode")
    ):
        result = {
            "success": False,
            "error": "Missing MFA/TOTP passcode for Snowflake Password + MFA test.",
            "diagnostic": _mfa_required_message(),
        }
    else:
        result = await asyncio.get_event_loop().run_in_executor(
            _pool, _sync_test, conn.type, cfg
        )

    if not result.get("success"):
        err = result.get("error", "")
        if _mfa_required_error(err):
            result["diagnostic"] = _mfa_required_message()
    if conn.type == ConnectionType.snowflake:
        result["execution_readiness"] = snowflake_execution_readiness(cfg, session_active=False)

    conn.health = "healthy" if result.get("success") else "failed"
    conn.last_tested = datetime.utcnow()
    await db.commit()

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.CONNECTION_TESTED,
        status="success" if result.get("success") else "failure",
        user_id=user.id, user_email=user.email,
        resource=f"connection:{conn.id}",
        details={"name": conn.name, "type": conn.type.value,
                 "health": conn.health}, **ctx,
    )

    return result


def _sync_test(conn_type: ConnectionType, cfg: Dict) -> Dict:
    """Dispatch to the right connector and return test_connection() result."""
    try:
        if conn_type == ConnectionType.snowflake:
            from connectors.snowflake_connector import SnowflakeConnector
            with SnowflakeConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.bigquery:
            from connectors.bigquery_connector import BigQueryConnector
            with BigQueryConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.redshift:
            from connectors.redshift_connector import RedshiftConnector
            with RedshiftConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.sqlserver:
            from connectors.sqlserver_connector import SQLServerConnector
            with SQLServerConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.salesforce:
            from connectors.salesforce_connector import SalesforceConnector
            with SalesforceConnector(cfg) as c: return c.test_connection()
        if conn_type in (ConnectionType.azureblob, ConnectionType.adls):
            from connectors.azure_connector import AzureConnector
            with AzureConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.s3:
            from connectors.s3_connector import S3Connector
            with S3Connector(cfg) as c: return c.test_connection()

        # Database connectors
        if conn_type in (ConnectionType.postgres, ConnectionType.mysql,
                         ConnectionType.oracle, ConnectionType.teradata,
                         ConnectionType.synapse):
            from connectors.db_connectors import (
                PostgreSQLConnector, MySQLConnector, OracleConnector,
                TeradataConnector, SynapseConnector,
            )
            klass = {
                ConnectionType.postgres:  PostgreSQLConnector,
                ConnectionType.mysql:     MySQLConnector,
                ConnectionType.oracle:    OracleConnector,
                ConnectionType.teradata:  TeradataConnector,
                ConnectionType.synapse:   SynapseConnector,
            }[conn_type]
            with klass(cfg) as c: return c.test_connection()

        # Storage connectors
        if conn_type == ConnectionType.gcs:
            from connectors.storage_connectors import GCSConnector
            with GCSConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.sftp:
            from connectors.storage_connectors import SFTPConnector
            with SFTPConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.rest:
            from connectors.storage_connectors import RESTConnector
            with RESTConnector(cfg) as c: return c.test_connection()

        # SaaS connectors
        if conn_type == ConnectionType.zendesk:
            from connectors.saas_connectors import ZendeskConnector
            with ZendeskConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.stripe:
            from connectors.saas_connectors import StripeConnector
            with StripeConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.hubspot:
            from connectors.saas_connectors import HubSpotConnector
            with HubSpotConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.jira:
            from connectors.saas_connectors import JiraConnector
            with JiraConnector(cfg) as c: return c.test_connection()

        # Enterprise SaaS
        if conn_type == ConnectionType.netsuite:
            from connectors.enterprise_saas_connectors import NetSuiteConnector
            with NetSuiteConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.workday:
            from connectors.enterprise_saas_connectors import WorkdayConnector
            with WorkdayConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.servicenow:
            from connectors.enterprise_saas_connectors import ServiceNowConnector
            with ServiceNowConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.marketo:
            from connectors.enterprise_saas_connectors import MarketoConnector
            with MarketoConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.shopify:
            from connectors.enterprise_saas_connectors import ShopifyConnector
            with ShopifyConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.ga4:
            from connectors.enterprise_saas_connectors import GA4Connector
            with GA4Connector(cfg) as c: return c.test_connection()

        # Extra database / streaming
        if conn_type == ConnectionType.db2:
            from connectors.extra_connectors import DB2Connector
            with DB2Connector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.saphana:
            from connectors.extra_connectors import SAPHanaConnector
            with SAPHanaConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.pubsub:
            from connectors.extra_connectors import PubSubConnector
            with PubSubConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.eventhubs:
            from connectors.extra_connectors import EventHubsConnector
            with EventHubsConnector(cfg) as c: return c.test_connection()

        # Streaming
        if conn_type == ConnectionType.kafka:
            from connectors.streaming_connectors import KafkaConnector
            with KafkaConnector(cfg) as c: return c.test_connection()
        if conn_type == ConnectionType.kinesis:
            from connectors.streaming_connectors import KinesisConnector
            with KinesisConnector(cfg) as c: return c.test_connection()

        # Flat file — nothing to test
        if conn_type == ConnectionType.flatfile:
            return {"success": True, "note": "Flat file connections don't require connectivity test"}

        return {"success": False, "error": f"No test handler for {conn_type.value}"}

    except Exception as e:
        return {"success": False, "error": str(e)}
