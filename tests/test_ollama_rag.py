import asyncio
import os
import sys
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.sql import operators
from sqlalchemy.sql.selectable import Select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")

from agents.tools.safety import redact_secrets  # noqa: E402
from core.config import settings  # noqa: E402
from models import ControlPlaneArtifact, ControlPlaneRun, HumanReviewItem, SqlConversionMessage  # noqa: E402
from services.copilot.uma_copilot_service import OllamaCopilotProvider, UmaCopilotService  # noqa: E402
from services.migration_conversion_brain import MigrationIntelligenceEngine, OllamaLlmProvider, llm_provider_status  # noqa: E402
from services.ollama_provider import OllamaClient  # noqa: E402
from services.rag.chunker import chunk_text  # noqa: E402
from services.rag.indexer import RagIndexer  # noqa: E402
from services.rag.retriever import RagRetriever  # noqa: E402
from services.rag.schemas import RagChunk  # noqa: E402
from services.rag.vector_store import LocalVectorStore  # noqa: E402


class FakeResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class FakeRagSession:
    MODELS = (ControlPlaneRun, ControlPlaneArtifact, SqlConversionMessage, HumanReviewItem)

    def __init__(self, rows):
        self.rows = rows

    async def get(self, model, obj_id):
        for row in self.rows.get(model, []):
            if getattr(row, "id", None) == obj_id:
                return row
        return None

    async def execute(self, stmt):
        if not isinstance(stmt, Select):
            raise AssertionError(f"Unsupported statement type: {type(stmt)}")
        model = stmt.column_descriptions[0]["entity"]
        rows = [row for row in self.rows.get(model, []) if self._matches(row, stmt._where_criteria)]
        return FakeResult(rows)

    def _matches(self, row, criteria):
        for criterion in criteria:
            left_name = getattr(getattr(criterion, "left", None), "name", None)
            right = getattr(criterion, "right", None)
            if criterion.operator == operators.eq and getattr(row, left_name) != getattr(right, "value", right):
                return False
        return True


class FakeDb:
    async def get(self, *_args):
        return None


def test_ollama_provider_unavailable_fallback(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_ENABLED", False)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")

    health = asyncio.run(OllamaClient().health())

    assert health["available"] is False
    assert health["enabled"] is False
    assert "OLLAMA_ENABLED" in health["error"]


