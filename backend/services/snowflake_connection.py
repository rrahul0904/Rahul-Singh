from __future__ import annotations

import os
from typing import Any

from cryptography.hazmat.primitives import serialization


SNOWFLAKE_KEY_PAIR_AUTH_METHODS = {"key_pair", "private_key", "jwt"}


def normalize_snowflake_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(raw or {})
    if cfg.get("username") and not cfg.get("user"):
        cfg["user"] = cfg.get("username")
    if cfg.get("schema_name") and not cfg.get("schema"):
        cfg["schema"] = cfg.get("schema_name")
    if cfg.get("dbname") and not cfg.get("database"):
        cfg["database"] = cfg.get("dbname")
    if cfg.get("account_identifier") and not cfg.get("account"):
        cfg["account"] = cfg.get("account_identifier")
    if cfg.get("private_key_pem") and not cfg.get("private_key"):
        cfg["private_key"] = cfg.get("private_key_pem")
    if cfg.get("passphrase") and not cfg.get("private_key_passphrase"):
        cfg["private_key_passphrase"] = cfg.get("passphrase")
    return cfg


def snowflake_auth_method(raw: dict[str, Any] | None) -> str:
    cfg = normalize_snowflake_config(raw)
    configured = str(cfg.get("auth_method") or "").strip().lower()
    if configured:
        return configured
    if cfg.get("private_key") or cfg.get("private_key_pem"):
        return "key_pair"
    return "password"


def snowflake_required_execution_fields(raw: dict[str, Any] | None) -> tuple[str, ...]:
    auth_method = snowflake_auth_method(raw)
    secret_field = "private_key" if auth_method in SNOWFLAKE_KEY_PAIR_AUTH_METHODS else "password"
    return ("account", "user", secret_field, "warehouse", "database", "schema")


def snowflake_private_key_der(raw: dict[str, Any] | None) -> bytes:
    cfg = normalize_snowflake_config(raw)
    pem = str(cfg.get("private_key") or "").strip()
    if not pem:
        raise ValueError("Snowflake key-pair authentication requires a PEM private key.")
    pem = pem.replace("\\n", "\n")
    passphrase = cfg.get("private_key_passphrase")
    password = str(passphrase).encode("utf-8") if passphrase else None
    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=password)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def snowflake_connect_kwargs(
    raw: dict[str, Any] | None,
    *,
    query_tag: str = "UMA_PLATFORM",
    client_session_keep_alive: bool = True,
    login_timeout: int | None = None,
    network_timeout: int | None = None,
) -> dict[str, Any]:
    cfg = normalize_snowflake_config(raw)
    auth_method = snowflake_auth_method(cfg)
    kwargs: dict[str, Any] = {
        "account": cfg.get("account"),
        "user": cfg.get("user"),
        "warehouse": cfg.get("warehouse"),
        "database": cfg.get("database"),
        "schema": cfg.get("schema"),
        "role": cfg.get("role"),
        "session_parameters": {"QUERY_TAG": query_tag},
        "client_session_keep_alive": bool(cfg.get("client_session_keep_alive", client_session_keep_alive)),
        "insecure_mode": os.getenv("SNOWFLAKE_INSECURE_MODE", "false").lower() == "true",
    }
    if login_timeout is not None:
        kwargs["login_timeout"] = login_timeout
    if network_timeout is not None:
        kwargs["network_timeout"] = network_timeout
    if auth_method in SNOWFLAKE_KEY_PAIR_AUTH_METHODS:
        kwargs["private_key"] = snowflake_private_key_der(cfg)
    else:
        kwargs["password"] = cfg.get("password", "")
        if auth_method == "password_mfa" and cfg.get("mfa_passcode"):
            kwargs["passcode"] = cfg["mfa_passcode"]
    return {key: value for key, value in kwargs.items() if value not in (None, "")}


def snowflake_execution_readiness(
    raw: dict[str, Any] | None,
    *,
    session_active: bool = False,
) -> dict[str, Any]:
    cfg = normalize_snowflake_config(raw)
    missing_fields = [field for field in snowflake_required_execution_fields(cfg) if not cfg.get(field)]
    auth_method = snowflake_auth_method(cfg)
    requires_mfa_session = auth_method == "password_mfa"

    if missing_fields:
        return {
            "status": "REQUIRES_CONFIGURATION",
            "can_execute_jobs": False,
            "missing_fields": missing_fields,
            "requires_mfa_session": requires_mfa_session,
            "session_active": session_active,
            "message": f"Snowflake job execution is blocked until these fields are configured: {', '.join(missing_fields)}.",
        }

    if requires_mfa_session and not session_active:
        return {
            "status": "REQUIRES_MFA_SESSION",
            "can_execute_jobs": False,
            "missing_fields": [],
            "requires_mfa_session": True,
            "session_active": False,
            "message": (
                "Snowflake connectivity is configured, but unattended jobs need an active Snowflake unlock session "
                "or a non-interactive auth method."
            ),
        }

    return {
        "status": "READY",
        "can_execute_jobs": True,
        "missing_fields": [],
        "requires_mfa_session": requires_mfa_session,
        "session_active": session_active,
        "message": "Snowflake connection is ready for job execution.",
    }
