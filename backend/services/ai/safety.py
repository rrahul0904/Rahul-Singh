from __future__ import annotations

import re
from typing import Any

from agents.tools.safety import redact_secrets as _base_redact

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
HOST_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:corp|internal|local|com|net|org|io|cloud)\b", re.I)
PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.I | re.S,
)


def redact_for_ai(payload: Any, *, redact_emails: bool = False, redact_hostnames: bool = False) -> Any:
    redacted = _base_redact(payload)
    if isinstance(redacted, str):
        text = PRIVATE_KEY_BLOCK_RE.sub("***REDACTED_PRIVATE_KEY***", redacted)
        if redact_emails:
            text = EMAIL_RE.sub("***REDACTED_EMAIL***", text)
        if redact_hostnames:
            text = HOST_RE.sub("***REDACTED_HOST***", text)
        return text
    if isinstance(redacted, dict):
        return {key: redact_for_ai(value, redact_emails=redact_emails, redact_hostnames=redact_hostnames) for key, value in redacted.items()}
    if isinstance(redacted, list):
        return [redact_for_ai(item, redact_emails=redact_emails, redact_hostnames=redact_hostnames) for item in redacted]
    return redacted


def safe_base_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    value = re.sub(r"://([^:/@]+):([^@]+)@", r"://***:***@", value)
    value = re.sub(r"(?i)([?&](?:api[_-]?key|token|password|secret)=)[^&#]+", r"\1***", value)
    return value.rstrip("/")
