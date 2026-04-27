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

router = APIRouter()
logger = logging.getLogger("uma.routes.connections")
_pool = ThreadPoolExecutor(max_workers=4)

CONNECTOR_REGISTRY = [
    {"key": "bigquery", "display_name": "BigQuery", "status": "ready", "source": True, "target": False},
    {"key": "redshift", "display_name": "Redshift", "status": "ready", "source": True, "target": False},
    {"key": "snowflake", "display_name": "Snowflake", "status": "ready", "source": True, "target": True},
    {"key": "sqlserver", "display_name": "SQL Server", "status": "ready", "source": True, "target": False},
    {"key": "postgres", "display_name": "PostgreSQL", "status": "ready", "source": True, "target": False},
    {"key": "mysql", "display_name": "MySQL", "status": "ready", "source": True, "target": False},
    {"key": "oracle", "display_name": "Oracle", "status": "ready", "source": True, "target": False},
    {"key": "teradata", "display_name": "Teradata", "status": "ready", "source": True, "target": False},
    {"key": "synapse", "display_name": "Synapse", "status": "ready", "source": True, "target": False},
    {"key": "salesforce", "display_name": "Salesforce", "status": "ready", "source": True, "target": False},
    {"key": "zendesk", "display_name": "Zendesk", "status": "ready", "source": True, "target": False},
    {"key": "hubspot", "display_name": "HubSpot", "status": "ready", "source": True, "target": False},
    {"key": "stripe", "display_name": "Stripe", "status": "ready", "source": True, "target": False},
    {"key": "jira", "display_name": "Jira", "status": "ready", "source": True, "target": False},
    {"key": "s3", "display_name": "Amazon S3", "status": "ready", "source": True, "target": True},
    {"key": "adls", "display_name": "ADLS Gen2", "status": "ready", "source": True, "target": True},
    {"key": "gcs", "display_name": "GCS", "status": "ready", "source": True, "target": True},
    {"key": "sftp", "display_name": "SFTP", "status": "ready", "source": True, "target": False},
    {"key": "flatfile", "display_name": "Flat Files", "status": "ready", "source": True, "target": False},
    {"key": "kafka", "display_name": "Kafka", "status": "ready", "source": True, "target": False},
    {"key": "kinesis", "display_name": "Kinesis", "status": "ready", "source": True, "target": False},
    {"key": "rest", "display_name": "REST/GraphQL", "status": "ready", "source": True, "target": False},
    {"key": "netsuite", "display_name": "NetSuite", "status": "coming_soon", "source": True, "target": False},
    {"key": "workday", "display_name": "Workday", "status": "coming_soon", "source": True, "target": False},
    {"key": "ga4", "display_name": "Google Analytics", "status": "coming_soon", "source": True, "target": False},
]


class ConnectionCreate(BaseModel):
    name: str
    type: str
    connection_role: str = "both"
    description: Optional[str] = ""
    credentials: Dict[str, Any] = {}
    config: Dict[str, Any] = {}

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


def _safe_conn(conn: Connection) -> dict:
    """Never return raw credentials. Show masked hints only."""
    cipher = get_cipher()
    credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}

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
    encrypted = cipher.encrypt_dict(body.credentials)

    conn = Connection(
        name=body.name,
        type=ConnectionType(body.type),
        connection_role=ConnectionRole(body.connection_role),
        description=body.description or "",
        credentials=encrypted,
        config=body.config,
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
        conn.config = body.config; changes.append("config")
    if body.credentials is not None:
        # Re-encrypt the full set
        conn.credentials = cipher.encrypt_dict(body.credentials)
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

    cfg = {**body.config, **body.credentials}

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
    # Add helpful diagnostics
    if not result.get("success"):
        err = result.get("error", "").lower()
        if "authentication" in err or "login" in err or "password" in err or "250001" in err:
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

    result = await asyncio.get_event_loop().run_in_executor(
        _pool, _sync_test, conn.type, cfg
    )

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
