import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")

from services.copilot.base import classify_action, payload_has_blocked_sql, safe_context  # noqa: E402
from services.copilot.hermes_adapter import HermesCopilotAdapter  # noqa: E402
from services.copilot.uma_copilot_service import MockCopilotProvider  # noqa: E402
from services.snowflake_intelligence import SnowflakeIntelligenceService  # noqa: E402


def test_copilot_action_classification_enforces_safety_boundary():
    assert classify_action("get_validation_summary") == "READ_ONLY"
    assert classify_action("approve_generated_ddl") == "APPROVAL_REQUIRED"
    assert classify_action("get_snowflake_services_health") == "READ_ONLY"
    assert classify_action("search_cortex_documents") == "READ_ONLY"
    assert classify_action("direct_arbitrary_sql_execution") == "BLOCKED"
    assert classify_action("DROP DATABASE analytics") == "BLOCKED"
    assert classify_action("TRUNCATE TABLE customers") == "BLOCKED"
    assert payload_has_blocked_sql({"ddl": "DROP SCHEMA RAW"}) is True
    assert payload_has_blocked_sql({"sql": "UPDATE RAW.T SET X = 1"}) is True
    assert payload_has_blocked_sql({"sql": "UPDATE RAW.T SET X = 1 WHERE ID = 7"}) is False


def test_copilot_safe_context_redacts_secret_like_fields():
    payload = {
        "run_id": "run-1",
        "password": "secret",
        "nested": {"private_key": "key", "token": "token"},
    }

    redacted = safe_context(payload)

    assert redacted["run_id"] == "run-1"
    assert redacted["password"] == "***REDACTED***"
    assert redacted["nested"]["private_key"] == "***REDACTED***"
    assert redacted["nested"]["token"] == "***REDACTED***"


def test_hermes_adapter_stub_is_optional_and_masks_token(monkeypatch):
    monkeypatch.setattr("core.config.settings.HERMES_AGENT_URL", "")
    monkeypatch.setattr("core.config.settings.HERMES_AGENT_TOKEN", "configured-token")

    adapter = HermesCopilotAdapter()

    assert adapter.url == ""
    assert adapter.has_token is True


def test_mock_provider_previews_mutations_without_execution():
    provider = MockCopilotProvider()

    import asyncio

    preview = asyncio.run(provider.preview_action("retry_failed_step", {"token": "secret"}))

    assert preview["category"] == "APPROVAL_REQUIRED"
    assert preview["requires_confirmation"] is True
    assert preview["payload"]["token"] == "***REDACTED***"


def test_hermes_adapter_blocks_dangerous_preview_locally(monkeypatch):
    monkeypatch.setattr("core.config.settings.HERMES_AGENT_URL", "http://127.0.0.1:9")
    monkeypatch.setattr("core.config.settings.HERMES_AGENT_TOKEN", "configured-token")
    adapter = HermesCopilotAdapter()

    import asyncio

    preview = asyncio.run(adapter.preview_action("direct_arbitrary_sql_execution", {"sql": "DROP DATABASE RAW"}))

    assert preview["category"] == "BLOCKED"
    assert preview["allowed"] is False
    assert "remote_preview" not in preview


def test_snowflake_intelligence_capabilities_report_missing_connection(monkeypatch):
    class _Scalars:
        def all(self):
            return []

    class _Result:
        def scalars(self):
            return _Scalars()

    class _FakeDb:
        async def execute(self, _stmt):
            return _Result()

    monkeypatch.setattr("core.config.settings.CORTEX_ENABLED", True)
    monkeypatch.setattr("core.config.settings.CORTEX_LLM_MODEL", "snowflake-arctic")
    monkeypatch.setattr("core.config.settings.CORTEX_SEARCH_SERVICE", "")
    monkeypatch.setattr("core.config.settings.CORTEX_DOCUMENT_SEARCH_SERVICE", "")

    import asyncio

    caps = asyncio.run(SnowflakeIntelligenceService(_FakeDb()).capabilities())

    assert caps["snowflake_connection"]["status"] == "SNOWFLAKE_CONNECTION_REQUIRED"
    assert caps["cortex"]["llm"]["status"] == "READY"
    assert caps["cortex"]["search"]["status"] == "CONFIG_REQUIRED"
