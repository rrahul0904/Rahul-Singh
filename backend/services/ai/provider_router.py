from __future__ import annotations

import json
from typing import Any

from core.config import settings
from services.ai.prompts import PATCH_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT
from services.ai.providers.anthropic import AnthropicProvider
from services.ai.providers.azure_openai import AzureOpenAIProvider
from services.ai.providers.base import AiProvider
from services.ai.providers.offline import OfflineDeterministicProvider
from services.ai.providers.ollama import OllamaProvider
from services.ai.providers.openai import OpenAIProvider
from services.ai.providers.openai_compatible import OpenAICompatibleProvider
from services.ai.safety import redact_for_ai
from services.ai.schemas import AiChatRequest, AiProviderConfig, AiProviderStatus


class AiProviderRouter:
    def __init__(self, provider_name: str | None = None):
        self.provider_name = resolve_provider(provider_name)

    def provider(self) -> AiProvider:
        mode = self.provider_name
        if mode == "openai_compatible_self_hosted":
            return OpenAICompatibleProvider(_config_for(mode))
        if mode == "ollama_local":
            return OllamaProvider(_config_for(mode))
        if mode == "openai":
            return OpenAIProvider(_config_for(mode))
        if mode == "azure_openai":
            return AzureOpenAIProvider(_config_for(mode))
        if mode == "anthropic":
            return AnthropicProvider(_config_for(mode))
        return OfflineDeterministicProvider(_config_for("offline_deterministic"))

    async def status(self) -> AiProviderStatus:
        return await self.provider().health()

    async def chat(self, messages: list[dict[str, str]], *, system: str = "", json_mode: bool = False, max_tokens: int | None = None, temperature: float | None = None):
        safe_messages = redact_for_ai(messages, redact_emails=settings.AI_REDACT_EMAILS, redact_hostnames=settings.AI_REDACT_HOSTNAMES)
        return await self.provider().chat(AiChatRequest(messages=safe_messages, system=system, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature))

    async def propose_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        status = await self.status()
        if not status.chat_supported or not status.patch_proposal_supported:
            return _offline_patch(payload, status)
        schema = {
            "proposed_sql": payload.get("converted_sql") or "",
            "explanation": "",
            "changes": [],
            "assumptions": [],
            "risks": [],
            "confidence": 0.0,
            "manual_review_required": True,
            "expected_readiness_impact": "Advisory only. UMA judge gates decide readiness.",
            "citations": [],
        }
        response = await self.chat(
            [{"role": "user", "content": json.dumps({"schema": schema, "evidence": redact_for_ai(payload)}, indent=2)[:60000]}],
            system=PATCH_SYSTEM_PROMPT,
            json_mode=True,
            max_tokens=settings.AI_MAX_TOKENS,
            temperature=settings.AI_TEMPERATURE,
        )
        if not response.available:
            return _offline_patch(payload, status, response.error)
        parsed = _parse_json(response.content)
        parsed.setdefault("proposed_sql", payload.get("converted_sql") or "")
        parsed.setdefault("manual_review_required", True)
        parsed["provider"] = status.active_provider
        parsed["model"] = status.model
        parsed["available"] = True
        return redact_for_ai(parsed)

    async def semantic_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        status = await self.status()
        if not status.chat_supported:
            return {"available": False, "provider": status.active_provider, "model": status.model, "risks": [], "message": status.error or "Provider unavailable."}
        response = await self.chat(
            [{"role": "user", "content": json.dumps(redact_for_ai(payload), indent=2)[:60000]}],
            system=REVIEW_SYSTEM_PROMPT,
            json_mode=True,
            max_tokens=settings.AI_MAX_TOKENS,
            temperature=settings.AI_TEMPERATURE,
        )
        if not response.available:
            return {"available": False, "provider": status.active_provider, "model": status.model, "risks": [], "message": response.error}
        parsed = _parse_json(response.content)
        parsed["available"] = True
        parsed["provider"] = status.active_provider
        parsed["model"] = status.model
        return redact_for_ai(parsed)


def normalize_provider(provider: str | None) -> str:
    value = (provider or "offline_deterministic").strip().lower()
    aliases = {
        "configured": "auto",
        "offline": "offline_deterministic",
        "mock": "offline_deterministic",
        "local": "openai_compatible_self_hosted",
        "self_hosted": "openai_compatible_self_hosted",
        "openai_compatible": "openai_compatible_self_hosted",
        "ollama": "ollama_local",
    }
    return aliases.get(value, value)


