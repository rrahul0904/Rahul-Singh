from __future__ import annotations

import copy
import os
import re
from typing import Any


READ_ONLY_TOOLS = {"inspect_source_schema", "profile_source", "estimate_snowflake_cost"}
PLANNING_TOOLS = {"assess_complexity", "plan_data_movement", "generate_cutover_plan"}
STAGING_TOOLS = {"generate_snowflake_ddl", "stage_ddl_for_review", "stage_cortex_index_plan"}
EXECUTION_TOOLS = {"execute_approved_ddl", "create_load_job", "run_validation"}
PRODUCTION_TOOLS = {"run_cutover", "execute_production_ddl", "start_cdc"}

_DANGEROUS_PATTERNS = [
    r"\bdrop\s+database\b",
    r"\bdrop\s+schema\b",
    r"\btruncate\b",
    r"\bdelete\s+from\s+[\w\".]+\s*(;|$)",
    r"\bupdate\s+[\w\".]+\s+set\b(?!.*\bwhere\b)",
    r"\balter\s+account\b",
    r"\balter\s+user\b",
    r"\bgrant\s+ownership\b",
    r"\bexternal\s+access\b",
]

_SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)([\"'](?:password|passwd|pwd|token|api[_-]?key|secret|client_secret|private[_-]?key|oauth[_-]?secret)[\"']\s*:\s*[\"'])[^\"']+([\"'])"),
    re.compile(r"(?i)\b(password|passwd|pwd|token|api[_-]?key|secret|client_secret|private[_-]?key|oauth[_-]?secret)\b\s*[:=]\s*(['\"]?)[^'\"\s,;]+\2"),
    re.compile(r"(?i)\b(private_key_file)\b\s*[:=]\s*(['\"]?)[^'\"\s,;]+\2"),
    re.compile(r"(?i)(jdbc:[^\s]+://[^/\s:]+):([^@\s]+)@"),
    re.compile(r"(?i)(snowflake|postgres|mysql|oracle|sqlserver)://([^:\s/@]+):([^@\s]+)@"),
]


def is_read_only_sql(sql: str) -> bool:
    text = (sql or "").strip().lower()
    if not text:
        return False
    if not re.match(r"^(select|show|describe|desc|with)\b", text):
        return False
    return not any(re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in _DANGEROUS_PATTERNS)


def requires_approval(action_type: str) -> bool:
    action = (action_type or "").strip()
    return action in EXECUTION_TOOLS or action in PRODUCTION_TOOLS or action.startswith("execute_")


def validate_allowed_schema(schema: str) -> bool:
    name = (schema or "").strip()
    if not name:
        return False
    blocked = {"information_schema", "pg_catalog", "account_usage"}
    return name.lower() not in blocked and bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name))


def redact_secrets(payload: Any) -> Any:
    secret_keys = ("password", "token", "secret", "private_key", "connection_string", "certificate")
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            if any(s in str(key).lower() for s in secret_keys):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = redact_secrets(value)
        return redacted
    if isinstance(payload, list):
        return [redact_secrets(item) for item in payload]
    if isinstance(payload, str):
        text = payload
        for env_name, env_value in os.environ.items():
            if env_value and any(token in env_name.upper() for token in ("SECRET", "TOKEN", "PASSWORD", "KEY")):
                text = text.replace(env_value, "***REDACTED***")
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.pattern.startswith("(?i)([\"']"):
                text = pattern.sub(r"\1***REDACTED***\2", text)
            elif pattern.pattern.startswith("(?i)(jdbc"):
                text = pattern.sub(r"\1:***REDACTED***@", text)
            elif "://" in pattern.pattern:
                text = pattern.sub(r"\1://\2:***REDACTED***@", text)
            else:
                text = pattern.sub(lambda match: f"{match.group(1)}=***REDACTED***", text)
        return text
    return copy.deepcopy(payload)


def safe_log_payload(payload: Any) -> Any:
    return redact_secrets(payload)
