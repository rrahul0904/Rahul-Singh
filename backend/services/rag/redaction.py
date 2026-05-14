from __future__ import annotations

from typing import Any

from core.config import settings
from services.ai.safety import redact_for_ai


def redact_rag_payload(payload: Any) -> Any:
    return redact_for_ai(
        payload,
        redact_emails=settings.AI_REDACT_EMAILS,
        redact_hostnames=settings.AI_REDACT_HOSTNAMES,
    )
