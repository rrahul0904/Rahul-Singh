from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.snowflake_connector import SnowflakeConnector
from core.config import settings
from core.security import get_cipher
from models import Connection, ConnectionType
from services.snowpark_validation import (
    SnowparkTableRef,
    SnowparkUnavailableError,
    SnowparkValidationService,
)


def _literal(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def _safe_limit(value: Any, default: int = 10, maximum: int = 50) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(parsed, maximum))


@dataclass(frozen=True)
class SnowflakeConnectionContext:
    connection: Connection | None
    config: dict[str, Any]
    status: str


class SnowflakeIntelligenceService:
    """Read-only Snowflake intelligence surface for Cortex, Snowpark, logs, docs, and cost.

    This service does not expose credentials and does not run arbitrary SQL. Each
    method is scoped to known read-only Snowflake/Cortex operations.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def connection_context(self) -> SnowflakeConnectionContext:
        rows = (
            await self.db.execute(
                select(Connection)
                .where(Connection.type == ConnectionType.snowflake)
                .order_by(Connection.updated_at.desc())
            )
        ).scalars().all()
        if not rows:
            return SnowflakeConnectionContext(None, {}, "SNOWFLAKE_CONNECTION_REQUIRED")
        healthy = [row for row in rows if (row.health or "").lower() == "healthy"]
        conn = healthy[0] if healthy else rows[0]
        cipher = get_cipher()
        credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}
        config = conn.config or {}
        cfg = {
            **config,
            **credentials,
            "account": config.get("account", ""),
            "user": credentials.get("user") or config.get("user", ""),
            "password": credentials.get("password", ""),
            "warehouse": config.get("warehouse") or settings.SNOWFLAKE_WAREHOUSE,
            "database": config.get("database") or settings.SNOWFLAKE_DATABASE,
            "schema": config.get("schema") or settings.SNOWFLAKE_SCHEMA,
            "role": config.get("role") or settings.SNOWFLAKE_ROLE,
        }
        missing = [key for key in ("account", "user", "password", "warehouse", "database") if not cfg.get(key)]
        if missing:
            return SnowflakeConnectionContext(conn, {}, "SNOWFLAKE_CONNECTION_INCOMPLETE")
        if not healthy:
            return SnowflakeConnectionContext(conn, cfg, "CONNECTION_NEEDS_TEST")
        return SnowflakeConnectionContext(conn, cfg, "CONNECTION_AVAILABLE")

    async def capabilities(self) -> dict[str, Any]:
        ctx = await self.connection_context()
        snowpark_status = "AVAILABLE"
        try:
            import snowflake.snowpark  # noqa: F401
        except Exception:
            snowpark_status = "PYTHON_PACKAGE_MISSING"

        cortex_enabled = bool(settings.CORTEX_ENABLED)
        return {
            "snowflake_connection": {
                "status": ctx.status,
                "connection_id": ctx.connection.id if ctx.connection else None,
                "connection_name": ctx.connection.name if ctx.connection else None,
                "health": ctx.connection.health if ctx.connection else None,
            },
            "cortex": {
                "enabled": cortex_enabled,
                "llm": {
                    "status": "READY" if cortex_enabled and settings.CORTEX_LLM_MODEL else "CONFIG_REQUIRED",
                    "model": settings.CORTEX_LLM_MODEL or None,
                    "function": "SNOWFLAKE.CORTEX.COMPLETE",
                },
                "analyst": {
                    "status": "READY" if cortex_enabled and settings.CORTEX_SEMANTIC_MODEL else "CONFIG_REQUIRED",
                    "semantic_model": settings.CORTEX_SEMANTIC_MODEL or None,
                },
                "search": {
                    "status": "READY" if cortex_enabled and settings.CORTEX_SEARCH_SERVICE else "CONFIG_REQUIRED",
                    "service": settings.CORTEX_SEARCH_SERVICE or None,
                },
                "document_search": {
                    "status": "READY" if cortex_enabled and (settings.CORTEX_DOCUMENT_SEARCH_SERVICE or settings.CORTEX_SEARCH_SERVICE) else "CONFIG_REQUIRED",
                    "service": settings.CORTEX_DOCUMENT_SEARCH_SERVICE or settings.CORTEX_SEARCH_SERVICE or None,
                },
            },
            "snowpark": {
                "status": snowpark_status,
                "capabilities": ["profile_table", "duplicate_primary_key_count", "sample_hash"],
            },
            "intelligence": {
                "query_history": "READY_WITH_CONNECTION" if ctx.config else ctx.status,
                "cost_intelligence": "READY_WITH_CONNECTION" if ctx.config else ctx.status,
                "validation_context": "READY_LOCAL_METADATA",
            },
        }

    async def cortex_complete(self, prompt: str) -> dict[str, Any]:
        if not settings.CORTEX_ENABLED:
            return {"status": "DISABLED", "message": "CORTEX_ENABLED=false"}
        if not settings.CORTEX_LLM_MODEL:
            return {"status": "CONFIG_REQUIRED", "message": "CORTEX_LLM_MODEL is not configured"}
        ctx = await self.connection_context()
        if not ctx.config:
            return {"status": ctx.status, "message": "Snowflake connection is required"}
        sql = (
            "SELECT SNOWFLAKE.CORTEX.COMPLETE("
            f"{_literal(settings.CORTEX_LLM_MODEL)}, {_literal(prompt[:8000])}"
            ") AS RESPONSE"
        )
        return await self._run_known_query(ctx.config, sql, "cortex_llm")

    async def cortex_search(self, query: str, *, document: bool = False, limit: int = 10) -> dict[str, Any]:
        if not settings.CORTEX_ENABLED:
            return {"status": "DISABLED", "message": "CORTEX_ENABLED=false"}
        service = settings.CORTEX_DOCUMENT_SEARCH_SERVICE if document else settings.CORTEX_SEARCH_SERVICE
        service = service or (settings.CORTEX_SEARCH_SERVICE if document else "")
        if not service:
            return {
                "status": "CONFIG_REQUIRED",
                "message": "Cortex Search service is not configured",
                "document_search": document,
            }
        ctx = await self.connection_context()
        if not ctx.config:
            return {"status": ctx.status, "message": "Snowflake connection is required"}
        payload = json.dumps({"query": query[:1000], "limit": _safe_limit(limit)})
        sql = f"SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW({_literal(service)}, {_literal(payload)}) AS RESULTS"
        return await self._run_known_query(ctx.config, sql, "cortex_document_search" if document else "cortex_search")

    async def cortex_analyst(self, question: str) -> dict[str, Any]:
        if not settings.CORTEX_ENABLED:
            return {"status": "DISABLED", "message": "CORTEX_ENABLED=false"}
        if not settings.CORTEX_SEMANTIC_MODEL:
            return {"status": "CONFIG_REQUIRED", "message": "CORTEX_SEMANTIC_MODEL is not configured"}
        ctx = await self.connection_context()
        if not ctx.config:
            return {"status": ctx.status, "message": "Snowflake connection is required"}
        prompt = (
            "Answer this structured migration metadata question using the configured semantic model "
            f"{settings.CORTEX_SEMANTIC_MODEL}: {question}"
        )
        return await self.cortex_complete(prompt)

    async def snowpark_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = await self.connection_context()
        if not ctx.connection:
            return {"status": ctx.status, "message": "Snowflake connection is required"}
        database = payload.get("database") or ctx.config.get("database") or settings.SNOWFLAKE_DATABASE
        schema = payload.get("schema") or ctx.config.get("schema") or settings.SNOWFLAKE_SCHEMA
        table = payload.get("table")
        if not table:
            return {"status": "TABLE_REQUIRED", "message": "table is required for Snowpark profile"}

        def _profile():
            service = SnowparkValidationService.from_connection(ctx.connection, database=database, schema=schema)
            try:
                return service.profile_table(
                    SnowparkTableRef(database=database, schema=schema, table=table),
                    primary_key_columns=payload.get("primary_key_columns") or [],
                    watermark_column=payload.get("watermark_column"),
                    soft_delete_column=payload.get("soft_delete_column"),
                )
            finally:
                service.close()

        try:
            profile = await asyncio.to_thread(_profile)
            return {"status": "SUCCEEDED", "profile": profile}
        except SnowparkUnavailableError as exc:
            return {"status": "PYTHON_PACKAGE_MISSING", "message": str(exc)}
        except Exception as exc:
            return {"status": "ERROR", "message": str(exc)[:500]}

    async def query_history(self, limit: int = 10) -> dict[str, Any]:
        ctx = await self.connection_context()
        if not ctx.config:
            return {"status": ctx.status, "message": "Snowflake connection is required"}
        sql = f"""
        SELECT QUERY_ID, QUERY_TEXT, QUERY_TAG, START_TIME, END_TIME, EXECUTION_TIME, WAREHOUSE_NAME
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE QUERY_TAG ILIKE '%UMA%'
        ORDER BY START_TIME DESC
        LIMIT {_safe_limit(limit)}
        """
        return await self._run_known_query(ctx.config, sql, "query_history")

    async def cost_intelligence(self, limit: int = 10) -> dict[str, Any]:
        ctx = await self.connection_context()
        if not ctx.config:
            return {"status": ctx.status, "message": "Snowflake connection is required"}
        sql = f"""
        SELECT WAREHOUSE_NAME, START_TIME, END_TIME, CREDITS_USED, CREDITS_USED_COMPUTE, CREDITS_USED_CLOUD_SERVICES
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        ORDER BY START_TIME DESC
        LIMIT {_safe_limit(limit)}
        """
        return await self._run_known_query(ctx.config, sql, "cost_intelligence")

    async def _run_known_query(self, cfg: dict[str, Any], sql: str, service_name: str) -> dict[str, Any]:
        def _run():
            with SnowflakeConnector(cfg) as sf:
                return sf.run_query(sql)

        try:
            rows = await asyncio.to_thread(_run)
            return {"status": "SUCCEEDED", "service": service_name, "rows": rows}
        except Exception as exc:
            return {"status": "ERROR", "service": service_name, "message": str(exc)[:500]}
