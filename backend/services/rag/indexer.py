from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.tools.safety import redact_secrets
from models import ControlPlaneArtifact, ControlPlaneRun, HumanReviewItem, SqlConversionMessage
from services.control_plane import read_artifact_text
from services.rag.chunker import chunk_text
from services.rag.embeddings import EmbeddingProvider
from services.rag.evidence_builder import normalize_chunk_metadata
from services.rag.schemas import RagChunk
from services.rag.vector_store import LocalVectorStore, maybe_await, vector_store_for


class RagIndexer:
    def __init__(self, db: AsyncSession, store: LocalVectorStore | None = None, embedder: EmbeddingProvider | None = None):
        self.db = db
        self.store = store or vector_store_for(db)
        self.embedder = embedder or EmbeddingProvider()

    async def index_artifact(self, artifact_id: str) -> dict[str, Any]:
        artifact = await self.db.get(ControlPlaneArtifact, artifact_id)
        if not artifact:
            return {"status": "NOT_FOUND", "artifact_id": artifact_id, "indexed_chunks": 0}
        await maybe_await(self.store.delete_where(artifact_id=artifact.id))
        chunks = await self._chunks_for_document(
            read_artifact_text(artifact),
            {
                "source": "artifact",
                "run_id": artifact.run_id,
                "artifact_id": artifact.id,
                "file_path": artifact.original_filename,
                "artifact_type": artifact.artifact_category,
                "content_hash": artifact.checksum_sha256,
                "redaction_applied": True,
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            },
        )
        indexed = await maybe_await(self.store.upsert(chunks))
        if getattr(self.store, "backend", "") == "pgvector":
            await self.db.commit()
        return {"status": "INDEXED", "artifact_id": artifact.id, "indexed_chunks": indexed}

    async def index_run(self, run_id: str) -> dict[str, Any]:
        run = await self.db.get(ControlPlaneRun, run_id)
        if not run:
            return {"status": "NOT_FOUND", "run_id": run_id, "indexed_chunks": 0}
        await maybe_await(self.store.delete_where(run_id=run.id))
        all_chunks: list[RagChunk] = []
        base = {
            "run_id": run.id,
            "source_dialect": run.source_dialect,
            "target_dialect": run.target_dialect,
            "job_id": run.id,
            "model_name": None,
            "redaction_applied": True,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "validation_status": (run.summary_json or {}).get("validation_status") or ((run.summary_json or {}).get("validation") or {}).get("validation_status"),
        }
        all_chunks.extend(
            await self._chunks_for_document(
                json.dumps(redact_secrets(run.summary_json or {}), indent=2, sort_keys=True),
                {**base, "source": "run_summary", "artifact_type": "RUN_SUMMARY", "file_path": f"run:{run.id}"},
            )
        )

        artifacts = (await self.db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id == run.id))).scalars().all()
        for artifact in artifacts:
            all_chunks.extend(
                await self._chunks_for_document(
                    read_artifact_text(artifact),
                    {
                        **base,
                        "source": "artifact",
                        "artifact_id": artifact.id,
                        "file_path": artifact.original_filename,
                        "artifact_type": artifact.artifact_category,
                        "content_hash": artifact.checksum_sha256,
                        "created_at": artifact.created_at.isoformat() if artifact.created_at else base["created_at"],
                    },
                )
            )

        messages = (await self.db.execute(select(SqlConversionMessage).where(SqlConversionMessage.run_id == run.id))).scalars().all()
        for msg in messages:
            all_chunks.extend(
                await self._chunks_for_document(
                    f"{msg.severity}: {msg.message}\nRecommendation: {msg.recommendation}",
                    {
                        **base,
                        "source": "sql_conversion_message",
                        "artifact_id": msg.artifact_id,
                        "file_path": msg.file_name,
                        "artifact_type": "SQL_CONVERSION_MESSAGE",
                    },
                )
            )

        decisions = (await self.db.execute(select(HumanReviewItem).where(HumanReviewItem.run_id == run.id))).scalars().all()
        for item in decisions:
            all_chunks.extend(
                await self._chunks_for_document(
                    f"{item.title}\n{item.description}\nRecommendation: {item.recommendation}\nReviewer: {item.reviewer_comment or ''}",
                    {
                        **base,
                        "source": "brain_review_decision",
                        "artifact_type": "BRAIN_REVIEW_DECISION",
                        "file_path": item.title,
                        "decision_status": item.status,
                    },
                )
            )

        validation = (run.summary_json or {}).get("validation") or {}
        if validation or (run.summary_json or {}).get("validation_status"):
            all_chunks.extend(
                await self._chunks_for_document(
                    json.dumps(redact_secrets({"validation": validation, "validation_status": (run.summary_json or {}).get("validation_status")}), indent=2, sort_keys=True),
                    {**base, "source": "validation_result", "artifact_type": "VALIDATION_RESULT", "file_path": f"validation:{run.id}"},
                )
            )

        for patch in (run.summary_json or {}).get("ai_patches") or []:
            if patch.get("status") not in {"APPLIED", "ACCEPTED"}:
                continue
            all_chunks.extend(
                await self._chunks_for_document(
                    json.dumps(redact_secrets(patch), indent=2, sort_keys=True),
                    {
                        **base,
                        "source": "accepted_patch",
                        "artifact_type": "ACCEPTED_PATCH",
                        "file_path": patch.get("target_path") or patch.get("selected_file"),
                    },
                )
            )

        indexed = await maybe_await(self.store.upsert(all_chunks))
        if getattr(self.store, "backend", "") == "pgvector":
            await self.db.commit()
        return {
            "status": "INDEXED",
            "run_id": run.id,
            "indexed_chunks": indexed,
            "indexed_artifacts": len(artifacts),
            "last_indexed_at": datetime.utcnow().isoformat(),
        }

    async def _chunks_for_document(self, text: str, metadata: dict[str, Any]) -> list[RagChunk]:
        rows: list[RagChunk] = []
        for index, chunk in enumerate(chunk_text(text)):
            chunk_id = _chunk_id(chunk, metadata, index)
            rows.append(
                RagChunk(
                    id=chunk_id,
                    text=chunk,
                    metadata=normalize_chunk_metadata({**{k: v for k, v in metadata.items() if v is not None}, "chunk_index": index}),
                    embedding=await self.embedder.embed(chunk),
                )
            )
        return rows


def _chunk_id(text: str, metadata: dict[str, Any], index: int) -> str:
    raw = json.dumps([metadata.get("run_id"), metadata.get("artifact_id"), metadata.get("source"), metadata.get("file_path"), index, text[:120]], sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
