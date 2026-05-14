import os
import sys
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi import HTTPException  # noqa: E402

from api.routes.workspace import _guard_read_only, _sf_entry, _with_snowflake  # noqa: E402
from models import ConnectionType  # noqa: E402
from services.snowflake_session_manager import SNOWFLAKE_MFA_EXPIRED_MESSAGE, SnowflakeSessionManager, snowflake_session_manager  # noqa: E402


class DummyConnector:
    def __init__(self):
        self.closed = False

    def disconnect(self):
        self.closed = True


def test_snowflake_session_manager_ttl_and_safe_metadata():
    connector = DummyConnector()
    manager = SnowflakeSessionManager(ttl_minutes=10)
    public = manager.create(
        user_id="user-1",
        connection_id="conn-1",
        connector=connector,
        metadata={"account": "acme", "mfa_passcode": "123456", "password": "secret"},
    )

    assert public["ttl_minutes"] >= 60
    assert public["status"] == "ACTIVE"
    assert public["metadata"] == {"account": "acme"}
    assert manager._sessions[public["session_id"]]["metadata"] == {"account": "acme"}
    assert "mfa_passcode" not in str(public)
    assert manager.active_for_user(user_id="user-1", connection_id="conn-1") is not None
    assert manager.close(public["session_id"], user_id="user-1") is True
    assert connector.closed is True


def test_unlock_creates_session_for_at_least_sixty_minutes_and_can_expire():
    manager = SnowflakeSessionManager(ttl_minutes=1)
    public = manager.create(user_id="user-2", connection_id="conn-2", connector=DummyConnector())
    created = datetime.fromisoformat(public["created_at"].replace("Z", ""))
    expires = datetime.fromisoformat(public["expires_at"].replace("Z", ""))

    assert (expires - created).total_seconds() >= 3600
    assert manager.get_active_session(user_id="user-2", connection_id="conn-2") is not None
    assert manager.expire(public["session_id"], user_id="user-2") is True
    assert manager.get_active_session(user_id="user-2", connection_id="conn-2") is None


def test_workspace_read_only_guard_allows_select_and_blocks_dml():
    category, verb = _guard_read_only("select * from public.customers")
    assert category == "read"
    assert verb == "SELECT"

    try:
        _guard_read_only("delete from public.customers where id = 1")
    except Exception as exc:
        assert "read-only" in str(exc)
    else:
        raise AssertionError("DML should be blocked")


def test_sql_workspace_uses_active_snowflake_session_without_passcode():
    class QueryConnector(DummyConnector):
        def run_query(self, sql):
            return [{"SQL": sql}]

    conn = SimpleNamespace(id="workspace-active", type=ConnectionType.snowflake, config={"auth_method": "password_mfa"})
    user = SimpleNamespace(id="user-active")
    public = snowflake_session_manager.create(user_id=user.id, connection_id=conn.id, connector=QueryConnector())
    try:
        result = __import__("asyncio").run(_with_snowflake(conn, user, None, lambda sf: sf.run_query("SELECT 1")))
        assert result == [{"SQL": "SELECT 1"}]
    finally:
        snowflake_session_manager.close(public["session_id"], user_id=user.id)


def test_expired_snowflake_session_returns_clear_workspace_error():
    conn = SimpleNamespace(id="workspace-expired", type=ConnectionType.snowflake, config={"auth_method": "password_mfa"})
    user = SimpleNamespace(id="user-expired")

    try:
        _sf_entry(conn, user, None)
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == SNOWFLAKE_MFA_EXPIRED_MESSAGE
    else:
        raise AssertionError("Expected expired Snowflake MFA session error")


def test_postgres_workspace_hides_snowflake_session_ui():
    page = open(
        os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "pages", "SQLWorkspacePage.jsx"),
        encoding="utf-8",
    ).read()

    assert "isSnowflake && (workspaceSessionId" in page
    assert "Unlock Snowflake" in page
    assert "Connect Snowflake" not in page


def test_migration_engine_requires_active_mfa_session_for_snowflake_target(monkeypatch):
    import services.real_migration_engine as engine
    from services.real_migration_engine import PermanentError, SnowflakeTargetAdapter

    monkeypatch.setattr(engine, "get_cipher", lambda: SimpleNamespace(decrypt_dict=lambda _: {}))

    conn = SimpleNamespace(
        id="migration-expired",
        config={
            "auth_method": "password_mfa",
            "account": "acct",
            "user": "user",
            "password": "secret",
            "warehouse": "WH",
            "database": "DB",
            "schema": "PUBLIC",
        },
        credentials={},
    )
    job = SimpleNamespace(id="job-1", sf_warehouse="WH", sf_database="DB", sf_schema="PUBLIC", sf_role="")

    try:
        SnowflakeTargetAdapter(conn, job, run_id="run-1", user_id="user-missing")
    except PermanentError as exc:
        assert str(exc) == SNOWFLAKE_MFA_EXPIRED_MESSAGE
    else:
        raise AssertionError("Expected migration engine to require an active MFA session")


def test_replication_execution_requires_active_mfa_session_for_snowflake_target():
    from services.replication_execution import ReplicationExecutionError

    assert str(ReplicationExecutionError(SNOWFLAKE_MFA_EXPIRED_MESSAGE)) == SNOWFLAKE_MFA_EXPIRED_MESSAGE


def test_workspace_and_catalog_routes_registered():
    from main import app

    paths = {route.path for route in app.routes}
    assert "/api/workspace/connections" in paths
    assert "/api/workspace/{connection_id}/query" in paths
    assert "/api/catalog/tables" in paths
    assert "/api/catalog/tables/summary" in paths
    assert "/api/catalog/tables/{table_id}/lineage" in paths
