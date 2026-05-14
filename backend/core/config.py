"""
UMA Platform — Configuration
All settings loaded from environment variables / .env file.
Fails fast on startup if required production values are missing.
"""

import logging
import os
import secrets
import base64
from typing import List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("uma.config")

PLACEHOLDER_SECRET_KEYS = {
    "",
    "change-me-in-production",
    "your-random-64-char-secret-here-change-me",
    "replace-with-a-random-64-char-secret",
    "test-secret-key-for-pytest-only-do-not-use-in-prod",
}

PLACEHOLDER_ENCRYPTION_KEYS = {
    "",
    "replace-with-generated-value",
    "replace-with-a-fernet-key",
    "replace-with-a-fernet-key-generated-for-this-install",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )

    # ── App ──────────────────────────────────────────────────
    APP_NAME:    str = "UMA Platform"
    APP_VERSION: str = "1.2.0"
    BUILD_SHA:   str = ""
    BUILD_TIME:  str = ""
    ENVIRONMENT: str = Field(default="development",
                              description="development | staging | production")
    DEBUG:       bool = False
    SECRET_KEY:  str  = ""

    # ── Encryption ───────────────────────────────────────────
    UMA_ENCRYPTION_KEY:  str = ""
    UMA_ENCRYPTION_KEYS: str = ""   # rotation list, comma-separated

    # ── Database ─────────────────────────────────────────────
    DATABASE_URL:       str = "postgresql+asyncpg://uma:uma@postgres:5432/uma"
    DB_POOL_SIZE:       int = 20
    DB_MAX_OVERFLOW:    int = 10
    DB_POOL_TIMEOUT:    int = 30
    DB_POOL_RECYCLE:    int = 3600   # recycle after 1h (avoids stale conns)

    # ── Redis ────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── CORS ─────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    APP_BASE_URL: str = "http://localhost:5173"
    API_BASE_URL: str = "http://localhost:8000"


    # ── Snowflake defaults (overridable per connection) ──────
    SNOWFLAKE_ACCOUNT:   str = ""
    SNOWFLAKE_USER:      str = ""
    SNOWFLAKE_PASSWORD:  str = ""
    SNOWFLAKE_WAREHOUSE: str = "COMPUTE_WH"
    SNOWFLAKE_DATABASE:  str = "ANALYTICS_DB"
    SNOWFLAKE_SCHEMA:    str = "RAW"
    SNOWFLAKE_ROLE:      str = "SYSADMIN"

    # ── AWS S3 Staging ───────────────────────────────────────
    AWS_ACCESS_KEY_ID:     str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION:            str = "us-east-1"
    S3_STAGING_BUCKET:     str = ""

    # ── Azure ────────────────────────────────────────────────
    AZURE_STORAGE_ACCOUNT: str = ""
    AZURE_STORAGE_KEY:     str = ""
    AZURE_CONTAINER:       str = ""

    # ── AI ───────────────────────────────────────────────────
    ANTHROPIC_API_KEY:        str = ""
    ANTHROPIC_MODEL:          str = "claude-3-5-sonnet-latest"
    OPENAI_API_KEY:           str = ""
    OPENAI_MODEL:             str = "gpt-4o"
    AZURE_OPENAI_API_KEY:     str = ""
    AZURE_OPENAI_ENDPOINT:    str = ""
    AZURE_OPENAI_DEPLOYMENT:  str = "gpt-4"
    AZURE_OPENAI_API_VERSION: str = "2024-02-01"
    INTERNAL_LLM_ENDPOINT:    str = ""
    INTERNAL_LLM_MODEL:       str = "local-model"
    INTERNAL_LLM_API_KEY:     str = ""
    AIRGAPPED_MODE:           bool = False
    CORTEX_SEMANTIC_MODEL:    str = ""
    COPILOT_PROVIDER:         str = "auto"
    HERMES_AGENT_URL:         str = ""
    HERMES_AGENT_TOKEN:       str = ""
    CORTEX_ENABLED:           bool = True
    CORTEX_LLM_MODEL:         str = "snowflake-arctic"
    CORTEX_SEARCH_SERVICE:    str = ""
    CORTEX_DOCUMENT_SEARCH_SERVICE: str = ""
    AI_PROVIDER:              str = "auto"
    AI_BASE_URL:              str = ""
    AI_API_KEY:               str = ""
    AI_CHAT_MODEL:            str = ""
    AI_TEMPERATURE:           float = 0.1
    AI_MAX_TOKENS:            int = 8192
    AI_TIMEOUT_SECONDS:       int = 60
    AI_STRUCTURED_OUTPUT_SUPPORTED: bool = True
    AI_REDACT_EMAILS:         bool = False
    AI_REDACT_HOSTNAMES:      bool = False
    OLLAMA_ENABLED:           bool = False
    OLLAMA_BASE_URL:          str = "http://localhost:11434"
    OLLAMA_CHAT_MODEL:        str = "llama3.1"
    OLLAMA_EMBEDDING_MODEL:   str = "nomic-embed-text"
    OLLAMA_TIMEOUT_SECONDS:   int = 30
    RAG_ENABLED:              bool = True
    RAG_VECTOR_STORE:         str = "keyword"
    RAG_INDEX_PATH:           str = "data/rag_index"
    RAG_CHUNK_SIZE:           int = 1200
    RAG_CHUNK_OVERLAP:        int = 150
    RAG_MAX_RESULTS:          int = 8
    RAG_TOP_K:                int = 8
    RAG_MAX_CONTEXT_TOKENS:   int = 12000
    RAG_EMBEDDING_PROVIDER:   str = "offline_keyword"
    RAG_EMBEDDING_MODEL:      str = "offline_keyword"
    RAG_EMBEDDING_DIM:        int = 256
    RAG_EMBEDDING_BATCH_SIZE: int = 16

    # ── Alerting ─────────────────────────────────────────────
    SLACK_WEBHOOK_URL:   str = ""
    ALERT_ON_SUCCESS:    bool = False
    SMTP_HOST:           str = ""
    SMTP_PORT:           int = 587
    SMTP_USER:           str = ""
    SMTP_PASSWORD:       str = ""
    SMTP_FROM:           str = "uma@yourcompany.com"  # backward-compatible alias
    SMTP_FROM_EMAIL:     str = ""
    SMTP_FROM_NAME:      str = "UMA Platform"
    SMTP_TLS:            bool = True                   # backward-compatible alias
    SMTP_USE_TLS:        bool = True
    ALERT_EMAIL_TO:      str = ""
    REQUIRE_EMAIL_VERIFICATION: bool = False


    # ── Worker / Jobs ────────────────────────────────────────
    MAX_CONCURRENT_JOBS: int = 5
    JOB_TIMEOUT_SECONDS: int = 86400

    # ── Observability ────────────────────────────────────────
    SENTRY_DSN:        str = ""
    OTLP_ENDPOINT:     str = ""
    LOG_JSON:          bool = False   # JSON structured logging
    LOG_LEVEL:         str  = "INFO"

    # ═══ Validators ═══════════════════════════════════════════

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_env(cls, v):
        v = v.lower()
        if v not in ("development", "staging", "production"):
            raise ValueError("ENVIRONMENT must be one of: development, staging, production")
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            if v.startswith("["):
                import json
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def validate_production(self):
        """Hard-fail if running in production without required values."""
        if self.ENVIRONMENT != "production":
            return self

        errors = []

        if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
            errors.append("SECRET_KEY must be set and ≥32 chars in production")

        if self.SECRET_KEY in PLACEHOLDER_SECRET_KEYS:
            errors.append("SECRET_KEY must not be a default/placeholder value")

        if self.UMA_ENCRYPTION_KEY in PLACEHOLDER_ENCRYPTION_KEYS:
            errors.append(
                "UMA_ENCRYPTION_KEY is required in production. Generate with:\n"
                "  python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        else:
            try:
                decoded = base64.urlsafe_b64decode(self.UMA_ENCRYPTION_KEY.encode())
                if len(decoded) != 32:
                    raise ValueError("invalid Fernet key length")
            except Exception:
                errors.append("UMA_ENCRYPTION_KEY must be a valid Fernet key in production")

        if self.DATABASE_URL == "postgresql+asyncpg://uma:uma@postgres:5432/uma":
            errors.append("DATABASE_URL must be explicitly configured for production")

        if "*" in self.CORS_ORIGINS:
            errors.append("CORS_ORIGINS must not contain '*' in production")

        if self.DEBUG:
            errors.append("DEBUG must be False in production")

        if errors:
            msg = "Production configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(msg)

        return self


def _load_settings() -> Settings:
    """Load settings. Generate a dev SECRET_KEY if not set."""
    try:
        s = Settings()
    except Exception as e:
        logger.critical(f"Configuration error:\n{e}")
        raise

    # Dev convenience: generate SECRET_KEY if missing in non-prod
    if s.ENVIRONMENT != "production" and not s.SECRET_KEY:
        s.SECRET_KEY = secrets.token_urlsafe(48)
        logger.warning(
            "SECRET_KEY not set — generated a random one for this process only. "
            "Set SECRET_KEY in .env to persist across restarts."
        )

    return s


settings = _load_settings()
