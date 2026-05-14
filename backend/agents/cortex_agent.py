from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from services.migration_intelligence import deterministic_migration_answer
from mcp.tools import registry_summary


@dataclass(frozen=True)
class SnowflakeReadiness:
    configured_connections: int
    healthy_connections: int
    active_connection_name: str | None = None
    permission_diagnostics_passed: bool = False

    @property
    def status(self) -> str:
        if self.healthy_connections > 0 and self.permission_diagnostics_passed:
            return "READY_FOR_LIVE_VALIDATION"
        if self.healthy_connections > 0:
            return "CONNECTION_HEALTHY_PERMISSIONS_UNVERIFIED"
        if self.configured_connections > 0:
            return "CONNECTION_NEEDS_TEST"
        return "SNOWFLAKE_CONNECTION_REQUIRED"


class CortexMigrationAgent:
    """Deterministic local Cortex-style migration agent.

    This is intentionally not a chatbot wrapper. It builds a structured agent
    decision from product state and can later swap local planning tools for
    Snowflake Cortex/Search/Analyst calls once a Snowflake connection is present.
    """

    name = "UMA Cortex Migration Agent"
    version = "0.1.0-local"

    def run(
        self,
        *,
        message: str,
        readiness: SnowflakeReadiness,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        if any(key in context for key in ("jobs", "connections", "tables", "snowflake_readiness")):
            return deterministic_migration_answer(message, context)
        intent = self._classify_intent(message)
        schemas = self._extract_schemas(message, context)
        source_type = self._extract_source(message, context)
        steps = self._build_steps(intent, source_type, schemas, readiness)
        token_estimate = self._estimate_tokens(message, steps)

        return {
            "agent_id": f"cortex-agent-{uuid.uuid4().hex[:12]}",
            "agent_name": self.name,
            "version": self.version,
            "status": "READY_LOCAL_AGENT",
            "mode": "local_deterministic_agent",
            "intent": intent,
            "summary": self._summary(intent, readiness),
            "architecture": self.architecture(),
            "steps": steps,
            "permission_checks": self.permission_checklist(),
            "snowflake_readiness": {
                "status": readiness.status,
                "configured_connections": readiness.configured_connections,
                "healthy_connections": readiness.healthy_connections,
                "active_connection_name": readiness.active_connection_name,
                "permission_diagnostics_passed": readiness.permission_diagnostics_passed,
                "live_execution_enabled": readiness.status == "READY_FOR_LIVE_VALIDATION",
                "safe_next_action": self._safe_next_action(readiness),
            },
            "credit_estimate": {
                "snowflake_credits": "0 until approved Snowflake SQL/SPCS/Tasks execute",
                "cortex_credits": "0 until Cortex functions/search/analyst are called",
                "local_agent_cost": "backend CPU only",
            },
            "token_estimate": token_estimate,
            "internal_tool_registry": {
                "remote_mcp_server": False,
                "recommended_name_if_promoted_to_mcp": "uma-migration-tools-mcp",
                "tools": [
                    "inspect_source_schema",
                    "stage_ddl_for_review",
                    "execute_approved_ddl",
                    "run_validation",
                    "estimate_snowflake_cost",
                    "check_snowflake_permissions",
                ],
                "rule": "Current UMA tools are an authenticated internal registry. Promote to remote MCP only when hosted callable transport is implemented.",
            },
        }

    def readiness(self) -> dict[str, Any]:
        return {
            "mode": "local_deterministic_agent",
            "provider_configured": False,
            "cortex_called": False,
            "openai_called": False,
            "token_credit_note": "No LLM tokens or Snowflake Cortex credits are used in deterministic local mode.",
            "mcp_registry": registry_summary(),
        }

    def architecture(self) -> dict[str, Any]:
        return {
            "runtime": "FastAPI local agent now; Snowpark Container Services later",
            "orchestration": "UMA deterministic workflow with persisted steps",
            "state_store": "UMA control tables first; Snowflake UMA_CONTROL when live target is configured",
            "intelligence": {
                "local_now": ["deterministic planning", "permission/readiness checks", "cost/token estimates"],
                "snowflake_later": ["Cortex Search", "Cortex Analyst", "AI_COMPLETE"],
            },
            "safety": [
                "read-only and planning tools run without approval",
                "DDL/DML execution requires approval",
                "dangerous SQL is blocked or staged",
                "secrets are never returned in agent output",
            ],
        }

    def permission_checklist(self) -> list[dict[str, str]]:
        return [
            {
                "area": "Warehouse",
                "check": "role can USAGE target warehouse",
                "why": "needed for any Snowflake SQL, validation, COPY, MERGE, Cortex calls",
            },
            {
                "area": "Database/schema",
                "check": "role has USAGE database/schema and CREATE TABLE/STAGE/TASK where approved",
                "why": "needed for generated DDL and internal stages",
            },
            {
                "area": "Data load",
                "check": "role has INSERT/UPDATE/MERGE on target tables and READ/WRITE on stages",
                "why": "needed for full load and incremental replication",
            },
            {
                "area": "Cortex",
                "check": "role has Cortex function/search/analyst access enabled by account policy",
                "why": "needed before replacing local planning with Snowflake-native intelligence",
            },
            {
                "area": "Observability",
                "check": "role can read query history/account usage or a delegated cost view",
                "why": "needed for actual cost reconciliation, not just estimates",
            },
        ]

    def _classify_intent(self, message: str) -> str:
        text = message.lower()
        if any(term in text for term in ["permission", "grant", "privilege", "access"]):
            return "snowflake_permission_readiness"
        if any(term in text for term in ["cost", "credit", "token"]):
            return "cost_and_token_estimation"
        if any(term in text for term in ["mcp", "tool server", "tooling"]):
            return "mcp_tooling_architecture"
        if any(term in text for term in ["cortex", "agent", "architecture"]):
            return "cortex_agent_architecture"
        return "migration_orchestration_plan"

    def _extract_source(self, message: str, context: dict[str, Any]) -> str:
        text = message.lower()
        for source in ["teradata", "oracle", "sqlserver", "postgres", "bigquery", "redshift", "s3"]:
            if source in text:
                return source
        return str(context.get("source_type") or "unknown")

    def _extract_schemas(self, message: str, context: dict[str, Any]) -> list[str]:
        if isinstance(context.get("schemas"), list) and context["schemas"]:
            return [str(s).upper() for s in context["schemas"]]
        matches = re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", message)
        ignored = {"UMA", "MCP", "DDL", "DML", "SQL", "SPCS", "CDC"}
        schemas = [m for m in matches if m not in ignored]
        return schemas[:5] or ["CRM", "FINANCE"]

    def _build_steps(
        self,
        intent: str,
        source_type: str,
        schemas: list[str],
        readiness: SnowflakeReadiness,
    ) -> list[dict[str, Any]]:
        live_status = "READY" if readiness.status == "READY_FOR_LIVE_VALIDATION" else "BLOCKED"
        return [
            {
                "name": "discover_metadata",
                "tool_category": "READ_ONLY",
                "status": "READY",
                "output": f"Inspect {source_type} metadata for schemas {', '.join(schemas)}.",
            },
            {
                "name": "assess_complexity",
                "tool_category": "PLANNING",
                "status": "READY",
                "output": "Score objects by data type, volume, SQL/procedure complexity, dependencies, and validation risk.",
            },
            {
                "name": "convert_ddl",
                "tool_category": "STAGING",
                "status": "READY",
                "output": "Generate Snowflake DDL and store it for review; do not execute automatically.",
            },
            {
                "name": "human_approval_gate",
                "tool_category": "APPROVAL",
                "status": "REQUIRED",
                "output": "Approval required before target DDL/DML, Cortex provisioning, Tasks, or SPCS actions.",
            },
            {
                "name": "execute_snowflake_actions",
                "tool_category": "EXECUTION",
                "status": live_status,
                "output": readiness.status,
            },
            {
                "name": "validation_cost_report",
                "tool_category": "READ_ONLY",
                "status": "READY" if live_status == "READY" else "STAGED",
                "output": "Run row/schema/hash checks and estimate or reconcile credits when live data exists.",
            },
        ]

    def _summary(self, intent: str, readiness: SnowflakeReadiness) -> str:
        if readiness.status == "READY_FOR_LIVE_VALIDATION":
            return f"{intent}: local agent is ready to plan and can validate live Snowflake execution after approval."
        return f"{intent}: local agent is working; live Snowflake/Cortex execution is gated by {readiness.status}."

    def _safe_next_action(self, readiness: SnowflakeReadiness) -> str:
        if readiness.status == "SNOWFLAKE_CONNECTION_REQUIRED":
            return "Create or select a Snowflake connection, then run connection diagnostics."
        if readiness.status == "CONNECTION_NEEDS_TEST":
            return "Run Snowflake connection test and permission diagnostics."
        if readiness.status == "CONNECTION_HEALTHY_PERMISSIONS_UNVERIFIED":
            return "Run permission diagnostics for warehouse, schema, stage, Cortex, Tasks, and SPCS grants."
        return "Stage DDL and run an approved validation smoke test."

    def _estimate_tokens(self, message: str, steps: list[dict[str, Any]]) -> dict[str, int | str]:
        input_tokens = max(1, round(len(message) / 4))
        output_tokens = 450 + len(steps) * 55
        return {
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
            "note": "Only applies if an LLM/Cortex call is enabled; local deterministic mode uses no LLM tokens.",
        }
