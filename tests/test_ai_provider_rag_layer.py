import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")

from core.config import settings  # noqa: E402
from services.ai.provider_router import AiProviderRouter, normalize_provider, resolve_provider  # noqa: E402
from services.ai.providers.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from services.ai.safety import redact_for_ai, safe_base_url  # noqa: E402
from services.rag.evidence_builder import normalize_chunk_metadata  # noqa: E402
from services.rag.schemas import RagChunk  # noqa: E402
from services.rag.vector_store import LocalVectorStore, PgVectorStore, vector_store_for  # noqa: E402


def test_provider_router_defaults_to_offline(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "offline_deterministic")

    status = asyncio.run(AiProviderRouter().status())

    assert status.active_provider == "offline_deterministic"
    assert status.available is True
    assert status.chat_supported is False
    assert status.patch_proposal_supported is False
    assert status.local_private_mode is True


def test_provider_aliases_are_not_ollama_first():
    assert normalize_provider("self_hosted") == "openai_compatible_self_hosted"
    assert normalize_provider("ollama") == "ollama_local"
    assert normalize_provider(None) == "offline_deterministic"


def test_auto_provider_selects_openai_when_key_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "auto")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "OLLAMA_ENABLED", False)
    monkeypatch.setattr(settings, "AI_BASE_URL", "")
    monkeypatch.setattr(settings, "AI_CHAT_MODEL", "")

    assert resolve_provider() == "openai"


def test_self_hosted_provider_mocked_health_success(monkeypatch):
    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, headers):
            assert url == "http://vllm:8000/v1/models"
            assert headers["Authorization"] == "Bearer local-dev-token"
            return FakeResponse()

    monkeypatch.setattr("services.ai.providers.openai_compatible.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(settings, "AI_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setattr(settings, "AI_API_KEY", "local-dev-token")
    monkeypatch.setattr(settings, "AI_CHAT_MODEL", "Qwen/Qwen2.5-Coder-32B-Instruct")

    status = asyncio.run(AiProviderRouter("openai_compatible_self_hosted").status())

    assert status.available is True
    assert status.chat_supported is True
    assert status.patch_proposal_supported is True
    assert status.local_private_mode is True
    assert status.base_url == "http://vllm:8000/v1"


def test_self_hosted_provider_unavailable_without_config(monkeypatch):
    monkeypatch.setattr(settings, "AI_BASE_URL", "")
    monkeypatch.setattr(settings, "AI_CHAT_MODEL", "")

    status = asyncio.run(AiProviderRouter("openai_compatible_self_hosted").status())

    assert status.available is False
    assert status.chat_supported is False
    assert "AI_BASE_URL" in status.error


def test_rag_metadata_has_required_fields():
    metadata = normalize_chunk_metadata({"run_id": "run-1", "artifact_type": "REPORT"})

    for key in (
        "run_id",
        "artifact_id",
        "job_id",
        "artifact_type",
        "file_path",
        "source_dialect",
        "target_dialect",
        "model_name",
        "created_at",
        "content_hash",
        "redaction_applied",
        "decision_status",
        "validation_status",
    ):
        assert key in metadata
    assert metadata["redaction_applied"] is True


def test_local_vector_store_falls_back_for_unwired_pgvector(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RAG_VECTOR_STORE", "pgvector")
    store = LocalVectorStore(path=str(tmp_path))
    store.upsert([RagChunk(id="a", text="DATE_SUB warning", metadata={"run_id": "run-1"}, embedding=[1.0])])

    assert store.configured_backend == "pgvector"
    assert store.backend == "keyword"
    assert store.count(run_id="run-1") == 1


def test_pgvector_store_selected_when_database_session_is_available(monkeypatch):
    monkeypatch.setattr(settings, "RAG_VECTOR_STORE", "pgvector")

    assert isinstance(vector_store_for(db=object()), PgVectorStore)


def test_redaction_before_prompting_blocks_common_secret_shapes():
    payload = {
        "sql": "select 'x' where password='super-secret' and api_key=abc123",
        "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
        "url": "postgres://user:secret@localhost/db",
    }

    redacted = redact_for_ai(payload)
    as_text = str(redacted)

    assert "super-secret" not in as_text
    assert "abc123" not in as_text
    assert "secret@localhost" not in as_text
    assert redacted["private_key"] == "***REDACTED***"


def test_provider_status_base_url_redacts_embedded_credentials():
    assert safe_base_url("http://user:pass@vllm:8000/v1?api_key=abc123") == "http://***:***@vllm:8000/v1?api_key=***"
