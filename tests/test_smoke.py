"""
UMA Platform — Minimal Smoke Test Suite

Run: pytest -q tests/

These tests verify:
- All critical modules import without error
- FastAPI app instantiates
- All declared routes are registered
- Core auth primitives (password hashing, JWT) are sane

These are NOT integration tests against a live API. For that, use
  quick-test.sh (requires Docker)
or hit /api/docs with Swagger's "Try it out".
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Set minimal env so config loads
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")


def test_core_modules_import():
    """All core modules must import without error."""
    from core import config, database, auth, security, middleware, audit, lockout
    assert config.settings is not None


def test_all_routes_import():
    """Every route module must import."""
    from api.routes import (
        auth, connections, jobs, tables, validation, ai, health,
        snowflake, projects, drift, settings, syncs, copilot,
        replication, control_plane,
    )
    # Each should expose a router
    for module_name in ("auth", "connections", "jobs", "tables", "validation",
                        "ai", "health", "snowflake", "projects", "drift",
                        "settings", "syncs", "copilot", "replication", "control_plane"):
        mod = __import__(f"api.routes.{module_name}", fromlist=["router"])
        assert hasattr(mod, "router"), f"{module_name} missing router"


def test_fastapi_app_builds():
    """The FastAPI app must instantiate."""
    from main import app
    assert app is not None
    # Should have at least these paths registered
    paths = {route.path for route in app.routes}
    required = [
        "/api/health",
        "/api/health/services",
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/change-password",
        "/api/auth/users/{user_id}/reset-password",
        "/api/connections",
        "/api/jobs",
        "/api/snowflake/query",
        "/api/snowflake/diagnose",
        "/api/snowflake/readiness",
        "/api/drift/check",
        "/api/drift/check-adhoc",
        "/api/syncs/profiles",
        "/api/replication/overview",
        "/api/replication/jobs",
        "/api/copilot/providers",
        "/api/copilot/snowflake-services",
        "/api/control-plane/runs",
        "/api/sql-conversion/runs",
        "/api/migration-intelligence/runs",
        "/api/provision/runs",
    ]
    for p in required:
        assert any(p in pp for pp in paths), f"Route {p} not registered"


def test_password_hash_roundtrip():
    from core.auth import hash_password, verify_password
    h = hash_password("CorrectHorseBatteryStaple123!")
    assert verify_password("CorrectHorseBatteryStaple123!", h) is True
    assert verify_password("wrong", h) is False


def test_jwt_roundtrip():
    from core.auth import create_jwt, decode_jwt
    t = create_jwt("user-123", "admin", "test@example.com")
    payload = decode_jwt(t)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"


def test_jwt_tampered_fails():
    from core.auth import create_jwt, decode_jwt
    t = create_jwt("user-123", "admin", "test@example.com")
    tampered = t[:-5] + "XXXXX"
    assert decode_jwt(tampered) is None


def test_api_token_generation():
    from core.auth import generate_api_token
    token, hash_, prefix = generate_api_token()
    assert token.startswith("uma_")
    assert len(token) > 20
    assert len(hash_) == 64  # sha256 hex
    assert prefix.startswith("uma_")


def test_sql_classification():
    """SQL injection guard should catch dangerous patterns."""
    from api.routes.snowflake import classify_sql
    # Read-only
    assert classify_sql("SELECT * FROM x")[0] == "read"
    assert classify_sql("SHOW TABLES")[0] == "read"
    # Writes
    assert classify_sql("INSERT INTO x VALUES (1)")[0] == "write"
    assert classify_sql("UPDATE x SET y=1")[0] == "write"
    # Dangerous
    assert classify_sql("DROP DATABASE prod")[0] == "dangerous"
    assert classify_sql("TRUNCATE TABLE foo")[0] == "dangerous"
    # With comments
    assert classify_sql("-- hello\nSELECT 1")[0] == "read"


def test_snowflake_diagnose_no_credentials():
    """Diagnose should run network checks without creds, then cleanly skip auth."""
    import asyncio
    from api.routes.snowflake import diagnose_connection
    from unittest.mock import MagicMock

    user = MagicMock()
    user.email = "test@example.com"

    # Empty account → fail on step 1
    result = asyncio.run(diagnose_connection({}, user))
    assert result["ok"] is False
    step_names = [c["step"] for c in result["checks"]]
    assert step_names[0] == "1_account_format"
    assert result["checks"][0]["status"] == "fail"


def test_snowflake_diagnose_bad_account():
    """DNS failures should be reported cleanly."""
    import asyncio
    import socket
    from api.routes.snowflake import diagnose_connection
    from unittest.mock import MagicMock, patch

    user = MagicMock()
    user.email = "test@example.com"

    with patch("socket.gethostbyname", side_effect=socket.gaierror("mock DNS failure")):
        result = asyncio.run(diagnose_connection(
            {"account": "this-account-definitely-does-not-exist-xyz123"}, user
        ))
    step_statuses = {c["step"]: c["status"] for c in result["checks"]}
    # Format is ok, DNS fails
    assert step_statuses.get("1_account_format") == "ok"
    assert step_statuses.get("2_dns_resolution") == "fail"
    assert result["ok"] is False


def test_snowflake_mfa_request_schema():
    from api.routes.snowflake import SnowflakeDiagnosticRequest

    body = SnowflakeDiagnosticRequest(
        account="example-account.us-east-1",
        user="example_user",
        password="secret",
        warehouse="COMPUTE_WH",
        auth_method="password_mfa",
        mfa_passcode="123456",
    )
    assert body.auth_method == "password_mfa"
    assert body.mfa_passcode == "123456"


def test_snowflake_connector_maps_mfa_passcode():
    from connectors.snowflake_connector import SnowflakeConnector
    from unittest.mock import MagicMock, patch

    fake_conn = MagicMock()
    connector = SnowflakeConnector({
        "account": "example-account.us-east-1",
        "user": "example_user",
        "password": "secret",
        "warehouse": "COMPUTE_WH",
        "auth_method": "password_mfa",
        "mfa_passcode": "123456",
    })
    with patch("snowflake.connector.connect", return_value=fake_conn) as connect:
        connector.connect()

    assert connect.call_args.kwargs["passcode"] == "123456"
    assert "mfa_passcode" not in connector.config


def test_snowflake_workspace_session_schema():
    from api.routes.snowflake import QueryRequest, SnowflakeRuntimeAuth, SnowflakeWorkspaceSessionRequest

    session = SnowflakeWorkspaceSessionRequest(
        connection_id="conn-123",
        auth_method="password_mfa",
        mfa_passcode="123456",
    )
    runtime = SnowflakeRuntimeAuth(workspace_session_id="session-123")
    query = QueryRequest(sql="SELECT 1", connection_id="conn-123", workspace_session_id="session-123")

    assert session.auth_method == "password_mfa"
    assert session.mfa_passcode == "123456"
    assert runtime.workspace_session_id == "session-123"
    assert query.workspace_session_id == "session-123"


def test_mfa_passcode_not_persisted_in_connection_payloads():
    from api.routes.connections import _strip_ephemeral_credentials

    assert _strip_ephemeral_credentials({
        "user": "Rahul",
        "password": "secret",
        "mfa_passcode": "123456",
        "passcode": "654321",
    }) == {"user": "Rahul", "password": "secret"}


def test_password_policy_rejects_weak():
    from api.routes.auth import validate_password_strength
    from fastapi import HTTPException

    # Too short
    with pytest.raises(HTTPException):
        validate_password_strength("Short1!")
    # No uppercase
    with pytest.raises(HTTPException):
        validate_password_strength("alllowercase1!")
    # No special char
    with pytest.raises(HTTPException):
        validate_password_strength("NoSpecialChar1")

    # Valid should not raise
    validate_password_strength("CorrectHorse123!")


def test_admin_password_reset_schema():
    from api.routes.auth import AdminPasswordResetRequest

    body = AdminPasswordResetRequest(new_password="CorrectHorse123!")
    assert body.new_password == "CorrectHorse123!"


def test_models_register_correctly():
    """SQLAlchemy models should all be importable from `models`."""
    import models
    for name in ("User", "Connection", "Job", "JobTask", "JobLog",
                 "ValidationRule", "Project", "Environment",
                 "SyncProfile", "SyncRun", "ApiToken"):
        assert hasattr(models, name), f"models.{name} missing"


def test_orchestrator_capabilities():
    """Migration orchestrator should expose the engine support matrix."""
    import asyncio
    from services.migration_orchestrator import execution_capabilities

    caps = asyncio.run(execution_capabilities())
    assert caps["default_engine"] == "auto"
    assert caps["real_engine"]["destination"] == "snowflake"
    assert "postgres" in caps["real_engine"]["sources"]


def test_credential_encryption_roundtrip():
    """Fernet encryption must encrypt+decrypt credentials cleanly."""
    os.environ["UMA_ENCRYPTION_KEY"] = "cY3Kn2QdFYz7-h6m0u8rLsVqW8Yz4kNd1MpXa9QrStU="
    from core.security import CredentialCipher
    cipher = CredentialCipher.from_env()
    creds = {"user": "alice", "password": "s3cret!"}
    enc = cipher.encrypt_dict(creds)
    assert enc.get("__encrypted__") is True
    dec = cipher.decrypt_dict(enc)
    assert dec == creds


def test_production_rejects_default_secret_key(monkeypatch):
    from core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "replace-with-a-random-64-char-secret")
    monkeypatch.setenv("UMA_ENCRYPTION_KEY", "cY3Kn2QdFYz7-h6m0u8rLsVqW8Yz4kNd1MpXa9QrStU=")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://uma:uma@db.example.com:5432/uma")

    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(_env_file=None)


def test_production_requires_valid_encryption_key(monkeypatch):
    from core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "prod-secret-key-with-more-than-thirty-two-characters")
    monkeypatch.setenv("UMA_ENCRYPTION_KEY", "replace-with-a-fernet-key-generated-for-this-install")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://uma:uma@db.example.com:5432/uma")

    with pytest.raises(ValueError, match="UMA_ENCRYPTION_KEY"):
        Settings(_env_file=None)


def test_production_rejects_default_database_url(monkeypatch):
    from core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "prod-secret-key-with-more-than-thirty-two-characters")
    monkeypatch.setenv("UMA_ENCRYPTION_KEY", "cY3Kn2QdFYz7-h6m0u8rLsVqW8Yz4kNd1MpXa9QrStU=")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://uma:uma@postgres:5432/uma")

    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(_env_file=None)


def test_env_example_contains_only_safe_placeholders():
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", ".env.example"),
        os.path.join(os.path.dirname(__file__), "..", "backend", ".env.example"),
        os.path.join(os.getcwd(), ".env.example"),
        os.path.join(os.getcwd(), "backend", ".env.example"),
    ]
    env_example = next((path for path in candidates if os.path.exists(path)), None)
    assert env_example is not None
    contents = open(env_example, encoding="utf-8").read()

    assert "sk-your-openai-key" not in contents
    assert "your_snowflake_password" not in contents
    assert "SNOWFLAKE_PASSWORD=\n" in contents
    assert "OPENAI_API_KEY=\n" in contents
    assert "UMA_ENCRYPTION_KEY=replace-with-a-fernet-key-generated-for-this-install" in contents


if __name__ == "__main__":
    import subprocess
    subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"])
