from __future__ import annotations

import json
from typing import Any

from services.ai.schemas import AiChatRequest, AiChatResponse, AiProviderConfig, AiProviderStatus
from services.ai.safety import safe_base_url


class AiProvider:
    mode = "offline_deterministic"
    display_name = "Offline deterministic"

    def __init__(self, config: AiProviderConfig):
        self.config = config

    async def health(self) -> AiProviderStatus:
        return AiProviderStatus(
            active_provider=self.mode,
            available=False,
            model=self.config.model or "offline",
            base_url=safe_base_url(self.config.base_url),
            local_private_mode=True,
        )

    async def chat(self, request: AiChatRequest) -> AiChatResponse:
        return AiChatResponse(
            content="",
            provider=self.mode,
            model=self.config.model or "offline",
            available=False,
            error="Provider does not support chat.",
        )

    async def chat_json(self, request: AiChatRequest) -> dict[str, Any]:
        response = await self.chat(AiChatRequest(**{**request.__dict__, "json_mode": True}))
        if not response.available:
            raise RuntimeError(response.error or "Provider unavailable")
        try:
            return json.loads(_strip_json_fence(response.content))
        except Exception as exc:
            raise ValueError(f"Provider returned non-JSON content: {exc}") from exc


def _strip_json_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lower().startswith("json"):
            value = value[4:]
    return value.strip()
