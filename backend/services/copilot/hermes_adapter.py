from __future__ import annotations

from typing import Any

import httpx

from core.config import settings
from services.copilot.base import CopilotAnswer, CopilotProvider, classify_action, payload_has_blocked_sql, safe_context


class HermesCopilotAdapter(CopilotProvider):
    name = "hermes"
    display_name = "Hermes Agent"

    def __init__(self):
        self.url = (settings.HERMES_AGENT_URL or "").rstrip("/")
        self.has_token = bool(settings.HERMES_AGENT_TOKEN)

    def _headers(self) -> dict[str, str]:
        if not self.has_token:
            return {}
        return {"Authorization": f"Bearer {settings.HERMES_AGENT_TOKEN}"}

    async def _post_json(self, path: str, payload: dict[str, Any], *, timeout: int = 30) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(f"{self.url}{path}", headers=self._headers(), json=safe_context(payload))

    async def capabilities(self) -> dict[str, Any]:
        if not self.url:
            return {"status": "STUB_UNCONFIGURED", "capabilities": []}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.url}/capabilities", headers=self._headers())
            if response.status_code >= 400:
                return {"status": "UNAVAILABLE", "status_code": response.status_code, "capabilities": []}
            data = response.json()
            return {
                "status": "AVAILABLE",
                "capabilities": safe_context(data.get("capabilities", data)),
            }
        except Exception as exc:
            return {"status": "UNREACHABLE", "error": exc.__class__.__name__, "capabilities": []}

    async def health(self) -> dict[str, Any]:
        if not self.url:
            return {
                "provider": self.name,
                "configured": False,
                "status": "STUB_UNCONFIGURED",
                "url": "",
                "token": "not_configured",
            }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.url}/health", headers=self._headers())
            capabilities = await self.capabilities()
            return {
                "provider": self.name,
                "configured": True,
                "status": "HEALTHY" if response.status_code < 400 else "UNHEALTHY",
                "url": self.url,
                "token": "configured_masked" if self.has_token else "not_configured",
                "status_code": response.status_code,
                "capabilities": capabilities,
            }
        except Exception as exc:
            return {
                "provider": self.name,
                "configured": True,
                "status": "UNREACHABLE",
                "url": self.url,
                "token": "configured_masked" if self.has_token else "not_configured",
                "error": exc.__class__.__name__,
            }

    async def send_message(self, message: str, context: dict[str, Any] | None = None) -> CopilotAnswer:
        health = await self.health()
        payload = {
            "message": message,
            "context": safe_context(context),
            "constraints": {
                "orchestrator": "UMA",
                "no_direct_sql": True,
                "approval_required_for_mutations": True,
                "secrets_available": False,
            },
        }
        if not self.url:
            return CopilotAnswer(
                provider=self.name,
                answer="Hermes adapter is installed as an optional copilot stub. Configure HERMES_AGENT_URL to forward safe, redacted UMA context.",
                source_context=safe_context(context),
                proposed_action=None,
                health=health,
            )
        try:
            proposed = None
            response = await self._post_json("/query", payload)
            if response.status_code == 404:
                response = await self._post_json("/message", payload)
            if response.status_code >= 400:
                answer = f"Hermes service returned {response.status_code}; UMA kept control of actions."
            else:
                data = response.json()
                answer = str(data.get("answer") or data.get("message") or data.get("response") or "Hermes returned no answer.")
                proposed = data.get("proposed_action")
                if proposed:
                    local_preview = await self.preview_action(str(proposed.get("action_type") or ""), proposed.get("payload") or {})
                    proposed = {
                        "action_type": proposed.get("action_type"),
                        "category": local_preview["category"],
                        "allowed": local_preview["allowed"],
                        "requires_confirmation": local_preview["requires_confirmation"],
                    }
                else:
                    proposed = None
            return CopilotAnswer(
                provider=self.name,
                answer=answer,
                source_context=safe_context(context),
                proposed_action=proposed,
                health=health,
            )
        except Exception as exc:
            return CopilotAnswer(
                provider=self.name,
                answer=f"Hermes service is unreachable ({exc.__class__.__name__}); using UMA local safety boundary.",
                source_context=safe_context(context),
                health=health,
            )

    async def preview_action(self, action_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        category = "BLOCKED" if payload_has_blocked_sql(payload) else classify_action(action_type)
        local_preview = {
            "provider": self.name,
            "action_type": action_type,
            "category": category,
            "allowed": category != "BLOCKED",
            "requires_confirmation": category == "APPROVAL_REQUIRED",
            "execution_owner": "UMA_ORCHESTRATOR",
            "payload": safe_context(payload),
        }
        if not self.url or category == "BLOCKED":
            return local_preview
        try:
            response = await self._post_json(
                "/actions/preview",
                {"action_type": action_type, "payload": safe_context(payload)},
                timeout=10,
            )
            if response.status_code < 400:
                local_preview["remote_preview"] = safe_context(response.json())
            else:
                local_preview["remote_preview"] = {"status": "UNAVAILABLE", "status_code": response.status_code}
        except Exception as exc:
            local_preview["remote_preview"] = {"status": "UNREACHABLE", "error": exc.__class__.__name__}
        return local_preview
