from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_editor
from core.config import settings
from core.database import get_db
from models import User
from services.rag import RagIndexer, RagRetriever
from services.rag.vector_store import maybe_await, vector_store_for

router = APIRouter()


@router.post("/index/run/{run_id}")
async def index_run(run_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    return await RagIndexer(db).index_run(run_id)


@router.post("/index/artifact/{artifact_id}")
async def index_artifact(artifact_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    return await RagIndexer(db).index_artifact(artifact_id)


@router.get("/search")
async def search(
    query: str = Query(min_length=1, max_length=4000),
    run_id: str | None = None,
    job_id: str | None = None,
    artifact_type: str | None = None,
    top_k: int = Query(default=0, ge=0, le=50),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await RagRetriever(db=db).search(
        query,
        run_id=run_id,
        job_id=job_id,
        artifact_type=artifact_type,
        top_k=top_k or settings.RAG_MAX_RESULTS,
    )


@router.get("/status")
async def status(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    store = vector_store_for(db)
    production_backends = {"pgvector", "qdrant"}
    embedding_ready = (settings.RAG_EMBEDDING_PROVIDER or "offline_keyword") != "offline_keyword"
    production_ready = settings.RAG_ENABLED and settings.RAG_VECTOR_STORE in production_backends and store.backend == settings.RAG_VECTOR_STORE and embedding_ready
    chunk_count = await maybe_await(store.count())
    return {
        "enabled": settings.RAG_ENABLED,
        "vector_store": settings.RAG_VECTOR_STORE,
        "effective_vector_store": store.backend,
        "production_ready": production_ready,
        "mode": "production_provider" if production_ready else "dev_local_fallback",
        "unavailable_reason": "" if production_ready else "Production RAG requires RAG_ENABLED=true, pgvector or Qdrant as the effective backend, and a non-offline embedding provider.",
        "provider_requirements": ["pgvector or Qdrant backend", "non-offline embedding provider", "run-scoped search", "artifact metadata", "chunk citations", "redaction before indexing"],
        "index_path": settings.RAG_INDEX_PATH,
        "chunks": chunk_count,
        "embedding_provider": settings.RAG_EMBEDDING_PROVIDER,
        "embedding_model": settings.RAG_EMBEDDING_MODEL,
        "top_k": settings.RAG_TOP_K,
        "indexed_artifact_count": chunk_count,
        "last_indexed_time": "",
    }
