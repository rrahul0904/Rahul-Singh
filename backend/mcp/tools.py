from __future__ import annotations

from typing import Any

from .schemas import SafetyLevel, ToolDefinition


TOOL_DEFINITIONS: list[ToolDefinition] = [
    ToolDefinition("uma.list_runs", SafetyLevel.READ_ONLY, "List persisted UMA migration runs."),
    ToolDefinition("uma.get_run", SafetyLevel.READ_ONLY, "Read one UMA migration run by run_id.", {"run_id": "string"}),
    ToolDefinition("uma.list_artifacts", SafetyLevel.READ_ONLY, "List control-plane artifacts, optionally scoped by run_id.", {"run_id": "string?"}),
    ToolDefinition("uma.read_artifact", SafetyLevel.READ_ONLY, "Read a redacted artifact body by artifact_id.", {"artifact_id": "string"}),
    ToolDefinition("uma.get_conversion_report", SafetyLevel.READ_ONLY, "Read the persisted conversion report for a run.", {"run_id": "string"}),
    ToolDefinition("uma.get_validation_summary", SafetyLevel.READ_ONLY, "Read validation status and validation evidence for a run.", {"run_id": "string"}),
    ToolDefinition("uma.get_brain_review_decisions", SafetyLevel.READ_ONLY, "Read Brain Review decisions for a run.", {"run_id": "string"}),
    ToolDefinition("list_connections", SafetyLevel.READ_ONLY, "List configured replication connections without secrets."),
    ToolDefinition("test_connection", SafetyLevel.READ_ONLY, "Run a bounded connector health check."),
    ToolDefinition("discover_source_metadata", SafetyLevel.READ_ONLY, "Discover schemas/tables/columns for supported sources."),
    ToolDefinition("get_replication_jobs", SafetyLevel.READ_ONLY, "List replication jobs and table counts."),
    ToolDefinition("get_replication_run_status", SafetyLevel.READ_ONLY, "Read run and table-run status."),
    ToolDefinition("get_snowflake_readiness", SafetyLevel.READ_ONLY, "Read Snowflake diagnostics and blocked grant items."),
    ToolDefinition("get_cost_estimate", SafetyLevel.READ_ONLY, "Estimate cost from persisted metadata only."),
    ToolDefinition("create_replication_plan", SafetyLevel.PLANNING, "Create or refresh a table-level replication plan."),
    ToolDefinition("recommend_sync_strategy", SafetyLevel.PLANNING, "Recommend load/write mode from table metadata."),
    ToolDefinition("recommend_snowflake_warehouse", SafetyLevel.PLANNING, "Recommend warehouse size from estimated bytes/rows."),
    ToolDefinition("identify_missing_keys_or_watermarks", SafetyLevel.PLANNING, "Find selected tables missing primary keys or watermarks."),
    ToolDefinition("stage_ddl_for_review", SafetyLevel.STAGING, "Stage DDL text for review; never execute it."),
    ToolDefinition("stage_replication_job", SafetyLevel.STAGING, "Stage a replication job definition for approval."),
    ToolDefinition("stage_permission_setup_script", SafetyLevel.ADMIN_REQUIRES_APPROVAL, "Generate grant script text for admin review."),
    ToolDefinition("start_replication_job", SafetyLevel.EXECUTION_REQUIRES_APPROVAL, "Start an approved replication job."),
    ToolDefinition("pause_replication_job", SafetyLevel.EXECUTION_REQUIRES_APPROVAL, "Pause an approved replication job."),
    ToolDefinition("resume_replication_job", SafetyLevel.EXECUTION_REQUIRES_APPROVAL, "Resume an approved replication job."),
    ToolDefinition("retry_failed_run", SafetyLevel.EXECUTION_REQUIRES_APPROVAL, "Retry a failed run after review."),
    ToolDefinition("execute_approved_ddl", SafetyLevel.ADMIN_REQUIRES_APPROVAL, "Execute pre-approved DDL only; arbitrary SQL is not accepted."),
]


def list_tool_definitions() -> list[dict[str, Any]]:
    return [tool.to_dict() for tool in TOOL_DEFINITIONS]


def get_tool_definition(name: str) -> ToolDefinition | None:
    return next((tool for tool in TOOL_DEFINITIONS if tool.name == name), None)


def registry_summary() -> dict[str, Any]:
    by_level: dict[str, int] = {}
    for tool in TOOL_DEFINITIONS:
        by_level[tool.safety_level.value] = by_level.get(tool.safety_level.value, 0) + 1
    return {
        "provider": "internal_tool_registry",
        "registry_kind": "internal_tool_registry",
        "remote_mcp_server": False,
        "honest_label": "Internal Tool Registry",
        "mcp_package_required": False,
        "message": "This is an authenticated internal UMA tool registry, not a remote MCP server.",
        "arbitrary_sql_allowed": False,
        "tool_count": len(TOOL_DEFINITIONS),
        "safety_levels": by_level,
        "tools": list_tool_definitions(),
    }
