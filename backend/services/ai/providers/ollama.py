from __future__ import annotations

from services.ai.providers.base import AiProvider
from services.ai.schemas import AiChatRequest, AiChatResponse, AiProviderStatus
from core.config import settings
from services.ollama_provider import OllamaClient


class OllamaProvider(AiProvider):
    mode = "ollama_local"
    display_name = "Ollama local"

    def __init__(self, config):
        super().__init__(config)
        self.client = OllamaClient()

    async def health(self) -> AiProviderStatus:
        health = await self.client.health(test_generation=False, test_embedding=False)
        available = bool(health.get("available"))
        embeddings_supported = bool(health.get("embedding_model"))
        return AiProviderStatus(
            active_provider=self.mode,
            available=available,
            model=self.client.chat_model,
            base_url=health.get("base_url") or "",
            chat_supported=available,
            embeddings_supported=embeddings_supported,
            rag_supported=bool(settings.RAG_ENABLED and embeddings_supported),
            patch_proposal_supported=available,
            structured_output_supported=False,
            local_private_mode=True,
            quality_warning="Local model quality depends on installed model.",
            error=health.get("error"),
        )

    async def chat(self, request: AiChatRequest) -> AiChatResponse:
        health = await self.health()
        if not health.available:
            return AiChatResponse("", self.mode, self.client.chat_model, available=False, error=health.error or "Ollama unavailable")
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend(request.messages)
        try:
            if request.json_mode:
                parsed = await self.client.chat_json(messages)
                import json
                return AiChatResponse(json.dumps(parsed), self.mode, self.client.chat_model)
            return AiChatResponse(await self.client.chat(messages), self.mode, self.client.chat_model)
        except Exception as exc:
            return AiChatResponse("", self.mode, self.client.chat_model, available=False, error=str(exc))
