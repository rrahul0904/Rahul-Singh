from __future__ import annotations

from typing import Any

from sqlalchemy import select

from agents.tools.safety import redact_secrets
from models import ControlPlaneArtifact, ControlPlaneRun, HumanReviewItem, User
from services.control_plane import read_artifact_text
from .schemas import SafetyLevel, ToolResult
from .tools import get_tool_definition, list_tool_definitions, registry_summary


class InternalToolRegistryServer:
    """Authenticated UMA internal tool registry.

    This class is intentionally not a remote MCP server. It exposes the same
    bounded tool vocabulary UMA can later publish through MCP, while keeping the
    current product label honest.
    """

    def __init__(self, db=None, user: User | None = None):
        self.db = db
        self.user = user

    def describe(self) -> dict[str, Any]:
        return registry_summary()

    def list_tools(self) -> list[dict[str, Any]]:
        return list_tool_definitions()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None, approved: bool = False) -> dict[str, Any]:
        tool = get_tool_definition(name)
        if not tool:
            return ToolResult(
                tool_name=name,
                status="NOT_FOUND",
                safety_level=SafetyLevel.READ_ONLY,
                output={"error": "Tool is not registered."},
            ).to_dict()
        if tool.safety_level in {SafetyLevel.EXECUTION_REQUIRES_APPROVAL, SafetyLevel.ADMIN_REQUIRES_APPROVAL} and not approved:
            return ToolResult(
                tool_name=name,
                status="APPROVAL_REQUIRED",
                safety_level=tool.safety_level,
                output={"message": "Execution/admin tools require explicit approval and do not accept arbitrary SQL."},
            ).to_dict()
        return ToolResult(
            tool_name=name,
            status="STAGED" if tool.safety_level != SafetyLevel.READ_ONLY else "READY",
            safety_level=tool.safety_level,
            output={"arguments": arguments or {}, "message": "Tool registered; bind to FastAPI service action before live use."},
        ).to_dict()

    async def call_tool_async(self, name: str, arguments: dict[str, Any] | None = None, approved: bool = False) -> dict[str, Any]:
        tool = get_tool_definition(name)
        if not tool:
            return ToolResult(name, "NOT_FOUND", SafetyLevel.READ_ONLY, {"error": "Tool is not registered."}).to_dict()
        if not self.user:
            return ToolResult(name, "AUTH_REQUIRED", tool.safety_level, {"error": "Authenticated UMA user is required."}).to_dict()
        if tool.safety_level in {SafetyLevel.EXECUTION_REQUIRES_APPROVAL, SafetyLevel.ADMIN_REQUIRES_APPROVAL} and not approved:
            return ToolResult(name, "APPROVAL_REQUIRED", tool.safety_level, {"message": "Execution/admin tools require explicit approval."}).to_dict()
        if name.startswith("uma."):
            return ToolResult(name, "READY", tool.safety_level, await self._call_uma_tool(name, arguments or {})).to_dict()
        return ToolResult(name, "STAGED", tool.safety_level, {"arguments": arguments or {}, "message": "Internal registry tool exists but is not bound to a live UMA service action yet."}).to_dict()

    async def _call_uma_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.db is None:
            return {"error": "Database session is required for UMA data tools."}
        if name == "uma.list_runs":
            rows = (await self.db.execute(select(ControlPlaneRun).order_by(ControlPlaneRun.created_at.desc()).limit(int(arguments.get("limit") or 50)))).scalars().all()
            return {"runs": [_run(row) for row in rows]}
        if name == "uma.get_run":
            run = await self.db.get(ControlPlaneRun, arguments.get("run_id"))
            return {"run": _run(run) if run else None}
        if name == "uma.list_artifacts":
            stmt = select(ControlPlaneArtifact).order_by(ControlPlaneArtifact.created_at.desc())
            if arguments.get("run_id"):
                stmt = stmt.where(ControlPlaneArtifact.run_id == arguments["run_id"])
            rows = (await self.db.execute(stmt.limit(int(arguments.get("limit") or 100)))).scalars().all()
            return {"artifacts": [_artifact(row) for row in rows]}
        if name == "uma.read_artifact":
            artifact = await self.db.get(ControlPlaneArtifact, arguments.get("artifact_id"))
            return {"artifact": _artifact(artifact) if artifact else None, "text": redact_secrets(read_artifact_text(artifact)) if artifact else ""}
        if name == "uma.get_conversion_report":
            run = await self.db.get(ControlPlaneRun, arguments.get("run_id"))
            return {"run_id": arguments.get("run_id"), "report": redact_secrets((run.summary_json or {}) if run else {})}
        if name == "uma.get_validation_summary":
            run = await self.db.get(ControlPlaneRun, arguments.get("run_id"))
            summary = run.summary_json or {} if run else {}
            return {"run_id": arguments.get("run_id"), "validation": redact_secrets(summary.get("validation") or {}), "validation_status": summary.get("validation_status") or (summary.get("job_state") or {}).get("validation_status") or "not_run"}
        if name == "uma.get_brain_review_decisions":
            rows = (await self.db.execute(select(HumanReviewItem).where(HumanReviewItem.run_id == arguments.get("run_id")).order_by(HumanReviewItem.created_at.asc()))).scalars().all()
            return {"run_id": arguments.get("run_id"), "decisions": [_decision(row) for row in rows]}
        return {"error": "UMA tool is not implemented."}


def _run(row: ControlPlaneRun | None) -> dict[str, Any]:
    if not row:
        return {}
    return redact_secrets({
        "id": row.id,
        "name": row.name,
        "workflow_type": row.workflow_type,
        "status": row.status,
        "source_dialect": row.source_dialect,
        "target_dialect": row.target_dialect,
        "readiness_score": (row.summary_json or {}).get("readiness_score"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    })


def _artifact(row: ControlPlaneArtifact | None) -> dict[str, Any]:
    if not row:
        return {}
    return redact_secrets({
        "id": row.id,
        "run_id": row.run_id,
        "original_filename": row.original_filename,
        "artifact_category": row.artifact_category,
        "file_type": row.file_type,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    })


def _decision(row: HumanReviewItem) -> dict[str, Any]:
    return redact_secrets({
        "id": row.id,
        "run_id": row.run_id,
        "item_type": row.item_type,
        "severity": row.severity,
        "title": row.title,
        "description": row.description,
        "recommendation": row.recommendation,
        "status": row.status,
        "metadata": row.metadata_json or {},
    })


InternalMCPRegistryServer = InternalToolRegistryServer
server = InternalToolRegistryServer()
