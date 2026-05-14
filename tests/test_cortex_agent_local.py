import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.migration_intelligence import deterministic_migration_answer  # noqa: E402


def test_deterministic_cortex_agent_response_shape():
    response = deterministic_migration_answer(
        "Which tables need primary keys or watermarks?",
        {
            "connections": [{"name": "SF", "connector_type": "snowflake", "role": "destination", "health": "PASS"}],
            "jobs": [{"name": "CRM", "status": "READY"}],
            "runs": [],
            "ready_tables": ["public.customers"],
            "missing_primary_keys": ["public.orders"],
            "missing_watermarks": ["public.orders"],
            "plans": [{"risk_level": "LOW"}],
            "snowflake_readiness": {"status": "WARNING", "message": "Connectivity only.", "missing_permissions": []},
            "mcp_registry": {"provider": "internal_provider_neutral_registry"},
        },
    )

    assert set(response).issuperset({
        "answer",
        "confidence",
        "evidence",
        "recommended_actions",
        "blocked_items",
        "snowflake_readiness",
        "token_credit_note",
        "mcp_tool_plan",
    })
    assert "public.orders" in response["answer"]
    assert "OpenAI" in response["token_credit_note"]
    assert response["mcp_tool_plan"]["arbitrary_sql_allowed"] is False
    assert response["openai_called"] is False
    assert response["snowflake_cortex_called"] is False
    assert response["snowflake_sql_executed"] is False
    assert response["generated_code_executed"] is False
    assert "replication jobs" in response["input_metadata_used"]
