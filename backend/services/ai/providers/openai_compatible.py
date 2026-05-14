from __future__ import annotations

from typing import Any

import httpx

from core.config import settings
from services.ai.providers.base import AiProvider
from services.ai.schemas import AiChatRequest, AiChatResponse, AiProviderStatus
from services.ai.safety import safe_base_url


class OpenAICompatibleProvider(AiProvider):
    mode = "openai_compatible_self_hosted"
    display_name = "Self-hosted OpenAI-compatible"

    async def health(self) -> AiProviderStatus:
        base = self.config.base_url.rstrip("/")
        if not base or not self.config.model:
            return self._status(False, error="AI_BASE_URL and AI_CHAT_MODEL are required.")
        try:
            async with httpx.AsyncClient(timeout=min(self.config.timeout, 15)) as client:
                response = await client.get(f"{base}/models", headers=self._headers())
            if response.status_code >= 400:
                return self._status(False, error=f"Provider health failed with HTTP {response.status_code}.")
            return self._status(True)
        except Exception as exc:
            return self._status(False, error=str(exc))

    async def chat(self, request: AiChatRequest) -> AiChatResponse:
        base = self.config.base_url.rstrip("/")
        if not base:
            return AiChatResponse("", self.mode, self.config.model, available=False, error="AI_BASE_URL is not configured.")
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend(request.messages)
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": request.temperature if request.temperature is not None else self.config.temperature,
            "max_tokens": request.max_tokens or self.config.max_tokens,
        }
        if request.json_mode and self.config.structured_output_supported:
            body["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(f"{base}/chat/completions", headers=self._headers(), json=body)
            response.raise_for_status()
            raw = response.json()
            choice = (raw.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or choice.get("text") or ""
            return AiChatResponse(content=content, provider=self.mode, model=self.config.model, raw=raw)
        except Exception as exc:
            return AiChatResponse("", self.mode, self.config.model, available=False, error=str(exc))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _status(self, available: bool, error: str | None = None) -> AiProviderStatus:
        embedding_provider = (settings.RAG_EMBEDDING_PROVIDER or "").strip().lower()
        if self.mode == "openai":
            embeddings_configured = embedding_provider == "openai_embeddings" and bool(self.config.api_key and settings.RAG_EMBEDDING_MODEL)
            local_private_mode = False
        else:
            embeddings_configured = embedding_provider == "openai_compatible_embeddings" and bool(settings.AI_BASE_URL and settings.RAG_EMBEDDING_MODEL)
            local_private_mode = True
        return AiProviderStatus(
            active_provider=self.mode,
            available=available,
            model=self.config.model,
            base_url=safe_base_url(self.config.base_url),
            chat_supported=available,
            embeddings_supported=embeddings_configured,
            rag_supported=bool(settings.RAG_ENABLED and embeddings_configured),
            patch_proposal_supported=available,
            structured_output_supported=self.config.structured_output_supported,
            local_private_mode=local_private_mode,
            error=error,
        )
