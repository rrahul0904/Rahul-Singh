from __future__ import annotations

import httpx

from services.ai.providers.base import AiProvider
from services.ai.schemas import AiChatRequest, AiChatResponse, AiProviderStatus


class AnthropicProvider(AiProvider):
    mode = "anthropic"
    display_name = "Anthropic"

    async def health(self) -> AiProviderStatus:
        available = bool(self.config.api_key and self.config.model)
        return AiProviderStatus(
            active_provider=self.mode,
            available=available,
            model=self.config.model,
            chat_supported=available,
            patch_proposal_supported=available,
            structured_output_supported=False,
            local_private_mode=False,
            error=None if available else "ANTHROPIC_API_KEY is not configured.",
        )

    async def chat(self, request: AiChatRequest) -> AiChatResponse:
        if not self.config.api_key:
            return AiChatResponse("", self.mode, self.config.model, available=False, error="ANTHROPIC_API_KEY is not configured.")
        prompt = "\n\n".join([request.system, *[m.get("content", "") for m in request.messages if m.get("role") == "user"]]).strip()
        body = {"model": self.config.model, "max_tokens": request.max_tokens or self.config.max_tokens, "temperature": request.temperature if request.temperature is not None else self.config.temperature, "messages": [{"role": "user", "content": prompt}]}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": self.config.api_key, "anthropic-version": "2023-06-01"}, json=body)
            response.raise_for_status()
            raw = response.json()
            content = "".join(part.get("text", "") for part in raw.get("content", []) if isinstance(part, dict))
            return AiChatResponse(content, self.mode, self.config.model, raw=raw)
        except Exception as exc:
            return AiChatResponse("", self.mode, self.config.model, available=False, error=str(exc))
