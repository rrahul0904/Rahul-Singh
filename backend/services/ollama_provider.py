from __future__ import annotations

from typing import Any
import json

import httpx

from agents.tools.safety import redact_secrets
from core.config import settings


class OllamaClient:
    """Small native Ollama API client used only for local/private inference."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        chat_model: str | None = None,
        embedding_model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")
        self.chat_model = chat_model or settings.OLLAMA_CHAT_MODEL
        self.embedding_model = embedding_model or settings.OLLAMA_EMBEDDING_MODEL
        self.timeout_seconds = int(timeout_seconds or settings.OLLAMA_TIMEOUT_SECONDS or 30)

    async def tags(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return response.json()

    async def available_models(self) -> set[str]:
        data = await self.tags()
        models = data.get("models") or []
        names = {str(row.get("name") or "").split(":")[0] for row in models if row.get("name")}
        names.update({str(row.get("name") or "") for row in models if row.get("name")})
        return {name for name in names if name}

    async def health(self, *, test_generation: bool = False, test_embedding: bool = False) -> dict[str, Any]:
        if not settings.OLLAMA_ENABLED:
            return {
                "available": False,
                "enabled": False,
                "base_url": self.base_url,
                "chat_model": self.chat_model,
                "embedding_model": self.embedding_model,
                "error": "OLLAMA_ENABLED is false.",
            }
        try:
            models = await self.available_models()
            chat_ok = bool(self.chat_model and (self.chat_model in models or self.chat_model.split(":")[0] in models))
            embedding_ok = bool(self.embedding_model and (self.embedding_model in models or self.embedding_model.split(":")[0] in models))
            generation_ok = None
            embedding_test_ok = None
            if test_generation and chat_ok:
                generated = await self.chat_json(
                    [
                        {"role": "system", "content": "Return short JSON only."},
                        {"role": "user", "content": "{\"ok\": true}"},
                    ],
                    fallback_key="health",
                )
                generation_ok = bool(generated)
            if test_embedding and embedding_ok:
                embedding_test_ok = bool(await self.embed("health check"))
            return {
                "available": chat_ok and embedding_ok,
                "enabled": True,
                "base_url": self.base_url,
                "chat_model": self.chat_model,
                "embedding_model": self.embedding_model,
                "chat_model_available": chat_ok,
                "embedding_model_available": embedding_ok,
                "test_generation": generation_ok,
                "test_embedding": embedding_test_ok,
                "models": sorted(models),
                "error": "" if chat_ok and embedding_ok else "Configured Ollama model was not found.",
            }
        except Exception as exc:
            return {
                "available": False,
                "enabled": True,
                "base_url": self.base_url,
                "chat_model": self.chat_model,
                "embedding_model": self.embedding_model,
                "error": str(exc),
            }

    async def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> str:
        payload = {
            "model": self.chat_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=redact_secrets(payload))
            response.raise_for_status()
            data = response.json()
        return str((data.get("message") or {}).get("content") or data.get("response") or "").strip()

    async def chat_json(self, messages: list[dict[str, str]], *, fallback_key: str = "answer") -> dict[str, Any]:
        content = await self.chat(messages)
        try:
            return json.loads(_extract_json(content))
        except Exception:
            return {fallback_key: content}

    async def embed(self, text: str) -> list[float]:
        payload = {"model": self.embedding_model, "prompt": text[:8000]}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/api/embeddings", json=redact_secrets(payload))
            response.raise_for_status()
            data = response.json()
        return [float(value) for value in data.get("embedding") or []]


def _extract_json(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("```")).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text
