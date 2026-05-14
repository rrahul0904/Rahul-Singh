from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ProviderMode = Literal[
    "offline_deterministic",
    "openai_compatible_self_hosted",
    "ollama_local",
    "openai",
    "azure_openai",
    "anthropic",
    "snowflake_cortex_later",
]


@dataclass
class AiProviderConfig:
    mode: str = "offline_deterministic"
    base_url: str = ""
    api_key: str = ""
    model: str = "offline"
    timeout: int = 60
    max_tokens: int = 4096
    temperature: float = 0.1
    structured_output_supported: bool = False


@dataclass
class AiProviderStatus:
    active_provider: str
    available: bool
    model: str = "offline"
    base_url: str = ""
    chat_supported: bool = False
    embeddings_supported: bool = False
    rag_supported: bool = False
    patch_proposal_supported: bool = False
    structured_output_supported: bool = False
    local_private_mode: bool = True
    quality_warning: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_provider": self.active_provider,
            "available": self.available,
            "model": self.model,
            "base_url": self.base_url,
            "chat_supported": self.chat_supported,
            "embeddings_supported": self.embeddings_supported,
            "rag_supported": self.rag_supported,
            "patch_proposal_supported": self.patch_proposal_supported,
            "structured_output_supported": self.structured_output_supported,
            "local_private_mode": self.local_private_mode,
            "quality_warning": self.quality_warning,
            "error": self.error,
        }


@dataclass
class AiChatRequest:
    messages: list[dict[str, str]]
    system: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    json_mode: bool = False


@dataclass
class AiChatResponse:
    content: str
    provider: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)
    available: bool = True
    error: str | None = None


@dataclass
class AiPatchProposal:
    proposed_sql: str
    explanation: str
    changes: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.0
    manual_review_required: bool = True
    expected_readiness_impact: str = "Advisory only. UMA judge gates decide readiness."
    citations: list[dict[str, Any]] = field(default_factory=list)
