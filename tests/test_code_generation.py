import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import services.code_generation as code_generation_module  # noqa: E402
from services.code_generation import generate_code_artifact, generate_code_artifact_with_ai  # noqa: E402
from core.database import Base  # noqa: E402


def test_code_generation_returns_code_tdd_and_judge_pass():
    result = generate_code_artifact(
        "PLSQL_TO_STORED_PROCEDURE",
        prompt="Convert order processor",
        source_code="CREATE OR REPLACE PROCEDURE process_order IS BEGIN NULL; END;",
        metadata={"database": "ANALYTICS_DB", "schema": "RAW", "table_name": "orders"},
    )

    assert "generated_code" in result
    assert "technical_design_document" in result
    assert "judge_pass_review" in result
    assert result["judge_pass_review"]["scale"] == "1-5"
    assert result["execution_ready"] is False
    assert "No SQL" in " ".join(result["safety_notes"])
    assert result["basis_for_generation"] == "pasted_source_code"


def test_code_generation_persistence_models_registered():
    assert "code_generation_artifacts" in Base.metadata.tables
    assert "code_generation_judge_reviews" in Base.metadata.tables


def test_code_generation_routes_registered():
    from main import app

    paths = {route.path for route in app.routes}
    assert "/api/ai/code-generation" in paths
    assert "/api/ai/code-generation/artifacts" in paths
    assert "/api/ai/code-generation/artifacts/{artifact_id}" in paths
    assert "/api/ai/code-generation/artifacts/{artifact_id}/judge-pass" in paths
    assert "/api/ai/code-generation/artifacts/{artifact_id}/revise" in paths


def test_code_generation_can_use_ai_provider(monkeypatch):
    class FakeStatus:
        active_provider = "openai"
        available = True
        model = "gpt-test"
        chat_supported = True

    class FakeResponse:
        available = True
        provider = "openai"
        model = "gpt-test"
        content = (
            '{"generated_code":"from airflow import DAG\\n",'
            '"source_language":"requirements",'
            '"target_language":"Airflow Python DAG",'
            '"technical_design_document":{"objective":"Create DAG"},'
            '"judge_pass_review":{"scale":"1-5","initial_score":4,"status":"NEEDS_HUMAN_REVIEW"},'
            '"safety_notes":["Review only"]}'
        )

    class FakeRouter:
        def __init__(self, provider_name=None):
            self.provider_name = provider_name

        async def status(self):
            return FakeStatus()

        async def chat(self, messages, *, system="", json_mode=False, max_tokens=None, temperature=None):
            assert json_mode is True
            assert max_tokens <= 1800
            return FakeResponse()

    monkeypatch.setattr(code_generation_module, "AiProviderRouter", FakeRouter)

    result = asyncio.run(generate_code_artifact_with_ai(
        "AIRFLOW_DAG",
        prompt="Build a migration DAG",
        metadata={"dag_id": "uma_test"},
    ))

    assert result["ai_available"] is True
    assert result["llm_status"] == "AI_GENERATED"
    assert result["ai_provider_name"] == "openai"
    assert "airflow" in result["generated_code"].lower()
