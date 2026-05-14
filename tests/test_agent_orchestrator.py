import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")

from agents.state import AgentRunStart, MigrationState  # noqa: E402
from agents.cortex_agent import CortexMigrationAgent, SnowflakeReadiness  # noqa: E402
from agents.tools.cost_tools import estimate_snowflake_cost, snowflake_intelligence_plan  # noqa: E402
from agents.tools.ddl_tools import generate_snowflake_ddl  # noqa: E402
from agents.tools.load_tools import plan_data_movement  # noqa: E402
from agents.tools.safety import (  # noqa: E402
    is_read_only_sql,
    redact_secrets,
    requires_approval,
    validate_allowed_schema,
)


def test_agent_state_supports_requested_migration_shape():
    body = AgentRunStart(
        request_text="Migrate Teradata CRM to Snowflake",
        source_type="teradata",
        target_type="snowflake",
        schemas=["CRM"],
        migration_type="incremental",
        data_volume_tb=2.5,
    )

    state = MigrationState(run_id="run-test", **body.model_dump())

    assert state.source_type == "teradata"
    assert state.target_type == "snowflake"
    assert state.schemas == ["CRM"]
    assert state.migration_type == "incremental"


def test_agent_safety_blocks_dangerous_sql_and_redacts_secrets():
    assert is_read_only_sql("SELECT * FROM CRM.ACCOUNTS") is True
    assert is_read_only_sql("DELETE FROM CRM.ACCOUNTS") is False
    assert is_read_only_sql("UPDATE CRM.ACCOUNTS SET NAME = 'x'") is False
    assert requires_approval("execute_approved_ddl") is True
    assert validate_allowed_schema("CRM") is True
    assert validate_allowed_schema("information_schema") is False
    assert redact_secrets({"password": "snowflake-password"})["password"] == "***REDACTED***"


def test_orchestrator_tools_stage_real_control_plane_outputs():
    obj = {"schema": "CRM", "name": "ACCOUNTS", "type": "table"}

    ddl = generate_snowflake_ddl(obj, "teradata")
    load_plan = plan_data_movement(
        discovered_objects=[obj],
        migration_type="incremental",
        data_volume_tb=1.5,
    )
    cost = estimate_snowflake_cost(
        data_volume_tb=1.5,
        migration_type="incremental",
        object_count=1,
    )
    snowflake_plan = snowflake_intelligence_plan()

    assert "CREATE TABLE IF NOT EXISTS" in ddl["converted_ddl"]
    assert ddl["manual_review_required"] is True
    assert load_plan["strategy"] == "merge_watermark_incremental"
    assert "COPY INTO" in load_plan["snowflake_load_methods"]
    assert cost["estimated_credits"] > 0
    assert snowflake_plan["cortex_search"]["status"] == "planned"
    assert snowflake_plan["spcs"]["runtime"] == "UMA deterministic workflow worker container"


def test_cortex_agent_runs_without_live_snowflake_credentials():
    agent = CortexMigrationAgent()
    result = agent.run(
        message="Plan Cortex agent architecture, permissions, credits, tokens, and MCP server",
        readiness=SnowflakeReadiness(configured_connections=0, healthy_connections=0),
        context={"schemas": ["CRM"]},
    )

    assert result["status"] == "READY_LOCAL_AGENT"
    assert result["snowflake_readiness"]["status"] == "SNOWFLAKE_CONNECTION_REQUIRED"
    assert result["credit_estimate"]["cortex_credits"].startswith("0 until")
    assert result["token_estimate"]["estimated_input_tokens"] > 0
    assert result["mcp_server"]["can_create"] is True
    assert any(step["name"] == "execute_snowflake_actions" and step["status"] == "BLOCKED" for step in result["steps"])


def test_cortex_agent_does_not_enable_execution_on_health_check_only():
    agent = CortexMigrationAgent()
    result = agent.run(
        message="Can I run Snowflake execution?",
        readiness=SnowflakeReadiness(configured_connections=1, healthy_connections=1),
    )

    assert result["snowflake_readiness"]["status"] == "CONNECTION_HEALTHY_PERMISSIONS_UNVERIFIED"
    assert result["snowflake_readiness"]["live_execution_enabled"] is False
    assert any(step["name"] == "execute_snowflake_actions" and step["status"] == "BLOCKED" for step in result["steps"])
