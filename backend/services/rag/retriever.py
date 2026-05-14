from __future__ import annotations

from core.config import settings
from services.rag.embeddings import EmbeddingProvider
from services.rag.vector_store import LocalVectorStore, maybe_await, vector_store_for


class RagRetriever:
    def __init__(self, store: LocalVectorStore | None = None, embedder: EmbeddingProvider | None = None, db=None):
        self.store = store or vector_store_for(db)
        self.embedder = embedder or EmbeddingProvider()

    async def search(
        self,
        query: str,
        *,
        run_id: str | None = None,
        job_id: str | None = None,
        artifact_type: str | None = None,
        top_k: int | None = None,
    ) -> dict:
        embedding = await self.embedder.embed(query)
        filters = {"run_id": run_id, "job_id": job_id, "artifact_type": artifact_type}
        results = await maybe_await(self.store.search(
            embedding,
            top_k=top_k or settings.RAG_MAX_RESULTS,
            filters={key: value for key, value in filters.items() if value},
        ))
        return {
            "query": query,
            "embedding_provider": self.embedder.provider_name,
            "vector_store": getattr(self.store, "configured_backend", self.store.backend),
            "effective_vector_store": self.store.backend,
            "chunks": [result.to_dict() for result in results],
        }
