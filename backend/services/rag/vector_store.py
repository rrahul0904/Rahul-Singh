from __future__ import annotations

from pathlib import Path
import json
import threading
import inspect
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models import RagChunkModel
from services.rag.embeddings import cosine_similarity
from services.rag.schemas import RagChunk, RagSearchResult


class LocalVectorStore:
    """Dependency-light local vector store for dev and tests.

    When `RAG_VECTOR_STORE=faiss` and faiss-cpu is installed, search uses a
    transient FAISS inner-product index over the persisted JSON chunks. If FAISS
    is unavailable, the same persisted chunks fall back to pure-Python cosine
    search so local development still starts cleanly.
    """

    _lock = threading.Lock()

    def __init__(self, path: str | None = None):
        root = Path(path or settings.RAG_INDEX_PATH or "data/rag_index")
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "chunks.json"
        self.configured_backend = (settings.RAG_VECTOR_STORE or "keyword").strip().lower()
        self.backend = self._effective_backend(self.configured_backend)

    def upsert(self, chunks: list[RagChunk]) -> int:
        with self._lock:
            rows = self._load()
            existing = {row["id"]: row for row in rows}
            for chunk in chunks:
                existing[chunk.id] = chunk.to_dict(include_embedding=True)
            self._save(list(existing.values()))
        return len(chunks)

    def delete_where(self, **filters: str | None) -> int:
        with self._lock:
            rows = self._load()
            kept = []
            deleted = 0
            for row in rows:
                metadata = row.get("metadata") or {}
                if all(value is None or str(metadata.get(key)) == str(value) for key, value in filters.items()):
                    deleted += 1
                else:
                    kept.append(row)
            self._save(kept)
        return deleted

    def count(self, **filters: str | None) -> int:
        return len(self._filter(self._load(), filters))

    def search(self, query_embedding: list[float], *, top_k: int, filters: dict[str, str | None] | None = None) -> list[RagSearchResult]:
        rows = self._filter(self._load(), filters or {})
        if (self.backend or "").lower() == "faiss":
            faiss_results = self._search_faiss(rows, query_embedding, top_k)
            if faiss_results is not None:
                return faiss_results
        scored = []
        for row in rows:
            score = cosine_similarity(query_embedding, row.get("embedding") or [])
            scored.append((
                score,
                RagChunk(
                    id=row["id"],
                    text=row.get("text") or "",
                    metadata=row.get("metadata") or {},
                    embedding=row.get("embedding") or [],
                ),
            ))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [RagSearchResult(chunk=chunk, score=score) for score, chunk in scored[: max(1, top_k)]]

    @staticmethod
    def _effective_backend(configured_backend: str) -> str:
        # pgvector/qdrant/chroma are deployment modes. If their services are not
        # wired into this lightweight dev store, UMA keeps deterministic keyword
        # retrieval available instead of failing normal conversion startup.
        if configured_backend in {"pgvector", "qdrant", "chroma"}:
            return "keyword"
        if configured_backend == "faiss":
            return "faiss"
        return "keyword"

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text("utf-8"))
        except Exception:
            return []

    def _save(self, rows: list[dict]) -> None:
        self.path.write_text(json.dumps(rows, indent=2, sort_keys=True), "utf-8")

    def _filter(self, rows: list[dict], filters: dict[str, str | None]) -> list[dict]:
        return [
            row
            for row in rows
            if all(value in {None, ""} or str((row.get("metadata") or {}).get(key)) == str(value) for key, value in filters.items())
        ]

    def _search_faiss(self, rows: list[dict[str, Any]], query_embedding: list[float], top_k: int) -> list[RagSearchResult] | None:
        try:
            import faiss  # type: ignore
            import numpy as np
        except Exception:
            return None
        vectors = [row.get("embedding") or [] for row in rows]
        if not vectors or not query_embedding:
            return []
        width = len(query_embedding)
        normalized_rows = []
        normalized_vectors = []
        for row, vector in zip(rows, vectors):
            if len(vector) == width:
                normalized_rows.append(row)
                normalized_vectors.append(vector)
        if not normalized_vectors:
            return []
        matrix = np.asarray(normalized_vectors, dtype="float32")
        faiss.normalize_L2(matrix)
        query = np.asarray([query_embedding], dtype="float32")
        faiss.normalize_L2(query)
        index = faiss.IndexFlatIP(width)
        index.add(matrix)
        scores, indices = index.search(query, min(max(1, top_k), len(normalized_rows)))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            row = normalized_rows[int(idx)]
            results.append(
                RagSearchResult(
                    chunk=RagChunk(id=row["id"], text=row.get("text") or "", metadata=row.get("metadata") or {}, embedding=row.get("embedding") or []),
                    score=float(score),
                )
            )
        return results


class PgVectorStore:
    """Postgres-backed vector store using UMA's persisted RAG chunk table.

    The current schema stores embeddings as JSON so the service can run without a
    hard pgvector Python dependency. It is still a real database-backed backend:
    indexing, run scoping, and citations survive process restarts. Similarity is
    computed in the service until a native vector column migration is enabled.
    """

    configured_backend = "pgvector"
    backend = "pgvector"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert(self, chunks: list[RagChunk]) -> int:
        for chunk in chunks:
            metadata = dict(chunk.metadata or {})
            existing = await self.db.get(RagChunkModel, chunk.id)
            if existing:
                existing.chunk_text = chunk.text
                existing.embedding = chunk.embedding
                existing.metadata_json = metadata
                existing.run_id = metadata.get("run_id")
                existing.chunk_index = int(metadata.get("chunk_index") or 0)
            else:
                self.db.add(
                    RagChunkModel(
                        id=chunk.id,
                        run_id=metadata.get("run_id"),
                        chunk_index=int(metadata.get("chunk_index") or 0),
                        chunk_text=chunk.text,
                        embedding=chunk.embedding,
                        metadata_json=metadata,
                    )
                )
        return len(chunks)

    async def delete_where(self, **filters: str | None) -> int:
        rows = await self._rows(filters)
        for row in rows:
            await self.db.delete(row)
        return len(rows)

    async def count(self, **filters: str | None) -> int:
        return len(await self._rows(filters))

    async def search(self, query_embedding: list[float], *, top_k: int, filters: dict[str, str | None] | None = None) -> list[RagSearchResult]:
        rows = await self._rows(filters or {})
        scored = []
        for row in rows:
            metadata = row.metadata_json or {}
            chunk = RagChunk(id=row.id, text=row.chunk_text or "", metadata=metadata, embedding=row.embedding or [])
            scored.append((cosine_similarity(query_embedding, chunk.embedding), chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [RagSearchResult(chunk=chunk, score=score) for score, chunk in scored[: max(1, top_k)]]

    async def _rows(self, filters: dict[str, str | None]) -> list[RagChunkModel]:
        result = await self.db.execute(select(RagChunkModel))
        rows = list(result.scalars().all())
        return [
            row
            for row in rows
            if all(value in {None, ""} or str((row.metadata_json or {}).get(key)) == str(value) for key, value in filters.items())
        ]


def vector_store_for(db: AsyncSession | None = None):
    configured = (settings.RAG_VECTOR_STORE or "keyword").strip().lower()
    if configured == "pgvector" and db is not None:
        return PgVectorStore(db)
    return LocalVectorStore()


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value
