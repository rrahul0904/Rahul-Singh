from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any, Literal

from agents.tools.safety import redact_secrets

ProviderName = Literal["offline", "ollama", "openai", "azure_openai", "anthropic", "snowflake_cortex_later", "cortex", "hermes", "mock"]
ActionCategory = Literal["READ_ONLY", "APPROVAL_REQUIRED", "BLOCKED"]


READ_ONLY_ACTIONS = {
    "get_migration_project_status",
    "get_agent_run_status",
    "get_validation_summary",
    "get_cost_estimate",
    "search_migration_logs",
    "summarize_failed_run",
    "explain_validation_mismatch",
    "explain_cost_spike",
    "get_snowflake_services_health",
    "ask_cortex_analyst",
    "search_cortex_documents",
    "search_cortex_logs",
    "summarize_with_cortex",
    "profile_with_snowpark",
    "get_snowflake_query_history",
    "get_snowflake_cost_intelligence",
}

APPROVAL_REQUIRED_ACTIONS = {
    "approve_generated_ddl",
    "reject_generated_ddl",
    "retry_failed_step",
    "cancel_run",
    "execute_approved_ddl",
}

BLOCKED_ACTIONS = {
    "direct_arbitrary_sql_execution",
    "read_env",
    "print_secrets",
    "modify_snowflake_users_roles",
    "drop_database",
    "drop_schema",
    "truncate_table",
    "delete_without_where",
    "update_without_where",
    "grant_ownership",
}

DANGEROUS_ACTION_KEYWORDS = {
    "drop database": "drop_database",
    "drop schema": "drop_schema",
    "truncate": "truncate_table",
    "delete without where": "delete_without_where",
    "update without where": "update_without_where",
    "grant ownership": "grant_ownership",
    "read .env": "read_env",
    "print secret": "print_secrets",
    "arbitrary sql": "direct_arbitrary_sql_execution",
}

_DANGEROUS_SQL_PATTERNS = (
    r"\bdrop\s+database\b",
    r"\bdrop\s+schema\b",
    r"\btruncate\b",
    r"\bdelete\s+from\s+[\w\".]+\s*(;|$)",
    r"\bupdate\s+[\w\".]+\s+set\b(?!.*\bwhere\b)",
    r"\balter\s+user\b",
    r"\balter\s+account\b",
    r"\bgrant\s+ownership\b",
)


def classify_action(action_type: str) -> ActionCategory:
    action = (action_type or "").strip().lower()
    if action in BLOCKED_ACTIONS:
        return "BLOCKED"
    if action in APPROVAL_REQUIRED_ACTIONS:
        return "APPROVAL_REQUIRED"
    if action in READ_ONLY_ACTIONS:
        return "READ_ONLY"
    for keyword, blocked in DANGEROUS_ACTION_KEYWORDS.items():
        if keyword in action:
            return "BLOCKED" if blocked in BLOCKED_ACTIONS else "APPROVAL_REQUIRED"
    return "BLOCKED"


def safe_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    return redact_secrets(payload or {})


def payload_has_blocked_sql(payload: dict[str, Any] | None) -> bool:
    def walk(value: Any) -> list[str]:
        if isinstance(value, dict):
            found: list[str] = []
            for key, item in value.items():
                if str(key).lower() in {"sql", "ddl", "statement", "query"}:
                    found.extend(walk(item))
                elif isinstance(item, (dict, list)):
                    found.extend(walk(item))
            return found
        if isinstance(value, list):
            found: list[str] = []
            for item in value:
                found.extend(walk(item))
            return found
        if isinstance(value, str):
            return [value]
        return []

    for sql in walk(payload or {}):
        if any(re.search(pattern, sql, re.IGNORECASE | re.DOTALL) for pattern in _DANGEROUS_SQL_PATTERNS):
            return True
    return False


@dataclass
class CopilotAnswer:
    provider: str
    answer: str
    grounded: bool = True
    source_context: dict[str, Any] = field(default_factory=dict)
    proposed_action: dict[str, Any] | None = None
    health: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "answer": self.answer,
            "grounded": self.grounded,
            "source_context": safe_context(self.source_context),
            "proposed_action": safe_context(self.proposed_action) if self.proposed_action else None,
            "health": safe_context(self.health),
        }


class CopilotProvider(ABC):
    name: ProviderName
    display_name: str

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def send_message(self, message: str, context: dict[str, Any] | None = None) -> CopilotAnswer:
        raise NotImplementedError

    async def preview_action(self, action_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        category = "BLOCKED" if payload_has_blocked_sql(payload) else classify_action(action_type)
        return {
            "action_type": action_type,
            "category": category,
            "allowed": category != "BLOCKED",
            "requires_confirmation": category == "APPROVAL_REQUIRED",
            "payload": safe_context(payload),
        }
