from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import httpx

from core.config import settings
from services.ollama_provider import OllamaClient
from services.rag.redaction import redact_rag_payload


class EmbeddingProvider:
    @property
    def provider_name(self) -> str:
        return settings.RAG_EMBEDDING_PROVIDER or "offline_keyword"

    async def embed(self, text: str) -> list[float]:
        safe = str(redact_rag_payload(text or "") or "")
        mode = (settings.RAG_EMBEDDING_PROVIDER or "offline_keyword").strip().lower()
        if mode == "ollama_embeddings" and settings.OLLAMA_ENABLED:
            try:
                vector = await OllamaClient().embed(safe)
                if vector:
                    return _normalize(vector)
            except Exception:
                pass
        if mode in {"openai_compatible_embeddings", "openai_embeddings"}:
            vector = await _openai_compatible_embedding(safe)
            if vector:
                return _normalize(vector)
        return deterministic_embedding(safe, dimensions=settings.RAG_EMBEDDING_DIM or 256)


async def _openai_compatible_embedding(text: str) -> list[float]:
    base_url = (settings.AI_BASE_URL if settings.RAG_EMBEDDING_PROVIDER == "openai_compatible_embeddings" else "https://api.openai.com/v1").rstrip("/")
    api_key = settings.AI_API_KEY if settings.RAG_EMBEDDING_PROVIDER == "openai_compatible_embeddings" else settings.OPENAI_API_KEY
    model = settings.RAG_EMBEDDING_MODEL or "BAAI/bge-m3"
    if not base_url or not model:
        return []
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{base_url}/embeddings", headers=headers, json={"model": model, "input": text})
        response.raise_for_status()
        raw: dict[str, Any] = response.json()
        return list(((raw.get("data") or [{}])[0]).get("embedding") or [])
    except Exception:
        return []


def deterministic_embedding(text: str, dimensions: int = 256) -> list[float]:
    vector = [0.0] * dimensions
    tokens = re.findall(r"[A-Za-z0-9_.$]+", (text or "").lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return _normalize(vector)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    return sum(left[i] * right[i] for i in range(size))


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if not norm:
        return [0.0 for _ in vector]
    return [round(float(value) / norm, 8) for value in vector]
