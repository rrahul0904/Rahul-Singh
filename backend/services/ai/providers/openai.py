from __future__ import annotations

from services.ai.providers.openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    mode = "openai"
    display_name = "OpenAI"
