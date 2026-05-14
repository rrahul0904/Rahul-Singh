from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RagChunk:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)

    def to_dict(self, *, include_embedding: bool = False) -> dict[str, Any]:
        data = {"id": self.id, "text": self.text, "metadata": self.metadata}
        if include_embedding:
            data["embedding"] = self.embedding
        return data


@dataclass
class RagSearchResult:
    chunk: RagChunk
    score: float

    def to_dict(self) -> dict[str, Any]:
        metadata = self.chunk.metadata
        return {
            "chunk_id": self.chunk.id,
            "text": self.chunk.text,
            "metadata": metadata,
            "score": round(float(self.score), 6),
            "citation": {
                "run_id": metadata.get("run_id"),
                "artifact_id": metadata.get("artifact_id"),
                "file_path": metadata.get("file_path"),
                "artifact_type": metadata.get("artifact_type"),
                "source": metadata.get("source"),
            },
        }
