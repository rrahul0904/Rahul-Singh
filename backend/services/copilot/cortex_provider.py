from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.cortex_agent import CortexMigrationAgent, SnowflakeReadiness
from core.config import settings
from models import Connection, ConnectionType
from services.copilot.base import CopilotAnswer, CopilotProvider, safe_context
from services.snowflake_intelligence import SnowflakeIntelligenceService


class CortexCopilotProvider(CopilotProvider):
    name = "cortex"
    display_name = "Snowflake Cortex"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _readiness(self) -> SnowflakeReadiness:
        rows = (
            await self.db.execute(
                select(Connection)
                .where(Connection.type == ConnectionType.snowflake)
                .order_by(Connection.updated_at.desc())
            )
        ).scalars().all()
        healthy = [row for row in rows if (row.health or "").lower() == "healthy"]
        return SnowflakeReadiness(
            configured_connections=len(rows),
            healthy_connections=len(healthy),
            active_connection_name=healthy[0].name if healthy else rows[0].name if rows else None,
        )

    async def health(self) -> dict[str, Any]:
        readiness = await self._readiness()
        services = await SnowflakeIntelligenceService(self.db).capabilities()
        return {
            "provider": self.name,
            "enabled": bool(settings.CORTEX_ENABLED),
            "status": readiness.status if settings.CORTEX_ENABLED else "DISABLED",
            "configured_connections": readiness.configured_connections,
            "healthy_connections": readiness.healthy_connections,
            "uses": ["Cortex Analyst metadata questions", "Cortex Search logs/docs/runbooks", "LLM summaries when configured"],
            "services": services,
        }

    async def send_message(self, message: str, context: dict[str, Any] | None = None) -> CopilotAnswer:
        readiness = await self._readiness()
        agent = CortexMigrationAgent()
        result = agent.run(message=message, context=safe_context(context), readiness=readiness)
        health = await self.health()
        snowflake = SnowflakeIntelligenceService(self.db)
        text = (message or "").lower()
        service_result: dict[str, Any] | None = None
        if "document" in text or "runbook" in text or "docs" in text:
            service_result = await snowflake.cortex_search(message, document=True, limit=5)
        elif "cortex search" in text or "search logs" in text:
            service_result = await snowflake.cortex_search(message, document=False, limit=5)
        elif "analyst" in text or "semantic" in text or "metadata" in text:
            service_result = await snowflake.cortex_analyst(message)
        elif "summarize" in text or "explain" in text or "cost spike" in text:
            service_result = await snowflake.cortex_complete(message)

        summary = result["summary"]
        if service_result:
            status = service_result.get("status")
            if status == "SUCCEEDED":
                summary = f"{summary}\n\nCortex service result is available in source context."
            else:
                summary = f"{summary}\n\nCortex service status: {status}. {service_result.get('message', '')}".strip()
        return CopilotAnswer(
            provider=self.name,
            answer=summary,
            source_context={
                "run_id": (context or {}).get("run_id"),
                "validation_id": (context or {}).get("validation_id"),
                "cost_estimate_id": (context or {}).get("cost_estimate_id"),
                "report_id": (context or {}).get("report_id"),
                "snowflake_readiness": result.get("snowflake_readiness", {}),
                "cortex_service_result": service_result,
            },
            proposed_action=None,
            health=health,
        )
