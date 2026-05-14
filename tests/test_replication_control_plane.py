import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")
os.environ.setdefault("REDIS_URL", "")

from core.database import Base  # noqa: E402
from models import (  # noqa: E402
    ConnectorHealthCheck,
    ReplicationConnection,
    ReplicationEvent,
    ReplicationJob,
    ReplicationJobTable,
    ReplicationPlan,
    ReplicationRun,
    ReplicationSource,
    ReplicationTableRun,
    gen_uuid,
)
from api.routes.replication import (  # noqa: E402
    JobTablesUpdate,
    ReplicationJobTablePayload,
    SourceDiscoverRequest,
    cancel_job,
    discover_source,
    pause_job,
    resume_job,
    start_job,
    update_job_tables,
    _test_sync,
)


REQUIRED_TABLES = {
    "replication_connections",
    "replication_sources",
    "replication_destinations",
    "replication_jobs",
    "replication_job_tables",
    "replication_plans",
    "replication_runs",
    "replication_table_runs",
    "replication_watermarks",
    "replication_events",
    "replication_errors",
    "connector_health_checks",
    "snowflake_permission_checks",
}


def test_replication_models_are_registered():
    assert REQUIRED_TABLES.issubset(set(Base.metadata.tables.keys()))


def test_replication_routes_are_registered():
    from main import app

    paths = {route.path for route in app.routes}
    required = {
        "/api/replication/overview",
        "/api/replication/connections",
        "/api/replication/connections/{connection_id}/test",
        "/api/replication/sources",
        "/api/replication/sources/discover",
        "/api/replication/jobs",
        "/api/replication/jobs/{job_id}",
        "/api/replication/jobs/{job_id}/start",
        "/api/replication/jobs/{job_id}/pause",
        "/api/replication/jobs/{job_id}/resume",
        "/api/replication/jobs/{job_id}/cancel",
        "/api/replication/jobs/{job_id}/retry",
        "/api/replication/jobs/{job_id}/tables",
        "/api/replication/jobs/{job_id}/plan",
        "/api/replication/runs",
        "/api/replication/runs/{run_id}",
        "/api/replication/runs/{run_id}/events",
        "/api/replication/runs/{run_id}/tables",
        "/api/replication/snowflake/readiness",
        "/api/replication/snowflake/check-permissions",
    }
    assert required.issubset(paths)


class FakeScalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return FakeScalars(self.rows)


class FakeReplicationSession:
    def __init__(self):
        self.job = ReplicationJob(
            id="job-1",
            name="CRM replication",
            source_connection_id="conn-src",
            destination_connection_id="conn-dst",
            sync_mode="incremental",
            status="READY",
            latest_error="",
        )
        self.connection = ReplicationConnection(
            id="conn-src",
            name="Missing credentials source",
            connector_type="postgres",
            role="source",
            config={},
            credentials={},
            status="NOT_CONFIGURED",
        )
        self.source = None
        self.tables = [
            ReplicationJobTable(
                id="table-1",
                job_id="job-1",
                schema_name="public",
                table_name="customers",
                selected=True,
                sync_mode="incremental",
                columns=[],
                primary_key_columns=[],
                status="NOT_STARTED",
            )
        ]
        self.runs = []
        self.table_runs = []
        self.plans = []
        self.events = []
        self.health = []
        self.commits = 0

    async def get(self, model, row_id):
        if model is ReplicationJob and row_id == self.job.id:
            return self.job
        if model is ReplicationConnection and row_id == self.connection.id:
            return self.connection
        if model is ReplicationRun:
            return next((r for r in self.runs if r.id == row_id), None)
        return None

    async def scalar(self, query):
        return len(self.runs)

    async def execute(self, query):
        entity = None
        if getattr(query, "column_descriptions", None):
            entity = query.column_descriptions[0].get("entity")
        if entity is ReplicationJobTable:
            return FakeResult(self.tables)
        if entity is ReplicationRun:
            return FakeResult([r for r in self.runs if r.status in {"QUEUED", "PLANNED"}])
        if entity is ReplicationSource:
            return FakeResult([self.source] if self.source else [])
        return FakeResult([])

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = gen_uuid()
        if isinstance(row, ReplicationRun):
            self.runs.append(row)
        elif isinstance(row, ReplicationTableRun):
            self.table_runs.append(row)
        elif isinstance(row, ReplicationPlan):
            self.plans.append(row)
        elif isinstance(row, ReplicationJobTable):
            self.tables.append(row)
        elif isinstance(row, ReplicationEvent):
            self.events.append(row)
        elif isinstance(row, ReplicationSource):
            self.source = row
        elif isinstance(row, ConnectorHealthCheck):
            self.health.append(row)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, row):
        return None


def test_job_lifecycle_creates_planned_run_without_execution():
    db = FakeReplicationSession()
    user = SimpleNamespace(id="user-1")

    async def scenario():
        run = await start_job("job-1", db=db, _=user)
        assert run["status"] == "QUEUED"
        assert run["planned_tables"] == 1
        assert db.job.status == "QUEUED"
        assert db.table_runs[0].status == "PLANNED"
        assert db.tables[0].status == "PLANNED"

        paused = await pause_job("job-1", user, db)
        assert paused["status"] == "PAUSED"

        resumed = await resume_job("job-1", user, db)
        assert resumed["status"] == "READY"

        cancelled = await cancel_job("job-1", user, db)
        assert cancelled["status"] == "CANCELLED"
        assert db.runs[0].status == "CANCELLED"

    asyncio.run(scenario())


def test_source_discovery_missing_credentials_returns_not_configured():
    db = FakeReplicationSession()
    user = SimpleNamespace(id="user-1")

    async def scenario():
        return await discover_source(
            SourceDiscoverRequest(connection_id="conn-src", schema_limit=2, table_limit=5),
            user,
            db,
        )

    result = asyncio.run(scenario())

    assert result["discovery_status"] == "NOT_CONFIGURED"
    assert "Credentials are missing" in result["discovery_reason"]
    assert result["schemas"] == []


def test_unsupported_connector_health_returns_warning():
    result = _test_sync("unknown_connector", {})
    assert result["status"] == "WARNING"
    assert "not implemented" in result["message"]


def test_update_job_tables_replaces_selection_without_deleting_history():
    db = FakeReplicationSession()
    user = SimpleNamespace(id="user-1")

    async def scenario():
        rows = await update_job_tables(
            "job-1",
            JobTablesUpdate(
                tables=[
                    ReplicationJobTablePayload(
                        schema_name="public",
                        table_name="orders",
                        target_schema="raw",
                        target_table="orders",
                        selected=True,
                        sync_mode="incremental",
                        watermark_column="updated_at",
                    )
                ]
            ),
            user,
            db,
        )
        return rows

    rows = asyncio.run(scenario())
    old_table = next(t for t in db.tables if t.table_name == "customers")
    new_table = next(t for t in db.tables if t.table_name == "orders")
    assert old_table.selected is False
    assert new_table.selected is True
    assert any(row["table_name"] == "orders" for row in rows)


def test_start_job_without_selected_tables_is_rejected():
    db = FakeReplicationSession()
    db.tables = []
    user = SimpleNamespace(id="user-1")

    async def scenario():
        return await start_job("job-1", db=db, _=user)

    with pytest.raises(Exception) as exc:
        asyncio.run(scenario())
    assert "no selected tables" in str(exc.value).lower()
