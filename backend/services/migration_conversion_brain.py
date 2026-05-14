from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4
from pathlib import Path
from typing import Any
import asyncio
import difflib
import json
import re
import urllib.request
import zipfile

from sqlalchemy.ext.asyncio import AsyncSession

from agents.tools.safety import redact_secrets
from core.config import settings
from models import ControlPlaneArtifact, ControlPlaneRun, HumanReviewItem
from services.control_plane import ControlPlaneService, read_artifact_text, utcnow
from services.ollama_provider import OllamaClient
from services.ai import AiProviderRouter, normalize_provider
from services.rag.retriever import RagRetriever
from services.sql_snowflake_conversion import SqlToSnowflakeConversionEngine


CONVERSION_GRAPH_NODES = [
    "UploadInventoryNode",
    "DialectDetectionNode",
    "DbtProjectAnalysisNode",
    "JinjaProtectionNode",
    "StaticRuleConversionNode",
    "ParserValidationNode",
    "SourceResidueScanNode",
    "RagRetrievalNode",
    "LlmRewriteNode",
    "ConversionJudgeNode",
    "RepairNode",
    "SecondJudgePassNode",
    "FinalQualityGateNode",
    "DeepAgentReviewNode",
    "DiffValidationNode",
    "RiskClassificationNode",
    "ReportGenerationNode",
    "CopilotContextNode",
]


@dataclass
class KnowledgeRule:
    dialect: str
    topic: str
    patterns: list[str]
    guidance: str
    examples: list[dict[str, str]] = field(default_factory=list)
    severity: str = "INFO"


class MigrationRagService:
    """Small local retrieval corpus. It is intentionally offline and deterministic."""

    RULES = [
        KnowledgeRule(
            "bigquery",
            "date/time functions",
            ["timestamp_trunc", "datetime_add", "date_sub", "date_trunc", "last_day", "time("],
            "Rewrite BigQuery date part argument order to Snowflake DATE_TRUNC/DATEADD conventions.",
            [
                {"source": "TIMESTAMP_TRUNC(ts, DAY)", "target": "DATE_TRUNC('DAY', ts)"},
                {"source": "DATE_SUB(d, INTERVAL 7 DAY)", "target": "DATEADD(DAY, -7, d)"},
            ],
        ),
        KnowledgeRule(
            "bigquery",
            "safe functions",
            ["safe_cast", "safe_divide", "regexp_contains"],
            "Map SAFE_CAST to TRY_CAST, SAFE_DIVIDE to guarded division, and REGEXP_CONTAINS to REGEXP_LIKE.",
            [{"source": "SAFE_CAST(x AS INT64)", "target": "TRY_CAST(x AS NUMBER)"}],
            "WARN",
        ),
        KnowledgeRule(
            "bigquery",
            "nested data",
            ["unnest", "struct", "array"],
            "Review nested data rewrites manually; Snowflake usually needs FLATTEN, OBJECT_CONSTRUCT, ARRAY_CONSTRUCT, or VARIANT modeling.",
            severity="REVIEW",
        ),
        KnowledgeRule(
            "dbt",
            "incremental models",
            ["materialized='incremental'", "materialized=\"incremental\"", "is_incremental", "unique_key"],
            "Incremental Snowflake dbt models should have a unique_key, incremental filter, incremental_predicates, or a merge/delete+insert strategy.",
            severity="WARN",
        ),
        KnowledgeRule(
            "dbt",
            "refs and sources",
            ["{{ ref(", "{{ source("],
            "Preserve dbt Jinja macros exactly during SQL conversion and only map source names through explicit project configuration.",
        ),
        KnowledgeRule("teradata", "volatile tables", ["volatile table", "primary index", "qualify"], "Map VOLATILE tables to Snowflake TEMPORARY tables and review PI semantics.", severity="WARN"),
        KnowledgeRule("oracle", "date and null functions", ["sysdate", "nvl", "connect by"], "Map SYSDATE/NVL and review hierarchical CONNECT BY rewrites.", severity="WARN"),
        KnowledgeRule("sqlserver", "T-SQL functions", ["getdate", "isnull", "top "], "Map GETDATE/ISNULL and normalize TOP to Snowflake LIMIT where applicable."),
        KnowledgeRule("postgres", "casts and JSON", ["::", "jsonb", "->>"], "Review Postgres cast and JSON operators for Snowflake TRY_CAST and VARIANT syntax."),
        KnowledgeRule("mysql", "mysql functions", ["ifnull", "auto_increment", "`"], "Map IFNULL to COALESCE and review AUTO_INCREMENT as identity or sequence."),
        KnowledgeRule("databricks", "spark nested data", ["explode", "lateral view", "using delta"], "Map Spark explode/lateral view to Snowflake FLATTEN and remove Delta storage clauses.", severity="REVIEW"),
    ]

    def retrieve(self, *, dialect: str, sql: str, dbt_metadata: dict[str, Any] | None = None, limit: int = 8) -> list[dict[str, Any]]:
        haystack = f"{sql}\n{json.dumps(dbt_metadata or {}, sort_keys=True)}".lower()
        scored: list[tuple[int, KnowledgeRule]] = []
        for rule in self.RULES:
            score = 0
            if rule.dialect in {dialect, "dbt"}:
                score += 2
            score += sum(1 for pattern in rule.patterns if pattern.lower() in haystack)
            if score:
                scored.append((score, rule))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "dialect": rule.dialect,
                "topic": rule.topic,
                "guidance": rule.guidance,
                "examples": rule.examples,
                "severity": rule.severity,
                "score": score,
            }
            for score, rule in scored[:limit]
        ]


class LlmConversionProvider:
    name = "offline"
    model = "offline"
    configured = False

    async def rewrite(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": False,
            "converted_sql": payload.get("deterministic_converted_sql", ""),
            "explanation": "No LLM provider is configured; deterministic conversion output was retained.",
            "rules_applied": [],
            "warnings": [],
            "manual_review_required": True,
            "confidence_score": 0,
            "assumptions": [],
            "unsupported_features": [],
        }

    async def propose_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "available": False,
            "proposed_sql": payload.get("converted_sql", ""),
            "explanation": "AI patching unavailable because no LLM provider is configured.",
            "assumptions": [],
            "risks": ["Patch was not generated by an AI provider."],
            "readiness_changes_expected": [],
            "patch_confidence": 0,
            "manual_review_required": True,
            "structured_diff": "",
        }