def _configured_secret(value: str | None) -> bool:
    normalized = (value or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return not (
        lowered.startswith("your_")
        or lowered.startswith("replace")
        or lowered in {"change-me", "changeme", "placeholder", "none", "null"}
    )


def resolve_provider(provider: str | None = None) -> str:
    requested = (provider or "").strip().lower()
    if requested and requested not in {"auto", "configured"}:
        return normalize_provider(requested)
    configured = normalize_provider(settings.AI_PROVIDER or "offline_deterministic")
    if configured == "offline_deterministic":
        return configured
    if configured not in {"", "auto", "configured"}:
        return configured
    if _configured_secret(settings.OPENAI_API_KEY):
        return "openai"
    if _configured_secret(settings.AZURE_OPENAI_API_KEY) and settings.AZURE_OPENAI_ENDPOINT:
        return "azure_openai"
    if _configured_secret(settings.ANTHROPIC_API_KEY):
        return "anthropic"
    if settings.OLLAMA_ENABLED:
        return "ollama_local"
    if settings.AI_BASE_URL and settings.AI_CHAT_MODEL:
        return "openai_compatible_self_hosted"
    return "offline_deterministic"


def _config_for(mode: str) -> AiProviderConfig:
    if mode == "openai_compatible_self_hosted":
        return AiProviderConfig(mode=mode, base_url=settings.AI_BASE_URL, api_key=settings.AI_API_KEY, model=settings.AI_CHAT_MODEL, timeout=settings.AI_TIMEOUT_SECONDS, max_tokens=settings.AI_MAX_TOKENS, temperature=settings.AI_TEMPERATURE, structured_output_supported=settings.AI_STRUCTURED_OUTPUT_SUPPORTED)
    if mode == "ollama_local":
        return AiProviderConfig(mode=mode, base_url=settings.OLLAMA_BASE_URL, model=settings.OLLAMA_CHAT_MODEL, timeout=settings.OLLAMA_TIMEOUT_SECONDS, max_tokens=settings.AI_MAX_TOKENS, temperature=settings.AI_TEMPERATURE)
    if mode == "openai":
        return AiProviderConfig(mode=mode, base_url="https://api.openai.com/v1", api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL, timeout=settings.AI_TIMEOUT_SECONDS, max_tokens=settings.AI_MAX_TOKENS, temperature=settings.AI_TEMPERATURE, structured_output_supported=True)
    if mode == "azure_openai":
        endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        base = f"{endpoint}/openai/deployments/{settings.AZURE_OPENAI_DEPLOYMENT}" if endpoint else ""
        return AiProviderConfig(mode=mode, base_url=base, api_key=settings.AZURE_OPENAI_API_KEY, model=settings.AZURE_OPENAI_DEPLOYMENT, timeout=settings.AI_TIMEOUT_SECONDS, max_tokens=settings.AI_MAX_TOKENS, temperature=settings.AI_TEMPERATURE, structured_output_supported=True)
    if mode == "anthropic":
        return AiProviderConfig(mode=mode, api_key=settings.ANTHROPIC_API_KEY, model=settings.ANTHROPIC_MODEL, timeout=settings.AI_TIMEOUT_SECONDS, max_tokens=settings.AI_MAX_TOKENS, temperature=settings.AI_TEMPERATURE)
    if mode == "snowflake_cortex_later":
        return AiProviderConfig(mode=mode, model="snowflake_cortex_later")
    return AiProviderConfig(mode="offline_deterministic", model="offline")


def _parse_json(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def parse_provider_json(content: str) -> dict[str, Any]:
    return _parse_json(content)


def _offline_patch(payload: dict[str, Any], status: AiProviderStatus, error: str | None = None) -> dict[str, Any]:
    return {
        "provider": status.active_provider,
        "model": status.model,
        "available": False,
        "proposed_sql": payload.get("converted_sql") or "",
        "explanation": "AI patching is unavailable; deterministic conversion output was retained.",
        "changes": [],
        "assumptions": [],
        "risks": [error or status.error or "No capable AI provider is configured."],
        "confidence": 0.0,
        "manual_review_required": True,
        "expected_readiness_impact": "None. UMA judge gates remain unchanged.",
        "citations": [],
    }


async def active_provider_status(provider_name: str | None = None) -> dict[str, Any]:
    return (await AiProviderRouter(provider_name).status()).to_dict()
