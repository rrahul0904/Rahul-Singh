from __future__ import annotations

from typing import Any

from services.ai.providers.openai_compatible import OpenAICompatibleProvider


class AzureOpenAIProvider(OpenAICompatibleProvider):
    mode = "azure_openai"
    display_name = "Azure OpenAI"

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "api-key": self.config.api_key}