class HttpJsonLlmProvider(LlmConversionProvider):
    def __init__(self, *, name: str, url: str, headers: dict[str, str], body_builder):
        self.name = name
        self.url = url
        self.headers = headers
        self.body_builder = body_builder
        self.configured = True

    async def rewrite(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "Return only JSON with keys converted_sql, explanation, rules_applied, warnings, "
            "manual_review_required, confidence_score, assumptions, unsupported_features.\n\n"
            + json.dumps(redact_secrets(payload), indent=2)[:24000]
        )

        def call() -> dict[str, Any]:
            request = urllib.request.Request(
                self.url,
                data=json.dumps(self.body_builder(prompt)).encode("utf-8"),
                headers={**self.headers, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            raw = await asyncio.to_thread(call)
            content = _extract_llm_content(raw)
            parsed = json.loads(content)
            parsed["provider"] = self.name
            parsed["available"] = True
            return parsed
        except Exception as exc:
            fallback = await LlmConversionProvider().rewrite(payload)
            fallback.update(
                {
                    "provider": self.name,
                    "available": False,
                    "warnings": [f"AI provider call failed: {exc}"],
                }
            )
            return fallback

    async def propose_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "You are proposing a SQL/dbt patch for migration review. Do not claim Snowflake readiness. "
            "Return only JSON with keys proposed_sql, explanation, assumptions, risks, "
            "readiness_changes_expected, patch_confidence, manual_review_required.\n\n"
            + json.dumps(redact_secrets(payload), indent=2)[:26000]
        )

        def call() -> dict[str, Any]:
            request = urllib.request.Request(
                self.url,
                data=json.dumps(self.body_builder(prompt)).encode("utf-8"),
                headers={**self.headers, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            raw = await asyncio.to_thread(call)
            content = _extract_llm_content(raw)
            parsed = json.loads(content)
            proposed_sql = parsed.get("proposed_sql") or parsed.get("converted_sql") or payload.get("converted_sql", "")
            parsed["proposed_sql"] = proposed_sql
            parsed["provider"] = self.name
            parsed["model"] = self.model
            parsed["available"] = True
            parsed["structured_diff"] = "\n".join(
                difflib.unified_diff(
                    str(payload.get("converted_sql") or "").splitlines(),
                    str(proposed_sql or "").splitlines(),
                    fromfile="converted",
                    tofile="ai_patch",
                    lineterm="",
                )
            )
            return parsed
        except Exception as exc:
            fallback = await LlmConversionProvider().propose_patch(payload)
            fallback.update({"provider": self.name, "available": False, "risks": [f"AI provider patch call failed: {exc}"]})
            return fallback


class OllamaLlmProvider(LlmConversionProvider):
    name = "ollama"
    configured = True

    def __init__(self) -> None:
        self.client = OllamaClient()
        self.model = self.client.chat_model

    async def rewrite(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not settings.OLLAMA_ENABLED:
            fallback = await LlmConversionProvider().rewrite(payload)
            fallback.update({"provider": self.name, "model": self.model, "available": False, "warnings": ["Ollama is disabled."]})
            return fallback
        health = await self.client.health()
        if not health.get("available"):
            fallback = await LlmConversionProvider().rewrite(payload)
            fallback.update({"provider": self.name, "model": self.model, "available": False, "warnings": [f"Ollama unavailable: {health.get('error') or 'health check failed'}"]})
            return fallback
        prompt = (
            "You are UMA's local Ollama SQL migration reviewer. Do not claim Snowflake readiness. "
            "Return only JSON with keys converted_sql, explanation, rules_applied, warnings, "
            "manual_review_required, confidence_score, assumptions, unsupported_features.\n\n"
            + json.dumps(redact_secrets(payload), indent=2)[:24000]
        )
        try:
            parsed = await self.client.chat_json([{"role": "user", "content": prompt}])
            parsed["provider"] = self.name
            parsed["model"] = self.model
            parsed["available"] = True
            parsed.setdefault("converted_sql", payload.get("deterministic_converted_sql", ""))
            parsed.setdefault("manual_review_required", True)
            return parsed
        except Exception as exc:
            fallback = await LlmConversionProvider().rewrite(payload)
            fallback.update({"provider": self.name, "model": self.model, "available": False, "warnings": [f"Ollama call failed: {exc}"]})
            return fallback

    async def propose_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not settings.OLLAMA_ENABLED:
            fallback = await LlmConversionProvider().propose_patch(payload)
            fallback.update({"provider": self.name, "model": self.model, "available": False, "risks": ["Ollama is disabled."]})
            return fallback
        health = await self.client.health()
        if not health.get("available"):
            fallback = await LlmConversionProvider().propose_patch(payload)
            fallback.update({"provider": self.name, "model": self.model, "available": False, "risks": [f"Ollama unavailable: {health.get('error') or 'health check failed'}"]})
            return fallback
        prompt = (
            "You are proposing a SQL/dbt patch for migration review using local Ollama only. "
            "Never auto-apply. Never claim Snowflake-ready. Preserve dbt/Jinja macros exactly. "
            "Return only JSON with keys proposed_sql, explanation, assumptions, risks, "
            "readiness_changes_expected, patch_confidence, manual_review_required.\n\n"
            + json.dumps(redact_secrets(payload), indent=2)[:26000]
        )
        try:
            parsed = await self.client.chat_json([{"role": "user", "content": prompt}])
            proposed_sql = parsed.get("proposed_sql") or parsed.get("converted_sql") or payload.get("converted_sql", "")
            parsed["proposed_sql"] = proposed_sql
            parsed["provider"] = self.name
            parsed["model"] = self.model
            parsed["available"] = True
            parsed["manual_review_required"] = True
            parsed["structured_diff"] = "\n".join(
                difflib.unified_diff(
                    str(payload.get("converted_sql") or "").splitlines(),
                    str(proposed_sql or "").splitlines(),
                    fromfile="converted",
                    tofile="ollama_patch",
                    lineterm="",
                )
            )
            return parsed
        except Exception as exc:
            fallback = await LlmConversionProvider().propose_patch(payload)
            fallback.update({"provider": self.name, "model": self.model, "available": False, "risks": [f"Ollama patch call failed: {exc}"]})
            return fallback


class RouterLlmProvider(LlmConversionProvider):
    def __init__(self, provider_name: str | None = None):
        self.router = AiProviderRouter(provider_name)
        self.name = self.router.provider_name
        self.model = settings.AI_CHAT_MODEL or settings.OPENAI_MODEL or settings.OLLAMA_CHAT_MODEL or "offline"
        self.configured = self.name != "offline_deterministic"

    async def rewrite(self, payload: dict[str, Any]) -> dict[str, Any]:
        review = await self.router.semantic_review(payload)
        if not review.get("available"):
            fallback = await LlmConversionProvider().rewrite(payload)
            fallback.update({
                "provider": self.name,
                "model": self.model,
                "available": False,
                "warnings": [] if self.name == "offline_deterministic" else [review.get("message") or "AI provider unavailable."],
            })
            return fallback
        return {
            "provider": review.get("provider") or self.name,
            "model": review.get("model") or self.model,
            "available": True,
            "converted_sql": review.get("converted_sql") or payload.get("deterministic_converted_sql") or "",
            "explanation": review.get("explanation") or review.get("summary") or "AI semantic review completed.",
            "rules_applied": review.get("rules_applied") or [],
            "warnings": review.get("warnings") or review.get("risks") or [],
            "manual_review_required": True,
            "confidence_score": review.get("confidence") or review.get("confidence_score") or 0,
            "assumptions": review.get("assumptions") or [],
            "unsupported_features": review.get("unsupported_features") or [],
            "semantic_review": review,
        }

    async def propose_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        proposal = await self.router.propose_patch(payload)
        proposed_sql = proposal.get("proposed_sql") or payload.get("converted_sql", "")
        proposal["patch_confidence"] = proposal.get("confidence", proposal.get("patch_confidence", 0))
        proposal["readiness_changes_expected"] = proposal.get("expected_readiness_impact") or proposal.get("readiness_changes_expected") or "Advisory only."
        proposal["manual_review_required"] = True
        proposal["structured_diff"] = "\n".join(
            difflib.unified_diff(
                str(payload.get("converted_sql") or "").splitlines(),
                str(proposed_sql or "").splitlines(),
                fromfile="converted",
                tofile="ai_patch",
                lineterm="",
            )
        )
        return proposal


def _extract_llm_content(raw: dict[str, Any]) -> str:
    if "choices" in raw:
        choice = raw["choices"][0]
        return (choice.get("message") or {}).get("content") or choice.get("text") or "{}"
    if "content" in raw and isinstance(raw["content"], list):
        return "".join(part.get("text", "") for part in raw["content"] if isinstance(part, dict))
    if "response" in raw:
        return str(raw["response"])
    return json.dumps(raw)


def _configured_provider_name(name: str | None = None) -> str:
    requested = (name or "").strip().lower()
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


def llm_provider(name: str | None = None) -> LlmConversionProvider:
    provider = _configured_provider_name(name)
    if provider in {"openai_compatible_self_hosted", "offline_deterministic", "openai"}:
        return RouterLlmProvider(provider)
    if provider == "ollama_local" and settings.OLLAMA_ENABLED:
        return OllamaLlmProvider()
    if provider == "openai" and settings.OPENAI_API_KEY:
        provider_obj = HttpJsonLlmProvider(
            name="openai",
            url="https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            body_builder=lambda prompt: {
                "model": settings.OPENAI_MODEL,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        provider_obj.model = settings.OPENAI_MODEL
        return provider_obj
    if provider == "azure_openai" and settings.AZURE_OPENAI_API_KEY and settings.AZURE_OPENAI_ENDPOINT:
        endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        provider_obj = HttpJsonLlmProvider(
            name="azure_openai",
            url=f"{endpoint}/openai/deployments/{settings.AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version={settings.AZURE_OPENAI_API_VERSION}",
            headers={"api-key": settings.AZURE_OPENAI_API_KEY},
            body_builder=lambda prompt: {
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        provider_obj.model = settings.AZURE_OPENAI_DEPLOYMENT
        return provider_obj
    if provider in {"anthropic", "claude"} and settings.ANTHROPIC_API_KEY:
        provider_obj = HttpJsonLlmProvider(
            name="anthropic",
            url="https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
            body_builder=lambda prompt: {
                "model": "claude-3-5-sonnet-latest",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        provider_obj.model = "claude-3-5-sonnet-latest"
        return provider_obj
    if provider in {"local", "offline"} and settings.INTERNAL_LLM_ENDPOINT:
        provider_obj = HttpJsonLlmProvider(
            name="local",
            url=settings.INTERNAL_LLM_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.INTERNAL_LLM_API_KEY}"} if settings.INTERNAL_LLM_API_KEY else {},
            body_builder=lambda prompt: {"model": settings.INTERNAL_LLM_MODEL, "prompt": prompt},
        )
        provider_obj.model = settings.INTERNAL_LLM_MODEL
        return provider_obj
    return LlmConversionProvider()


def llm_provider_status(name: str | None = None) -> dict[str, Any]:
    requested = _configured_provider_name(name)
    if requested == "openai_compatible_self_hosted":
        configured = bool(settings.AI_BASE_URL and settings.AI_CHAT_MODEL)
        return {
            "provider_configured": configured,
            "provider_name": requested,
            "model_name": settings.AI_CHAT_MODEL or "self-hosted-open-model",
            "ai_review_available": configured,
            "ai_patch_available": configured,
            "status": "configured" if configured else "offline",
            "message": "Self-hosted OpenAI-compatible provider is configured." if configured else "AI_BASE_URL and AI_CHAT_MODEL are required for self-hosted AI.",
            "local_private_mode": True,
            "structured_output_supported": settings.AI_STRUCTURED_OUTPUT_SUPPORTED,
        }
    if requested == "offline_deterministic":
        return {
            "provider_configured": False,
            "provider_name": requested,
            "model_name": "offline",
            "ai_review_available": False,
            "ai_patch_available": False,
            "status": "offline",
            "message": "Offline deterministic conversion only. AI patching is disabled.",
            "local_private_mode": True,
        }
    provider = llm_provider(name)
    if requested in {"snowflake_cortex", "snowflake_cortex_later", "cortex"}:
        return {
            "provider_configured": False,
            "provider_name": "snowflake_cortex",
            "model_name": settings.CORTEX_LLM_MODEL or "snowflake-cortex",
            "ai_review_available": False,
            "ai_patch_available": False,
            "status": "planned",
            "message": "Snowflake Cortex provider slot is reserved but not wired for conversion patching yet.",
        }
    if requested == "ollama_local":
        configured = bool(settings.OLLAMA_ENABLED)
        return {
            "provider_configured": configured,
            "provider_name": "ollama",
            "model_name": settings.OLLAMA_CHAT_MODEL,
            "embedding_model": settings.OLLAMA_EMBEDDING_MODEL,
            "ai_review_available": configured,
            "ai_patch_available": configured,
            "status": "configured" if configured else "offline",
            "message": "Local Ollama provider is configured; health endpoint verifies reachability." if configured else "Ollama is disabled.",
        }
    configured = bool(getattr(provider, "configured", False))
    return {
        "provider_configured": configured,
        "provider_name": provider.name,
        "model_name": getattr(provider, "model", "offline") or "offline",
        "ai_review_available": configured,
        "ai_patch_available": configured,
        "status": "configured" if configured else "offline",
        "message": "Provider-backed AI review and patching are available." if configured else "AI review unavailable / deterministic conversion only.",
    }


def dbt_metadata(sql: str, path: str) -> dict[str, Any]:
    config = re.search(r"\{\{\s*config\s*\((.*?)\)\s*\}\}", sql, re.I | re.S)
    config_body = config.group(1) if config else ""
    logical_path = path.split(":", 1)[-1]
    target_model = Path(logical_path).stem
    source_pairs = re.findall(r"\{\{\s*source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", sql, re.I)
    return {
        "path": path,
        "target_model": target_model,
        "target_relation": target_model,
        "target_relation_type": "dbt_model",
        "materialization": _config_value(config_body, "materialized") or "unknown",
        "unique_key": _config_value(config_body, "unique_key"),
        "incremental_strategy": _config_value(config_body, "incremental_strategy"),
        "incremental_predicates": "incremental_predicates" in config_body,
        "has_is_incremental": bool(re.search(r"\bis_incremental\s*\(", sql, re.I)),
        "pre_hook": _config_value(config_body, "pre_hook"),
        "post_hook": _config_value(config_body, "post_hook"),
        "partition_by": "partition_by" in config_body,
        "cluster_by": "cluster_by" in config_body,
        "refs": re.findall(r"\{\{\s*ref\s*\(\s*['\"]([^'\"]+)['\"]", sql, re.I),
        "sources": source_pairs,
        "source_relations": [
            {
                "source_name": source_name,
                "table_name": table_name,
                "dbt_macro": f"{{{{ source('{source_name}', '{table_name}') }}}}",
                "is_wildcard": "*" in table_name,
            }
            for source_name, table_name in sorted(set(source_pairs))
        ],
        "macros": sorted(set(re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", sql))),
        "snapshots": path.lower().startswith("snapshots/"),
        "seeds": path.lower().startswith("seeds/"),
    }


def _config_value(config_body: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}\s*=\s*['\"]([^'\"]+)['\"]", config_body, re.I)
    return match.group(1) if match else None


def specialist_review(file_result: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    metadata = file_result.get("dbt_metadata") or {}
    unsupported = file_result.get("unsupported_features") or []
    warnings = file_result.get("warnings") or []
    rules = file_result.get("rules_applied") or []
    readiness_reasons = file_result.get("readiness_reasons") or []
    if file_result.get("detected_dialect") == "generic_ansi":
        findings.append({"agent": "DialectDetectionAgent", "severity": "WARN", "finding": "Dialect confidence is low; review source syntax manually."})
    if metadata.get("materialization") == "incremental" and any("duplicate rows" in warning.lower() for warning in warnings):
        findings.append({"agent": "IncrementalModelAgent", "severity": "WARN", "finding": "Incremental model needs unique_key or incremental filter before Snowflake readiness."})
    for reason in readiness_reasons:
        findings.append({
            "agent": "DbtSemanticReadinessAgent",
            "severity": "WARN" if reason.get("severity") == "warning" else "INFO",
            "finding": reason.get("message"),
        })
    if unsupported:
        findings.append({"agent": "SnowflakeSyntaxAgent", "severity": "REVIEW", "finding": "Source-dialect residue or unsupported constructs remain."})
    if file_result.get("judge_status") == "failed":
        findings.append({"agent": "ConversionJudgeAgent", "severity": "ERROR", "finding": "Judge rejected the conversion; this file is not Snowflake-ready."})
    if file_result.get("source_residue"):
        findings.append({"agent": "ResidueScannerAgent", "severity": "ERROR", "finding": "Source-dialect syntax remains: " + ", ".join(file_result.get("source_residue", [])) + "."})
    if not file_result.get("snowflake_ready"):
        findings.append({"agent": "FinalQualityGateAgent", "severity": "REVIEW", "finding": "Final quality gate did not mark this file as Snowflake-ready."})
    if not rules:
        findings.append({"agent": "SqlRewriteAgent", "severity": "ERROR", "finding": "No conversion rules were applied; converted file is not ready."})
    if metadata.get("sources"):
        findings.append({"agent": "DbtSemanticsAgent", "severity": "INFO", "finding": "dbt source macros were preserved; source mapping should be checked by project owner."})
    if metadata.get("partition_by") or metadata.get("cluster_by"):
        findings.append({"agent": "DbtSemanticsAgent", "severity": "REVIEW", "finding": "BigQuery partition_by/cluster_by config needs Snowflake semantic review."})
    if any(row.get("is_wildcard") for row in metadata.get("source_relations", [])):
        findings.append({"agent": "DbtSemanticsAgent", "severity": "REVIEW", "finding": "Wildcard dbt source table detected; Snowflake needs explicit file/table suffix strategy before readiness."})
    if re.search(r"\bselect\s+\*", file_result.get("converted_sql", ""), re.I):
        findings.append({"agent": "PerformanceAgent", "severity": "INFO", "finding": "SELECT * remains; consider explicit projection for governed Snowflake models."})
    findings.append({"agent": "ValidationAgent", "severity": "INFO", "finding": "No SQL was executed. Validation is static residue and readiness scanning only."})
    recommendation = "REQUIRES_REVIEW" if any(f["severity"] in {"ERROR", "REVIEW"} for f in findings) else "READY_FOR_HUMAN_REVIEW"
    return {"supervisor_recommendation": recommendation, "findings": findings}


class MigrationIntelligenceEngine:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.common = ControlPlaneService(db)
        self.converter = SqlToSnowflakeConversionEngine(db)
        self.rag = MigrationRagService()

    async def agentic_convert(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact], *, provider_name: str | None = None, use_llm: bool = True) -> dict[str, Any]:
        job = await self.common.create_job(run.id, "MIGRATION_INTELLIGENCE", "AGENTIC_CONVERT")
        provider_info = llm_provider_status(provider_name)
        state: dict[str, Any] = {"graph_runtime": "uma_deterministic_workflow", "nodes": [], "files": []}
        inventory = self._inventory(artifacts)
        self._node(state, "UploadInventoryNode", {"file_count": len(inventory), "files": inventory})
        self._node(
            state,
            "DialectDetectionNode",
            {"requested_source_dialect": run.source_dialect or "auto_detect", "target_dialect": run.target_dialect or "snowflake"},
        )
        self._node(
            state,
            "DbtProjectAnalysisNode",
            {"input_type": (run.config_json or {}).get("input_type") or "sql_file", "file_count": len(inventory)},
        )
        self._node(state, "JinjaProtectionNode", {"dbt_jinja_preservation": "enabled"})

        conversion = await self.converter.convert(run, artifacts)
        file_reports = conversion.get("file_reports") or []
        by_source = {row["source_path"]: row for row in file_reports}
        self._node(state, "StaticRuleConversionNode", {"file_reports": file_reports})

        for artifact in artifacts:
            for source_path, target_path, original_sql in self._artifact_sql_entries(artifact):
                detection = self.converter.detect_dialect(original_sql, run.source_dialect)
                deterministic = self.converter._convert_sql_text(original_sql, detection.dialect, (run.config_json or {}).get("input_type") or "sql_file")
                report = by_source.get(source_path) or {
                    "source_path": source_path,
                    "target_path": target_path,
                    "detected_dialect": detection.dialect,
                    "confidence_score": detection.confidence,
                    "detection_reasons": detection.reasons,
                    "conversion_status": "REQUIRES_REVIEW" if deterministic["manual_review_required"] else "COMPLETED",
                    "converted_file_ready": not deterministic["manual_review_required"],
                    "manual_review_required": deterministic["manual_review_required"],
                    "rules_applied": deterministic["rules_applied"],
                    "warnings": deterministic["warnings"],
                    "unsupported_features": deterministic["unsupported_features"],
                }
                converted_sql = deterministic["sql"]
                metadata = dbt_metadata(original_sql, source_path)
                rag = self.rag.retrieve(dialect=detection.dialect, sql=original_sql, dbt_metadata=metadata)
                llm_payload = {
                    "original_sql": original_sql,
                    "deterministic_converted_sql": converted_sql,
                    "detected_dialect": detection.dialect,
                    "dbt_metadata": metadata,
                    "warnings": report.get("warnings", []),
                    "unsupported_features": report.get("unsupported_features", []),
                    "rag_context": rag,
                    "parser_errors": [item for item in report.get("unsupported_features", []) if "Parser-backed" in item],
                    "source_residue_scan": report.get("unsupported_features", []),
                }
                llm_result = await llm_provider(provider_name).rewrite(llm_payload) if use_llm else await LlmConversionProvider().rewrite(llm_payload)
                final_sql = llm_result.get("converted_sql") or converted_sql
                final_rules = sorted(set((report.get("rules_applied") or []) + (llm_result.get("rules_applied") or [])))
                final_warnings = sorted(set((report.get("warnings") or []) + (llm_result.get("warnings") or [])))
                final_unsupported = sorted(set((report.get("unsupported_features") or []) + (llm_result.get("unsupported_features") or [])))
                readiness_reasons = report.get("readiness_reasons") or []
                judge = self.converter.judge_conversion(
                    source_sql=original_sql,
                    converted_sql=final_sql,
                    detected_dialect=detection.dialect,
                    rules_applied=final_rules,
                    warnings=final_warnings,
                    unsupported_features=final_unsupported,
                )
                repair_attempts: list[dict[str, Any]] = []
                while judge["judge_status"] == "failed" and len(repair_attempts) < 2:
                    repair = self.converter.repair_sql_once(
                        source_sql=original_sql,
                        converted_sql=final_sql,
                        detected_dialect=detection.dialect,
                        input_type=(run.config_json or {}).get("input_type") or "sql_file",
                    )
                    repair_attempts.append(
                        {
                            "attempt": len(repair_attempts) + 1,
                            "changed": repair["changed"],
                            "rules_applied": repair["rules_applied"],
                            "warnings": repair["warnings"],
                            "unsupported_features": repair["unsupported_features"],
                        }
                    )
                    if not repair["changed"]:
                        break
                    final_sql = repair["sql"]
                    final_rules = sorted(set(final_rules + repair["rules_applied"]))
                    final_warnings = sorted(set(final_warnings + repair["warnings"]))
                    final_unsupported = sorted(set(final_unsupported + repair["unsupported_features"]))
                    judge = self.converter.judge_conversion(
                        source_sql=original_sql,
                        converted_sql=final_sql,
                        detected_dialect=detection.dialect,
                        rules_applied=final_rules,
                        warnings=final_warnings,
                        unsupported_features=final_unsupported,
                    )
                diff = "\n".join(difflib.unified_diff(original_sql.splitlines(), final_sql.splitlines(), fromfile="source", tofile="converted", lineterm=""))
                enriched = {
                    **report,
                    "source_path": source_path,
                    "target_path": target_path,
                    "original_sql": original_sql,
                    "converted_sql": final_sql,
                    "conversion_status": "FAILED" if judge["judge_status"] == "failed" and (judge["copied_source_sql"] or not final_rules or judge["parser_failed"] or judge["dbt_jinja_corrupted"]) else "REQUIRES_REVIEW" if judge["manual_review_required"] else "COMPLETED",
                    "converted_file_ready": judge["snowflake_ready"],
                    "manual_review_required": judge["manual_review_required"],
                    "rules_applied": final_rules,
                    "warnings": final_warnings,
                    "unsupported_features": sorted(set(final_unsupported + judge["unsupported_features"])),
                    "readiness_reasons": readiness_reasons,
                    "errors": judge["errors"],
                    "judge_status": judge["judge_status"],
                    "snowflake_ready": judge["snowflake_ready"],
                    "source_residue": judge["source_residue"],
                    "diff_summary": judge["diff_summary"],
                    "repair_attempts": repair_attempts,
                    "dbt_metadata": metadata,
                    "rag_results": rag,
                    "llm_rewrite": redact_secrets(llm_result),
                    "diff": diff,
                }
                enriched["agent_review_results"] = specialist_review(enriched)
                state["files"].append(redact_secrets(enriched))

        for node in CONVERSION_GRAPH_NODES:
            if not any(row["node"] == node for row in state["nodes"]):
                self._node(state, node, self._node_output(node, state))

        job_state = (conversion.get("job_state") or {}).copy()
        if state["files"]:
            job_state.update(
                {
                    "judge_status": (
                        "failed"
                        if any(row.get("judge_status") == "failed" for row in state["files"])
                        else "passed_with_warnings"
                        if any(row.get("judge_status") == "passed_with_warnings" or row.get("warnings") for row in state["files"])
                        else "passed"
                    ),
                    "snowflake_ready": all(row.get("snowflake_ready") for row in state["files"]),
                    "manual_review_required": any(row.get("manual_review_required") for row in state["files"]),
                    "source_residue": sorted({item for row in state["files"] for item in row.get("source_residue", [])}),
                    "warnings": sorted({item for row in state["files"] for item in row.get("warnings", [])}),
                    "errors": sorted({item for row in state["files"] for item in row.get("errors", [])}),
                    "unsupported_features": sorted({item for row in state["files"] for item in row.get("unsupported_features", [])}),
                    "readiness_reasons": [
                        reason
                        for row in state["files"]
                        for reason in row.get("readiness_reasons", [])
                    ],
                    "rules_applied_count": len({item for row in state["files"] for item in row.get("rules_applied", [])}),
                    "ai_provider_configured": provider_info["provider_configured"],
                    "ai_provider_name": provider_info["provider_name"],
                    "ai_model_name": provider_info["model_name"],
                    "ai_review_available": provider_info["ai_review_available"],
                    "ai_patch_available": provider_info["ai_patch_available"],
                }
            )
            job_state["status"] = "converted" if job_state["snowflake_ready"] else "requires_review"
        report = {
            **conversion,
            "status": job_state.get("status") or ("requires_review" if any((f.get("agent_review_results") or {}).get("supervisor_recommendation") == "REQUIRES_REVIEW" for f in state["files"]) else conversion.get("status")),
            "engine": "MigrationIntelligenceEngine",
            "graph": state["nodes"],
            "rag_enabled": True,
            "llm_provider": provider_info["provider_name"],
            "llm_available": any((f.get("llm_rewrite") or {}).get("available") for f in state["files"]),
            "ai_provider_configured": provider_info["provider_configured"],
            "ai_provider_name": provider_info["provider_name"],
            "ai_model_name": provider_info["model_name"],
            "ai_review_available": provider_info["ai_review_available"],
            "ai_patch_available": provider_info["ai_patch_available"],
            "ai_provider_status": provider_info,
            "deep_agent_review": [f.get("agent_review_results") for f in state["files"]],
            "copilot_context_registered": True,
            "conversion_context": state,
            "job_state": job_state,
        }
        run.summary_json = redact_secrets({**(run.summary_json or {}), **report})
        run.status = report["status"]
        run.current_phase = "AGENTIC_CONVERTED"
        run.completed_at = utcnow()
        await self.common.store_json_artifact(run.id, "REPORT", "migration_intelligence_context.json", run.summary_json, run.created_by)
        await self.common.finish_job(job, "COMPLETED", report)
        await self.db.commit()
        return run.summary_json

    async def ai_review(self, run: ControlPlaneRun, *, provider_name: str | None = None) -> dict[str, Any]:
        provider_info = llm_provider_status(provider_name)
        context = (run.summary_json or {}).get("conversion_context") or {}
        files = context.get("files") or []
        reviews = []
        for file_row in files:
            payload = {
                "original_sql": file_row.get("original_sql", ""),
                "deterministic_converted_sql": file_row.get("converted_sql", ""),
                "detected_dialect": file_row.get("detected_dialect"),
                "dbt_metadata": file_row.get("dbt_metadata"),
                "warnings": file_row.get("warnings", []),
                "unsupported_features": file_row.get("unsupported_features", []),
                "rag_context": file_row.get("rag_results", []),
            }
            reviews.append(await llm_provider(provider_name).rewrite(payload))
        payload = {
            "status": "COMPLETED_WITH_WARNINGS" if any(not r.get("available") for r in reviews) else "COMPLETED",
            "provider_status": provider_info,
            "ai_reviews": redact_secrets(reviews),
        }
        run.summary_json = {**(run.summary_json or {}), "ai_review": payload}
        await self.common.store_json_artifact(run.id, "REPORT", "ai_review.json", payload, run.created_by)
        await self.db.commit()
        return payload

    async def copilot_chat(self, run: ControlPlaneRun, message: str) -> dict[str, Any]:
        summary = run.summary_json or {}
        text = (message or "").lower()
        files = ((summary.get("conversion_context") or {}).get("files") or summary.get("file_reports") or [])
        job_state = summary.get("job_state") or {}
        residue = sorted({item for row in files for item in row.get("source_residue", [])} | set(job_state.get("source_residue") or []))
        errors = sorted({item for row in files for item in row.get("errors", [])} | set(job_state.get("errors") or []))
        warnings = sorted({item for row in files for item in row.get("warnings", [])} | set(job_state.get("warnings") or []))
        unsupported = sorted({item for row in files for item in row.get("unsupported_features", [])} | set(job_state.get("unsupported_features") or []))
        rules = sorted({rule for row in files for rule in row.get("rules_applied", [])})
        readiness_reasons = [
            reason
            for row in files
            for reason in row.get("readiness_reasons", [])
        ] + list(job_state.get("readiness_reasons") or [])
        readiness_messages = sorted({reason.get("message") for reason in readiness_reasons if reason.get("message")})
        non_readiness_warnings = [warning for warning in warnings if warning not in readiness_messages]
        llm_available = bool(summary.get("llm_available"))
        if ("why" in text and ("fail" in text or "review" in text)) or "requires review" in text:
            answer = (
                "UMA converted the BigQuery syntax and removed checked BigQuery residue. "
                "The model is still not Snowflake-ready because: "
                + _flatten(errors + unsupported + residue + readiness_messages + non_readiness_warnings)
            )
        elif "what changed" in text or "before" in text or "after" in text or "rules" in text or "applied" in text or "convert" in text or "diff" in text:
            answer = "The job changed these rules: " + _flatten(rules) + "."
        elif "unsupported" in text or "remain" in text:
            answer = "Remaining BigQuery/source syntax or unsupported features: " + _flatten(residue + unsupported)
        elif "dbt" in text or "incremental" in text or "risk" in text:
            answer = "dbt risks: " + _flatten(readiness_messages + non_readiness_warnings)
        elif "patch" in text or "fix" in text:
            if not llm_available:
                answer = "AI patching unavailable because no LLM provider is configured. Deterministic guidance: address any remaining residue, preserve every dbt/Jinja macro verbatim, review dbt materialization semantics, and rerun the judge. Current residue: " + _flatten(residue)
            else:
                answer = "Patch proposal: remove remaining source-dialect residue, preserve every dbt/Jinja macro verbatim, and rerun the judge. Current residue: " + _flatten(residue)
        elif "ready" in text:
            ready = bool(job_state.get("snowflake_ready")) or (bool(files) and all(row.get("snowflake_ready") for row in files))
            answer = "Snowflake-ready: yes." if ready else f"Snowflake-ready: no; judge_status={job_state.get('judge_status') or 'unknown'}, residue={_flatten(residue)}, blockers={_flatten(readiness_messages + non_readiness_warnings)}."
        else:
            answer = "This conversion job is available to Copilot with original SQL, converted SQL, diffs, rules applied, judge result, warnings, errors, unsupported features, residue scan, and dbt metadata."
        rag_results = []
        if settings.RAG_ENABLED:
            rag_payload = await RagRetriever().search(message, run_id=run.id, top_k=settings.RAG_MAX_RESULTS)
            rag_results = rag_payload.get("chunks") or []
            if rag_results and (settings.COPILOT_PROVIDER or "").strip().lower() == "ollama" and settings.OLLAMA_ENABLED:
                try:
                    local_answer = await OllamaClient().chat(
                        [
                            {"role": "system", "content": "You are UMA Copilot. Answer from the supplied redacted evidence. Cite chunk ids. Do not claim execution or readiness not present in evidence."},
                            {"role": "user", "content": json.dumps({"question": message, "deterministic_answer": answer, "evidence": rag_results[: settings.RAG_MAX_RESULTS]}, indent=2)[:20000]},
                        ]
                    )
                    if local_answer.strip():
                        answer = local_answer.strip()
                except Exception:
                    pass
        return {
            "job_id": run.id,
            "provider": "ollama" if (settings.COPILOT_PROVIDER or "").strip().lower() == "ollama" and settings.OLLAMA_ENABLED else "offline",
            "answer": answer,
            "job_state": job_state,
            "source_context": redact_secrets({"summary": summary, "rag": rag_results}),
            "citations": [row.get("citation") for row in rag_results],
        }

    async def propose_ai_patch(self, run: ControlPlaneRun, *, selected_file: str | None = None, provider_name: str | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        summary = run.summary_json or {}
        provider_info = llm_provider_status(provider_name)
        files = ((summary.get("conversion_context") or {}).get("files") or summary.get("file_reports") or [])
        file_row = self._select_file(files, selected_file)
        if not file_row:
            raise ValueError("No converted file context is available for AI patch proposal.")
        original_sql = (overrides or {}).get("original_sql") or file_row.get("original_sql") or ""
        converted_sql = (overrides or {}).get("converted_sql") or file_row.get("converted_sql") or ""
        metadata = file_row.get("dbt_metadata") or dbt_metadata(original_sql, file_row.get("source_path") or selected_file or "model.sql")
        rag = self.rag.retrieve(dialect=file_row.get("detected_dialect") or summary.get("source_dialect") or "auto_detect", sql=original_sql, dbt_metadata=metadata)
        if settings.RAG_ENABLED:
            retrieved = await RagRetriever().search(
                " ".join([
                    str(selected_file or file_row.get("source_path") or ""),
                    str(file_row.get("detected_dialect") or summary.get("source_dialect") or ""),
                    str((overrides or {}).get("diff") or file_row.get("diff") or ""),
                    str((overrides or {}).get("readiness_reasons") or file_row.get("readiness_reasons") or ""),
                ]),
                run_id=run.id,
                top_k=settings.RAG_MAX_RESULTS,
            )
            rag = [*rag, *(retrieved.get("chunks") or [])]
        payload = {
            "selected_file": selected_file or file_row.get("source_path") or file_row.get("target_path"),
            "original_sql": original_sql,
            "converted_sql": converted_sql,
            "diff": (overrides or {}).get("diff") or file_row.get("diff") or (file_row.get("diff_summary") or {}).get("diff"),
            "rules_applied": (overrides or {}).get("rules_applied") or file_row.get("rules_applied") or [],
            "readiness_reasons": (overrides or {}).get("readiness_reasons") or file_row.get("readiness_reasons") or summary.get("readiness_reasons") or [],
            "warnings": (overrides or {}).get("warnings") or file_row.get("warnings") or [],
            "source_residue": (overrides or {}).get("source_residue") or file_row.get("source_residue") or [],
            "unsupported_features": (overrides or {}).get("unsupported_features") or file_row.get("unsupported_features") or [],
            "dbt_metadata": (overrides or {}).get("dbt_metadata") or metadata,
            "rag_context": (overrides or {}).get("rag_context") or rag,
            "quality_gate": summary.get("job_state") or {},
        }
        if not provider_info["ai_patch_available"]:
            proposal = await LlmConversionProvider().propose_patch(payload)
        else:
            proposal = await llm_provider(provider_name).propose_patch(payload)
        patch_id = f"patch_{uuid4().hex[:12]}"
        proposed_sql = proposal.get("proposed_sql") or converted_sql
        proposal["structured_diff"] = proposal.get("structured_diff") or "\n".join(
            difflib.unified_diff(converted_sql.splitlines(), proposed_sql.splitlines(), fromfile="converted", tofile="ai_patch", lineterm="")
        )
        record = {
            "patch_id": patch_id,
            "status": "PROPOSED" if proposal.get("available") else "AI_UNAVAILABLE",
            "selected_file": payload["selected_file"],
            "target_path": file_row.get("target_path") or payload["selected_file"],
            "source_path": file_row.get("source_path") or payload["selected_file"],
            "detected_dialect": file_row.get("detected_dialect") or summary.get("source_dialect") or "auto_detect",
            "input_type": summary.get("input_type") or "sql_file",
            "original_sql": original_sql,
            "converted_sql": converted_sql,
            "proposed_sql": proposed_sql,
            "provider_status": provider_info,
            "proposal": redact_secrets(proposal),
            "created_at": utcnow().isoformat(),
            "auto_applied": False,
        }
        patches = list(summary.get("ai_patches") or [])
        patches.append(record)
        run.summary_json = {**summary, "ai_provider_status": provider_info, "ai_patches": patches}
        await self.common.store_json_artifact(run.id, "REPORT", f"{patch_id}.json", record, run.created_by)
        await self.db.commit()
        return redact_secrets(record)

    async def apply_patch(self, run: ControlPlaneRun, *, patch_id: str | None = None, target_path: str | None = None, patched_sql: str | None = None, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            return {
                "status": "CONFIRMATION_REQUIRED",
                "message": "Patch application will overwrite the selected converted artifact for this job. Resubmit with confirmed=true after review.",
                "patch_id": patch_id,
                "target_path": target_path,
            }
        summary = run.summary_json or {}
        patches = list(summary.get("ai_patches") or [])
        patch_record = next((patch for patch in patches if patch.get("patch_id") == patch_id), None) if patch_id else None
        if patch_id and not patch_record:
            raise ValueError("Patch proposal was not found for this conversion job.")
        file_rows = (summary.get("conversion_context") or {}).get("files") or summary.get("file_reports") or []
        selected_file = target_path or (patch_record or {}).get("target_path") or (patch_record or {}).get("selected_file")
        file_row = self._select_file(file_rows, selected_file) or {}
        proposed_sql = patched_sql or (patch_record or {}).get("proposed_sql") or ""
        if not proposed_sql.strip():
            raise ValueError("Patched SQL is empty.")
        original_sql = (patch_record or {}).get("original_sql") or file_row.get("original_sql") or proposed_sql
        detected_dialect = (patch_record or {}).get("detected_dialect") or file_row.get("detected_dialect") or summary.get("source_dialect") or "auto_detect"
        rules = sorted(set((file_row.get("rules_applied") or []) + ["ai_patch_applied"]))
        assessment = self.converter.assess_converted_sql(
            source_sql=original_sql,
            converted_sql=proposed_sql,
            detected_dialect=detected_dialect,
            input_type=(patch_record or {}).get("input_type") or summary.get("input_type") or "sql_file",
            rules_applied=rules,
            warnings=file_row.get("warnings") or [],
            unsupported_features=file_row.get("unsupported_features") or [],
        )
        target = selected_file or f"converted/{Path((patch_record or {}).get('source_path') or 'ai_patch.sql').name}"
        artifact = await self.common.store_text_artifact(run.id, "GENERATED_SQL_PATCH", target, proposed_sql, run.created_by, "text/sql")
        updated_file = {
            **file_row,
            "source_path": file_row.get("source_path") or (patch_record or {}).get("source_path") or target,
            "target_path": target,
            "converted_sql": proposed_sql,
            "rules_applied": rules,
            "warnings": assessment["warnings"],
            "unsupported_features": assessment["unsupported_features"],
            "readiness_reasons": assessment["readiness_reasons"],
            "errors": assessment["errors"],
            "judge_status": assessment["judge_status"],
            "snowflake_ready": assessment["snowflake_ready"],
            "manual_review_required": assessment["manual_review_required"],
            "source_residue": assessment["source_residue"],
            "diff_summary": assessment["diff_summary"],
            "diff": "\n".join(difflib.unified_diff(original_sql.splitlines(), proposed_sql.splitlines(), fromfile="source", tofile="patched", lineterm="")),
            "conversion_status": "COMPLETED" if assessment["snowflake_ready"] else "REQUIRES_REVIEW",
        }
        summary = self._replace_file_in_summary(summary, updated_file, selected_file)
        state = dict(summary.get("job_state") or {})
        stale_reason = {
            "category": "snowflake_validation",
            "severity": "BLOCKER",
            "message": "AI patch was accepted after the last validation run; rerun dbt compile/Snowflake validation before package readiness.",
        }
        state["validation_status"] = "stale_after_ai_patch"
        state["validation_required"] = True
        state["snowflake_ready"] = False
        state["manual_review_required"] = True
        state["status"] = "requires_review"
        state["readiness_reasons"] = [
            reason for reason in state.get("readiness_reasons", []) if reason.get("message") != stale_reason["message"]
        ] + [stale_reason]
        summary["job_state"] = state
        summary["validation_status"] = "stale_after_ai_patch"
        accepted = {
            "patch_id": patch_id,
            "target_path": target,
            "artifact_id": artifact.id,
            "applied_at": utcnow().isoformat(),
            "executed": False,
            "judge_status": assessment["judge_status"],
            "snowflake_ready": assessment["snowflake_ready"],
            "manual_review_required": assessment["manual_review_required"],
            "validation_status": "stale_after_ai_patch",
        }
        patches = [
            {**patch, "status": "APPLIED", "applied_at": accepted["applied_at"]}
            if patch.get("patch_id") == patch_id
            else patch
            for patch in patches
        ]
        if patch_id and not any(patch.get("patch_id") == patch_id for patch in patches):
            patches.append({"patch_id": patch_id, "status": "APPLIED", "applied_at": accepted["applied_at"]})
        summary["ai_patches"] = patches
        summary["accepted_patch"] = accepted
        summary["download_artifact_id"] = summary.get("download_artifact_id") if self._all_gates_ready(summary) else None
        run.summary_json = summary
        run.status = (summary.get("job_state") or {}).get("status") or run.status
        self.db.add(
            HumanReviewItem(
                run_id=run.id,
                item_type="STALE_SNOWFLAKE_VALIDATION",
                severity="CRITICAL" if assessment["judge_status"] == "failed" else "HIGH",
                title="Snowflake validation is stale after accepted AI patch",
                description="An AI patch was accepted into the converted artifact. UMA reran the deterministic judge and marked Snowflake validation stale until dbt compile and real Snowflake validation are rerun.",
                recommendation="Review the generated patch diff, resolve judge warnings, rerun dbt compile plus Snowflake validation, then approve or resolve this Brain Review item before package readiness.",
                status="BLOCKED",
                metadata_json={
                    "patch_id": patch_id,
                    "target_path": target,
                    "artifact_id": artifact.id,
                    "judge_status": assessment["judge_status"],
                    "validation_status": "stale_after_ai_patch",
                    "source_residue": assessment["source_residue"],
                    "dedupe_key": f"stale_validation_after_patch:{run.id}:{patch_id or target}",
                },
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        await self.db.commit()
        return {"status": "PATCH_APPLIED", **accepted, "assessment": assessment}

    def _select_file(self, files: list[dict[str, Any]], selected_file: str | None) -> dict[str, Any] | None:
        if not files:
            return None
        if not selected_file:
            return files[0]
        return next((row for row in files if self._file_matches(row, selected_file)), files[0])

    def _file_matches(self, row: dict[str, Any], selected_file: str | None) -> bool:
        if not selected_file:
            return False
        needle = selected_file.lower()
        return (
            needle in str(row.get("source_path") or "").lower()
            or needle in str(row.get("target_path") or "").lower()
            or needle in Path(str(row.get("source_path") or row.get("target_path") or "")).name.lower()
        )

    def _replace_file_in_summary(self, summary: dict[str, Any], updated_file: dict[str, Any], selected_file: str | None) -> dict[str, Any]:
        def replace(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not files:
                return [updated_file]
            selected = selected_file or updated_file.get("target_path") or updated_file.get("source_path")
            return [
                updated_file
                if self._file_matches(row, selected)
                else row
                for row in files
            ]

        next_summary = {**summary}
        if next_summary.get("file_reports"):
            next_summary["file_reports"] = replace(list(next_summary.get("file_reports") or []))
        context = dict(next_summary.get("conversion_context") or {})
        if context.get("files"):
            context["files"] = replace(list(context.get("files") or []))
            next_summary["conversion_context"] = context
        files = (next_summary.get("conversion_context") or {}).get("files") or next_summary.get("file_reports") or []
        next_summary["job_state"] = self._job_state_from_files(next_summary.get("job_state") or {}, files)
        return next_summary

    def _job_state_from_files(self, current: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
        if not files:
            return current
        snowflake_ready = all(row.get("snowflake_ready") for row in files)
        validation = current.get("validation_status") or "not_run"
        if validation not in {"validation_passed", "waived_by_brain_review"}:
            snowflake_ready = False
        return {
            **current,
            "status": "converted" if snowflake_ready else "requires_review",
            "total_files": len(files),
            "converted_files_count": sum(1 for row in files if row.get("conversion_status") in {"COMPLETED", "CONVERTED_WITH_WARNINGS"}),
            "failed_files_count": sum(1 for row in files if row.get("conversion_status") == "FAILED"),
            "requires_review_count": sum(1 for row in files if row.get("conversion_status") == "REQUIRES_REVIEW" or row.get("manual_review_required")),
            "rules_applied_count": len({rule for row in files for rule in row.get("rules_applied", [])}),
            "judge_status": "failed" if any(row.get("judge_status") == "failed" for row in files) else "passed_with_warnings" if any(row.get("judge_status") == "passed_with_warnings" or row.get("warnings") for row in files) else "passed",
            "snowflake_ready": snowflake_ready,
            "manual_review_required": any(row.get("manual_review_required") for row in files) or not snowflake_ready,
            "source_residue": sorted({item for row in files for item in row.get("source_residue", [])}),
            "warnings": sorted({item for row in files for item in row.get("warnings", [])}),
            "errors": sorted({item for row in files for item in row.get("errors", [])}),
            "unsupported_features": sorted({item for row in files for item in row.get("unsupported_features", [])}),
            "readiness_reasons": [reason for row in files for reason in row.get("readiness_reasons", [])],
        }

    def _all_gates_ready(self, summary: dict[str, Any]) -> bool:
        state = summary.get("job_state") or {}
        return (
            state.get("snowflake_ready") is True
            and state.get("judge_status") != "failed"
            and not state.get("source_residue")
            and int(state.get("rules_applied_count") or 0) > 0
            and state.get("validation_status") in {"validation_passed", "waived_by_brain_review"}
        )

    def _inventory(self, artifacts: list[ControlPlaneArtifact]) -> list[dict[str, Any]]:
        return [
            {
                "artifact_id": artifact.id,
                "file_name": artifact.original_filename,
                "category": artifact.artifact_category,
                "file_type": artifact.file_type,
                "size_bytes": artifact.size_bytes,
            }
            for artifact in artifacts
        ]

    def _artifact_sql_entries(self, artifact: ControlPlaneArtifact) -> list[tuple[str, str, str]]:
        path = Path(artifact.storage_path)
        if artifact.file_type == "zip" or artifact.artifact_category == "DBT_PROJECT":
            entries = []
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    lower = name.lower()
                    if lower.endswith(".sql") and not name.endswith("/"):
                        entries.append((f"{artifact.original_filename}:{name}", name, zf.read(name).decode("utf-8", errors="ignore")))
            return entries
        target = f"converted/{Path(artifact.original_filename).name}"
        return [(artifact.original_filename, target, read_artifact_text(artifact))]

    def _node(self, state: dict[str, Any], node: str, output: dict[str, Any]) -> None:
        state["nodes"].append({"node": node, "status": "COMPLETED", "output": redact_secrets(output)})

    def _node_output(self, node: str, state: dict[str, Any]) -> dict[str, Any]:
        if node == "RagRetrievalNode":
            return {"result_count": sum(len(row.get("rag_results", [])) for row in state["files"])}
        if node == "LlmRewriteNode":
            return {"available": any((row.get("llm_rewrite") or {}).get("available") for row in state["files"])}
        if node == "ConversionJudgeNode":
            return {
                "failed": sum(1 for row in state["files"] if row.get("judge_status") == "failed"),
                "snowflake_ready": all(row.get("snowflake_ready") for row in state["files"]) if state["files"] else False,
            }
        if node == "RepairNode":
            return {"max_attempts": 2, "attempts": sum(len(row.get("repair_attempts", [])) for row in state["files"])}
        if node == "SecondJudgePassNode":
            return {"completed": True, "remaining_residue": sorted({item for row in state["files"] for item in row.get("source_residue", [])})}
        if node == "FinalQualityGateNode":
            return {"snowflake_ready": all(row.get("snowflake_ready") for row in state["files"]) if state["files"] else False}
        if node == "DeepAgentReviewNode":
            return {"specialists": ["DialectDetectionAgent", "DbtSemanticsAgent", "SqlRewriteAgent", "SnowflakeSyntaxAgent", "IncrementalModelAgent", "PerformanceAgent", "ValidationAgent", "ReportAgent"]}
        if node == "CopilotContextNode":
            return {"registered": True}
        return {"completed": True}


def _flatten(items: list[Any]) -> str:
    return ", ".join(str(item) for item in items) or "none"
