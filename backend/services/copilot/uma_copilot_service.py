from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.migration_graph import continue_after_approval, retry_agent_run, serialize_run
from agents.tools.safety import redact_secrets
from core.config import settings
from models import (
    AgentRun,
    Job,
    JobLog,
    MigrationCostEstimate,
    MigrationRun,
    MigrationValidationResult,
    User,
)
from services.copilot.base import (
    APPROVAL_REQUIRED_ACTIONS,
    BLOCKED_ACTIONS,
    READ_ONLY_ACTIONS,
    CopilotAnswer,
    classify_action,
    payload_has_blocked_sql,
    safe_context,
)
from services.copilot.cortex_provider import CortexCopilotProvider
from services.copilot.hermes_adapter import HermesCopilotAdapter
from services.ai import AiProviderRouter, normalize_provider, resolve_provider
from services.ai.prompts import COPILOT_SYSTEM_PROMPT
from services.ollama_provider import OllamaClient
from services.rag.retriever import RagRetriever
from services.snowflake_intelligence import SnowflakeIntelligenceService


class MockCopilotProvider:
    name = "mock"
    display_name = "Mock Copilot"

    async def health(self) -> dict[str, Any]:
        return {"provider": self.name, "status": "HEALTHY", "configured": True}

    async def send_message(self, message: str, context: dict[str, Any] | None = None) -> CopilotAnswer:
        return CopilotAnswer(
            provider=self.name,
            answer="Mock copilot response grounded in UMA control-plane metadata. No external provider was called.",
            source_context=safe_context(context),
            proposed_action=_infer_proposed_action(message),
            health=await self.health(),
        )

    async def preview_action(self, action_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        category = "BLOCKED" if payload_has_blocked_sql(payload) else classify_action(action_type)
        return {
            "provider": self.name,
            "action_type": action_type,
            "category": category,
            "allowed": category != "BLOCKED",
            "requires_confirmation": category == "APPROVAL_REQUIRED",
            "payload": safe_context(payload),
        }


class ConfigOnlyCopilotProvider(MockCopilotProvider):
    def __init__(self, name: str, display_name: str, configured: bool):
        self.name = name
        self.display_name = display_name
        self._configured = configured

    async def health(self) -> dict[str, Any]:
        return {"provider": self.name, "status": "CONFIGURED" if self._configured else "NOT_CONFIGURED", "configured": self._configured}


class OllamaCopilotProvider(MockCopilotProvider):
    name = "ollama"
    display_name = "Ollama Local"

    def __init__(self) -> None:
        self.client = OllamaClient()

    async def health(self) -> dict[str, Any]:
        return await self.client.health(test_generation=False, test_embedding=False)

    async def send_message(self, message: str, context: dict[str, Any] | None = None) -> CopilotAnswer:
        health = await self.health()
        if not health.get("available"):
            return CopilotAnswer(
                provider=self.name,
                answer="Ollama Local is not available. UMA stayed in deterministic mode and did not call an external provider.",
                grounded=True,
                source_context=safe_context(context),
                proposed_action=_infer_proposed_action(message),
                health=health,
            )
        prompt = (
            "You are UMA Copilot running on local Ollama. Use only the redacted UMA context and RAG chunks. "
            "Cite evidence by chunk_id or artifact/run id when possible. Do not claim Snowflake readiness unless validation evidence says so.\n\n"
            f"Question:\n{message}\n\nContext:\n{redact_secrets(context or {})}"
        )
        answer = await self.client.chat([
            {"role": "system", "content": "Answer as a concise enterprise migration assistant."},
            {"role": "user", "content": prompt[:24000]},
        ])
        return CopilotAnswer(
            provider=self.name,
            answer=answer or "Ollama returned an empty answer.",
            source_context=safe_context(context),
            proposed_action=_infer_proposed_action(message),
            health=health,
        )


class RouterCopilotProvider(MockCopilotProvider):
    def __init__(self, provider_name: str | None = None):
        self.router = AiProviderRouter(provider_name)
        self.name = self.router.provider_name
        display_names = {
            "openai": "OpenAI",
            "openai_compatible_self_hosted": "Self-hosted Open Model",
        }
        self.display_name = display_names.get(self.name, self.name.replace("_", " ").title())

    async def health(self) -> dict[str, Any]:
        return (await self.router.status()).to_dict()

    async def send_message(self, message: str, context: dict[str, Any] | None = None) -> CopilotAnswer:
        health = await self.health()
        if not health.get("chat_supported"):
            return CopilotAnswer(
                provider=self.name,
                answer="AI provider is unavailable. UMA answered in deterministic mode from local state only.",
                source_context=safe_context(context),
                proposed_action=_infer_proposed_action(message),
                health=health,
            )
        response = await self.router.chat(
            [{"role": "user", "content": json.dumps({"question": message, "context": redact_secrets(context or {})}, indent=2)[:60000]}],
            system=COPILOT_SYSTEM_PROMPT,
            max_tokens=settings.AI_MAX_TOKENS,
            temperature=settings.AI_TEMPERATURE,
        )
        answer = response.content if response.available else f"Provider unavailable: {response.error}"
        return CopilotAnswer(
            provider=self.name,
            answer=answer,
            source_context=safe_context(context),
            proposed_action=_infer_proposed_action(message),
            health=health,
        )


def _infer_proposed_action(message: str) -> dict[str, Any] | None:
    text = (message or "").lower()
    if "retry" in text:
        return {"action_type": "retry_failed_step", "category": "APPROVAL_REQUIRED"}
    if "cancel" in text:
        return {"action_type": "cancel_run", "category": "APPROVAL_REQUIRED"}
    if "approve" in text and "ddl" in text:
        return {"action_type": "approve_generated_ddl", "category": "APPROVAL_REQUIRED"}
    if "reject" in text and "ddl" in text:
        return {"action_type": "reject_generated_ddl", "category": "APPROVAL_REQUIRED"}
    if "cost" in text:
        return {"action_type": "get_cost_estimate", "category": "READ_ONLY"}
    if "validation" in text:
        return {"action_type": "get_validation_summary", "category": "READ_ONLY"}
    if "snowflake service" in text or "cortex health" in text or "service health" in text:
        return {"action_type": "get_snowflake_services_health", "category": "READ_ONLY"}
    if "document" in text or "runbook" in text:
        return {"action_type": "search_cortex_documents", "category": "READ_ONLY"}
    if "snowpark" in text or "profile" in text:
        return {"action_type": "profile_with_snowpark", "category": "READ_ONLY"}
    if "query history" in text:
        return {"action_type": "get_snowflake_query_history", "category": "READ_ONLY"}
    return None


class UmaCopilotService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _provider(self, name: str | None = None):
        requested = normalize_provider(name or settings.COPILOT_PROVIDER or "auto")
        provider = resolve_provider(settings.AI_PROVIDER if requested in {"auto", "configured"} else requested)
        if provider == "offline_deterministic":
            provider = "mock"
        if provider in {"openai_compatible_self_hosted", "openai"}:
            return RouterCopilotProvider(provider)
        if provider == "ollama_local":
            return OllamaCopilotProvider()
        if provider == "azure_openai":
            return ConfigOnlyCopilotProvider("azure_openai", "Azure OpenAI", bool(settings.AZURE_OPENAI_API_KEY and settings.AZURE_OPENAI_ENDPOINT))
        if provider == "anthropic":
            return ConfigOnlyCopilotProvider("anthropic", "Anthropic", bool(settings.ANTHROPIC_API_KEY))
        if provider == "snowflake_cortex_later":
            return ConfigOnlyCopilotProvider("snowflake_cortex_later", "Snowflake Cortex later", False)
        if provider == "cortex":
            return CortexCopilotProvider(self.db)
        if provider == "hermes":
            return HermesCopilotAdapter()
        return MockCopilotProvider()

    async def providers(self) -> dict[str, Any]:
        rows = []
        selected_provider = resolve_provider(settings.AI_PROVIDER if normalize_provider(settings.COPILOT_PROVIDER or "auto") in {"auto", "configured"} else settings.COPILOT_PROVIDER)
        for name in ("offline_deterministic", "openai_compatible_self_hosted", "ollama_local", "openai", "azure_openai", "anthropic", "snowflake_cortex_later", "cortex", "hermes"):
            provider = self._provider(name)
            health = await provider.health()
            rows.append({
                "name": name,
                "display_name": "Offline Deterministic" if name == "offline_deterministic" else provider.display_name,
                "selected": selected_provider == name,
                "health": redact_secrets(health),
            })
        snowflake_services = await SnowflakeIntelligenceService(self.db).capabilities()
        return {
            "selected_provider": selected_provider,
            "ai_mode": normalize_provider(settings.AI_PROVIDER),
            "rag": {
                "enabled": settings.RAG_ENABLED,
                "vector_store": settings.RAG_VECTOR_STORE,
                "index_path": settings.RAG_INDEX_PATH,
                "max_results": settings.RAG_MAX_RESULTS,
            },
            "ollama": {
                "enabled": settings.OLLAMA_ENABLED,
                "base_url": settings.OLLAMA_BASE_URL,
                "chat_model": settings.OLLAMA_CHAT_MODEL,
                "embedding_model": settings.OLLAMA_EMBEDDING_MODEL,
            },
            "cortex_enabled": bool(settings.CORTEX_ENABLED),
            "hermes": {
                "url_configured": bool(settings.HERMES_AGENT_URL),
                "token_status": "configured_masked" if settings.HERMES_AGENT_TOKEN else "not_configured",
            },
            "snowflake_services": redact_secrets(snowflake_services),
            "providers": rows,
            "safe_actions": {
                "READ_ONLY": sorted(READ_ONLY_ACTIONS),
                "APPROVAL_REQUIRED": sorted(APPROVAL_REQUIRED_ACTIONS),
                "BLOCKED": sorted(BLOCKED_ACTIONS),
            },
        }

    async def ask(self, *, message: str, provider_name: str | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        provider = self._provider(provider_name)
        gathered = await self._gather_context(context or {})
        run_id = (context or {}).get("run_id") or (context or {}).get("selected_run_id") or (context or {}).get("job_id")
        if settings.RAG_ENABLED and message:
            rag = await RagRetriever(db=self.db).search(message, run_id=run_id, job_id=(context or {}).get("job_id"), top_k=settings.RAG_MAX_RESULTS)
            gathered["rag"] = rag.get("chunks") or []
            gathered["rag_enabled"] = bool(gathered["rag"])
            gathered["rag_provider"] = rag.get("embedding_provider")
        answer = await provider.send_message(message, gathered)
        if not answer.proposed_action:
            answer.proposed_action = _infer_proposed_action(message)
        data = answer.to_dict()
        data["ai_mode"] = provider.name
        data["rag_enabled"] = bool(gathered.get("rag"))
        data["evidence_used"] = [
            {
                "chunk_id": row.get("chunk_id") or row.get("id"),
                "citation": row.get("citation"),
                "score": row.get("score"),
            }
            for row in gathered.get("rag", [])
        ]
        return data

    async def preview_action(self, action_type: str, payload: dict[str, Any] | None = None, provider_name: str | None = None) -> dict[str, Any]:
        provider = self._provider(provider_name)
        preview = await provider.preview_action(action_type, payload)
        preview["execution_owner"] = "UMA_ORCHESTRATOR"
        if preview["category"] == "BLOCKED":
            preview["reason"] = "Action is outside the copilot safety boundary."
        elif preview["category"] == "APPROVAL_REQUIRED":
            preview["reason"] = "Mutation action must pass the UMA approval gate."
        else:
            preview["reason"] = "Read-only action can be executed by UMA backend APIs."
        return redact_secrets(preview)

    async def execute_action(
        self,
        *,
        action_type: str,
        payload: dict[str, Any] | None,
        confirmed: bool,
        user: User,
    ) -> dict[str, Any]:
        payload = payload or {}
        category = "BLOCKED" if payload_has_blocked_sql(payload) else classify_action(action_type)
        if category == "BLOCKED":
            return {
                "status": "BLOCKED",
                "action_type": action_type,
                "message": "Action is blocked by UMA copilot safety policy.",
            }
        if category == "APPROVAL_REQUIRED" and not confirmed:
            return {
                "status": "CONFIRMATION_REQUIRED",
                "action_type": action_type,
                "message": "Confirm this mutation after reviewing the UMA approval context.",
            }
        if category == "READ_ONLY":
            return await self._execute_read_only(action_type, payload)
        return await self._execute_approved_action(action_type, payload, user)

    async def _gather_context(self, context: dict[str, Any]) -> dict[str, Any]:
        result = safe_context(context)
        if context.get("run_id"):
            run = await self.db.get(AgentRun, context["run_id"])
            if run:
                result["run"] = serialize_run(run)
        if context.get("validation_id"):
            row = await self.db.get(MigrationValidationResult, context["validation_id"])
            if row:
                result["validation"] = {
                    "id": row.id,
                    "status": row.status,
                    "rule_type": row.rule_type,
                    "message": row.message,
                    "delta": row.delta,
                }
        if context.get("cost_estimate_id"):
            row = await self.db.get(MigrationCostEstimate, context["cost_estimate_id"])
            if row:
                result["cost_estimate"] = {
                    "id": row.id,
                    "estimated_credits": row.estimated_credits,
                    "estimated_cost": row.estimated_cost,
                    "confidence_level": row.confidence_level,
                }
        return redact_secrets(result)

    async def _execute_read_only(self, action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action_type == "get_migration_project_status":
            job_counts = (await self.db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))).all()
            run_counts = (await self.db.execute(select(AgentRun.status, func.count(AgentRun.id)).group_by(AgentRun.status))).all()
            return {
                "status": "SUCCEEDED",
                "job_status": {str(k.value if hasattr(k, "value") else k): v for k, v in job_counts},
                "agent_run_status": {str(k): v for k, v in run_counts},
            }
        if action_type == "get_agent_run_status":
            run = await self.db.get(AgentRun, payload.get("run_id"))
            return {"status": "SUCCEEDED", "run": serialize_run(run) if run else None}
        if action_type == "get_validation_summary":
            rows = (
                await self.db.execute(
                    select(MigrationValidationResult.status, func.count(MigrationValidationResult.id))
                    .group_by(MigrationValidationResult.status)
                )
            ).all()
            return {"status": "SUCCEEDED", "validation_status": {str(k): v for k, v in rows}}
        if action_type == "get_cost_estimate":
            rows = (
                await self.db.execute(
                    select(MigrationCostEstimate)
                    .order_by(MigrationCostEstimate.created_at.desc())
                    .limit(5)
                )
            ).scalars().all()
            return {
                "status": "SUCCEEDED",
                "cost_estimates": [
                    {
                        "id": row.id,
                        "run_id": row.run_id,
                        "table_name": row.table_name,
                        "estimated_credits": row.estimated_credits,
                        "estimated_cost": row.estimated_cost,
                        "confidence_level": row.confidence_level,
                    }
                    for row in rows
                ],
            }
        if action_type == "search_migration_logs":
            term = f"%{payload.get('query', '')[:80]}%"
            rows = (
                await self.db.execute(
                    select(JobLog)
                    .where(JobLog.message.ilike(term))
                    .order_by(JobLog.created_at.desc())
                    .limit(10)
                )
            ).scalars().all()
            return {
                "status": "SUCCEEDED",
                "logs": [
                    {
                        "id": row.id,
                        "job_id": row.job_id,
                        "event": row.event,
                        "level": row.level.value if hasattr(row.level, "value") else row.level,
                        "message": row.message,
                    }
                    for row in rows
                ],
            }
        if action_type == "summarize_failed_run":
            rows = (
                await self.db.execute(
                    select(MigrationRun)
                    .where(MigrationRun.status == "FAILED")
                    .order_by(MigrationRun.ended_at.desc().nullslast(), MigrationRun.created_at.desc())
                    .limit(3)
                )
            ).scalars().all()
            return {
                "status": "SUCCEEDED",
                "summary": [
                    {"run_id": row.id, "job_id": row.job_id, "error_message": row.error_message}
                    for row in rows
                ],
            }
        if action_type == "explain_validation_mismatch":
            return {
                "status": "SUCCEEDED",
                "explanation": "Compare source/target counts, duplicate keys, watermark ranges, and soft-delete handling for the referenced validation result.",
                "payload": safe_context(payload),
            }
        if action_type == "explain_cost_spike":
            return {
                "status": "SUCCEEDED",
                "explanation": "Check warehouse size, query duration, bytes scanned, retry count, validation strategy, and Cortex/Snowpark usage attribution.",
                "payload": safe_context(payload),
            }
        snowflake = SnowflakeIntelligenceService(self.db)
        if action_type == "get_snowflake_services_health":
            return {"status": "SUCCEEDED", "services": await snowflake.capabilities()}
        if action_type == "ask_cortex_analyst":
            return await snowflake.cortex_analyst(str(payload.get("question") or payload.get("query") or ""))
        if action_type == "search_cortex_documents":
            return await snowflake.cortex_search(str(payload.get("query") or ""), document=True, limit=payload.get("limit", 10))
        if action_type == "search_cortex_logs":
            return await snowflake.cortex_search(str(payload.get("query") or ""), document=False, limit=payload.get("limit", 10))
        if action_type == "summarize_with_cortex":
            return await snowflake.cortex_complete(str(payload.get("prompt") or payload.get("query") or ""))
        if action_type == "profile_with_snowpark":
            return await snowflake.snowpark_profile(payload)
        if action_type == "get_snowflake_query_history":
            return await snowflake.query_history(payload.get("limit", 10))
        if action_type == "get_snowflake_cost_intelligence":
            return await snowflake.cost_intelligence(payload.get("limit", 10))
        return {"status": "BLOCKED", "message": "Unsupported read-only action."}

    async def _execute_approved_action(self, action_type: str, payload: dict[str, Any], user: User) -> dict[str, Any]:
        run_id = payload.get("run_id")
        run = await self.db.get(AgentRun, run_id) if run_id else None
        if action_type == "retry_failed_step":
            if not run:
                return {"status": "ERROR", "message": "run_id is required"}
            updated = await retry_agent_run(self.db, run)
            return {"status": "SUCCEEDED", "run": serialize_run(updated)}
        if action_type == "cancel_run":
            if not run:
                return {"status": "ERROR", "message": "run_id is required"}
            run.status = "CANCELLED"
            run.current_step = "cancelled"
            run.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(run)
            return {"status": "SUCCEEDED", "run": serialize_run(run)}
        if action_type == "approve_generated_ddl":
            if not run:
                return {"status": "ERROR", "message": "run_id is required"}
            updated = await continue_after_approval(self.db, run, user)
            return {"status": "SUCCEEDED", "run": serialize_run(updated)}
        if action_type == "reject_generated_ddl":
            if not run:
                return {"status": "ERROR", "message": "run_id is required"}
            run.status = "APPROVAL_REJECTED"
            run.requires_approval = False
            run.error_message = payload.get("comment") or "Rejected by copilot action gate"
            run.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(run)
            return {"status": "SUCCEEDED", "run": serialize_run(run)}
        if action_type == "execute_approved_ddl":
            return {
                "status": "STAGED",
                "message": "DDL execution remains owned by the UMA orchestrator and requires an already approved control-plane run.",
                "payload": safe_context(payload),
            }
        return {"status": "BLOCKED", "message": "Unsupported mutation action."}
