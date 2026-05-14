from __future__ import annotations

from services.ai.providers.base import AiProvider
from services.ai.schemas import AiChatRequest, AiChatResponse, AiProviderStatus


class OfflineDeterministicProvider(AiProvider):
    mode = "offline_deterministic"
    display_name = "Offline deterministic"

    async def health(self) -> AiProviderStatus:
        return AiProviderStatus(
            active_provider=self.mode,
            available=True,
            model="offline",
            chat_supported=False,
            embeddings_supported=False,
            rag_supported=False,
            patch_proposal_supported=False,
            structured_output_supported=False,
            local_private_mode=True,
        )

    async def chat(self, request: AiChatRequest) -> AiChatResponse:
        return AiChatResponse(
            content="Offline deterministic mode is active. UMA did not call an LLM provider.",
            provider=self.mode,
            model="offline",
            available=False,
            error="offline_deterministic has no chat model",
        )
