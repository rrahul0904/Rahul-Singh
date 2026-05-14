import os
import sys
import asyncio
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from models import ControlPlaneArtifact, ControlPlaneRun, HumanReviewItem, User  # noqa: E402
from mcp.server import InternalMCPRegistryServer, InternalToolRegistryServer  # noqa: E402
from mcp.tools import registry_summary  # noqa: E402


class FakeResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class FakeToolSession:
    def __init__(self, rows):
        self.rows = rows

    async def get(self, model, obj_id):
        return next((row for row in self.rows.get(model, []) if getattr(row, "id", None) == obj_id), None)

    async def execute(self, stmt):
        model = stmt.column_descriptions[0]["entity"]
        rows = list(self.rows.get(model, []))
        for criterion in getattr(stmt, "_where_criteria", []):
            left_name = getattr(getattr(criterion, "left", None), "name", None)
            right = getattr(criterion, "right", None)
            value = getattr(right, "value", right)
            rows = [row for row in rows if getattr(row, left_name) == value]
        return FakeResult(rows)


def test_mcp_registry_lists_required_tools_and_gates_execution():
    summary = registry_summary()
    names = {tool["name"] for tool in summary["tools"]}

    assert summary["honest_label"] == "Internal Tool Registry"
    assert summary["remote_mcp_server"] is False
    assert "uma.list_runs" in names
    assert "uma.get_conversion_report" in names
    assert "list_connections" in names
    assert "create_replication_plan" in names
    assert "execute_approved_ddl" in names
    assert summary["arbitrary_sql_allowed"] is False

    result = InternalMCPRegistryServer().call_tool("execute_approved_ddl", {"sql": "DROP TABLE T"})
    assert result["status"] == "APPROVAL_REQUIRED"


def test_internal_tool_registry_requires_auth_for_uma_tools():
    result = asyncio.run(InternalToolRegistryServer(db=FakeToolSession({}), user=None).call_tool_async("uma.list_runs", {}))

    assert result["status"] == "AUTH_REQUIRED"


def test_internal_tool_registry_returns_real_uma_data(tmp_path):
    artifact_file = tmp_path / "report.json"
    artifact_file.write_text("{\"password\":\"secret\", \"status\":\"ok\"}", "utf-8")
    run = ControlPlaneRun(
        id="run-1",
        name="SQL Conversion",
        workflow_type="SQL_DBT_TO_SNOWFLAKE",
        status="requires_review",
        source_dialect="bigquery",
        target_dialect="snowflake",
        summary_json={"validation_status": "not_run", "password": "hidden"},
        created_at=datetime.utcnow(),
    )
    artifact = ControlPlaneArtifact(
        id="artifact-1",
        run_id="run-1",
        filename="report.json",
        original_filename="report.json",
        file_type="json",
        artifact_category="REPORT",
        storage_path=str(artifact_file),
        created_at=datetime.utcnow(),
    )
    decision = HumanReviewItem(
        id="review-1",
        run_id="run-1",
        item_type="SQL_REVIEW",
        severity="WARN",
        title="Review conversion",
        description="Needs review",
        recommendation="Fix and rerun.",
        status="NEW",
        metadata_json={},
    )
    user = User(id="user-1", email="user@example.com", name="User", role="viewer")
    server = InternalToolRegistryServer(
        db=FakeToolSession({ControlPlaneRun: [run], ControlPlaneArtifact: [artifact], HumanReviewItem: [decision]}),
        user=user,
    )

    runs = asyncio.run(server.call_tool_async("uma.list_runs", {}))
    report = asyncio.run(server.call_tool_async("uma.get_conversion_report", {"run_id": "run-1"}))
    text = asyncio.run(server.call_tool_async("uma.read_artifact", {"artifact_id": "artifact-1"}))
    decisions = asyncio.run(server.call_tool_async("uma.get_brain_review_decisions", {"run_id": "run-1"}))

    assert runs["output"]["runs"][0]["id"] == "run-1"
    assert report["output"]["report"]["validation_status"] == "not_run"
    assert "secret" not in text["output"]["text"]
    assert decisions["output"]["decisions"][0]["title"] == "Review conversion"