def test_ollama_provider_health_reports_missing_models(monkeypatch):
    async def fake_models(self):
        return {"llama3.1"}

    monkeypatch.setattr(settings, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(settings, "OLLAMA_CHAT_MODEL", "llama3.1")
    monkeypatch.setattr(settings, "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setattr(OllamaClient, "available_models", fake_models)

    health = asyncio.run(OllamaClient().health())

    assert health["available"] is False
    assert health["chat_model_available"] is True
    assert health["embedding_model_available"] is False


def test_rag_chunking_redacts_secret_metadata():
    chunks = chunk_text("password=supersecret token: abc123 snowflake://user:pass@acct/db", chunk_size=200)

    assert chunks
    combined = "\n".join(chunks)
    assert "supersecret" not in combined
    assert "abc123" not in combined
    assert "pass@acct" not in combined
    assert "***REDACTED***" in combined


def test_rag_retrieval_filters_by_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RAG_INDEX_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "OLLAMA_ENABLED", False)
    store = LocalVectorStore(path=str(tmp_path))
    store.upsert([
        RagChunk(id="run-1-a", text="DATE_SUB migration warning", metadata={"run_id": "run-1", "artifact_type": "REPORT"}, embedding=[1.0, 0.0]),
        RagChunk(id="run-2-a", text="unrelated validation note", metadata={"run_id": "run-2", "artifact_type": "REPORT"}, embedding=[1.0, 0.0]),
    ])

    results = asyncio.run(RagRetriever(store=store).search("DATE_SUB", run_id="run-1", top_k=5))

    assert len(results["chunks"]) == 1
    assert results["chunks"][0]["metadata"]["run_id"] == "run-1"


def test_rag_indexer_captures_artifacts_decisions_and_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RAG_INDEX_PATH", str(tmp_path / "index"))
    monkeypatch.setattr(settings, "OLLAMA_ENABLED", False)
    artifact_file = tmp_path / "orders.sql"
    artifact_file.write_text("select * from orders where password='secret-value'", "utf-8")
    run_id = str(uuid4())
    artifact_id = str(uuid4())
    run = ControlPlaneRun(
        id=run_id,
        name="run",
        workflow_type="SQL_CONVERSION",
        source_dialect="bigquery",
        target_dialect="snowflake",
        created_at=datetime.utcnow(),
        summary_json={"validation_status": "not_run", "password": "hidden"},
    )
    artifact = ControlPlaneArtifact(
        id=artifact_id,
        run_id=run_id,
        filename="orders.sql",
        original_filename="orders.sql",
        file_type="sql",
        artifact_category="SOURCE_SQL",
        storage_path=str(artifact_file),
        checksum_sha256="x",
        created_at=datetime.utcnow(),
    )
    message = SqlConversionMessage(run_id=run_id, artifact_id=artifact_id, file_name="orders.sql", severity="WARN", message="DATE_SUB residue", recommendation="Use DATEADD.")
    decision = HumanReviewItem(run_id=run_id, item_type="SQL_REVIEW", title="Review DATE_SUB", description="DATE_SUB remains.", recommendation="Convert before approval.", status="OPEN")
    db = FakeRagSession({ControlPlaneRun: [run], ControlPlaneArtifact: [artifact], SqlConversionMessage: [message], HumanReviewItem: [decision]})

    indexed = asyncio.run(RagIndexer(db).index_run(run_id))
    stored = LocalVectorStore(path=str(tmp_path / "index"))._load()

    assert indexed["indexed_artifacts"] == 1
    assert indexed["indexed_chunks"] >= 4
    assert any(row["metadata"].get("artifact_type") == "BRAIN_REVIEW_DECISION" for row in stored)
    assert "secret-value" not in "\n".join(row["text"] for row in stored)


def test_copilot_uses_rag_context_with_ollama(monkeypatch):
    async def fake_health(self, **_kwargs):
        return {"available": True, "enabled": True, "provider": "ollama"}

    async def fake_chat(self, messages, **_kwargs):
        prompt = messages[-1]["content"]
        assert "rag-chunk-1" in prompt
        assert "DATE_SUB" in prompt
        return "Use DATEADD; cited rag-chunk-1."

    async def fake_search(self, query, **_kwargs):
        return {"chunks": [{"id": "rag-chunk-1", "text": "DATE_SUB requires DATEADD.", "metadata": {"run_id": "run-1"}, "score": 0.91}]}

    monkeypatch.setattr(settings, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    monkeypatch.setattr(OllamaClient, "health", fake_health)
    monkeypatch.setattr(OllamaClient, "chat", fake_chat)
    monkeypatch.setattr(RagRetriever, "search", fake_search)

    response = asyncio.run(UmaCopilotService(FakeDb()).ask(message="How do I fix DATE_SUB?", provider_name="ollama", context={"selected_run_id": "run-1"}))

    assert response["provider"] == "ollama"
    assert "DATEADD" in response["answer"]
    assert response["source_context"]["rag"][0]["id"] == "rag-chunk-1"


def test_ai_patch_disabled_when_ollama_provider_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_ENABLED", False)

    proposal = asyncio.run(OllamaLlmProvider().propose_patch({"converted_sql": "select 1"}))
    status = llm_provider_status("ollama")

    assert proposal["available"] is False
    assert proposal["manual_review_required"] is True
    assert status["ai_patch_available"] is False


def test_ai_patch_structured_output_parsing_and_manual_gate(monkeypatch):
    async def fake_chat_json(self, messages, **_kwargs):
        return {
            "proposed_sql": "select DATEADD(DAY, -1, order_date) from orders",
            "explanation": "Replace DATE_SUB.",
            "assumptions": ["date-compatible"],
            "risks": ["review"],
            "confidence": 0.77,
            "manual_review_required": False,
        }

    async def fake_health(self, **_kwargs):
        return {"available": True, "enabled": True}

    monkeypatch.setattr(settings, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(OllamaClient, "health", fake_health)
    monkeypatch.setattr(OllamaClient, "chat_json", fake_chat_json)

    proposal = asyncio.run(OllamaLlmProvider().propose_patch({"converted_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) from orders"}))

    assert proposal["available"] is True
    assert proposal["provider"] == "ollama"
    assert "DATEADD" in proposal["proposed_sql"]
    assert proposal["manual_review_required"] is True


def test_patch_application_still_requires_confirmation():
    run = ControlPlaneRun(id="run-1", name="run", workflow_type="SQL_CONVERSION", summary_json={})

    result = asyncio.run(MigrationIntelligenceEngine(FakeDb()).apply_patch(run, patch_id="patch-1", confirmed=False))

    assert result["status"] == "CONFIRMATION_REQUIRED"


def test_accepted_ai_patch_stales_validation_and_creates_review_item():
    class PatchDb:
        def __init__(self):
            self.added = []
            self.commits = 0

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            self.commits += 1

    run = ControlPlaneRun(
        id="run-1",
        name="run",
        workflow_type="SQL_CONVERSION",
        summary_json={
            "input_type": "sql_file",
            "job_state": {"validation_status": "passed", "snowflake_ready": True, "rules_applied_count": 1},
            "conversion_context": {
                "files": [{
                    "source_path": "orders.sql",
                    "target_path": "converted/orders.sql",
                    "original_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) from orders",
                    "converted_sql": "select DATEADD(day, -1, order_date) from orders",
                    "detected_dialect": "bigquery",
                    "rules_applied": ["date_sub_to_dateadd"],
                    "warnings": [],
                    "unsupported_features": [],
                }]
            },
            "ai_patches": [{
                "patch_id": "patch-1",
                "status": "PROPOSED",
                "target_path": "converted/orders.sql",
                "source_path": "orders.sql",
                "original_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) from orders",
                "proposed_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) from orders",
            }],
        },
    )
    db = PatchDb()
    engine = MigrationIntelligenceEngine(db)

    async def fake_store_text_artifact(*_args, **_kwargs):
        return SimpleNamespace(id="artifact-1")

    engine.common.store_text_artifact = fake_store_text_artifact

    result = asyncio.run(engine.apply_patch(run, patch_id="patch-1", confirmed=True))

    assert result["status"] == "PATCH_APPLIED"
    assert result["validation_status"] == "stale_after_ai_patch"
    assert run.summary_json["job_state"]["validation_status"] == "stale_after_ai_patch"
    assert run.summary_json["job_state"]["snowflake_ready"] is False
    assert any(isinstance(obj, HumanReviewItem) and obj.item_type == "AI_PATCH_REVIEW" for obj in db.added)


def test_redact_secrets_handles_raw_text_before_indexing():
    redacted = redact_secrets("api_key=abc123 postgres://user:secret@localhost/db")

    assert "abc123" not in redacted
    assert "secret@localhost" not in redacted
