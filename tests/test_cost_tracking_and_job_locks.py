import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")

from core.database import AsyncSessionLocal, engine, init_db  # noqa: E402
from models import (  # noqa: E402
    Connection,
    ConnectionRole,
    ConnectionType,
    DestinationMode,
    Job,
    JobTask,
    JobRunLease,
    LoadStrategy,
    MigrationChunkManifest,
    MigrationRun,
)
from services.job_run_locks import acquire_job_run_lease, release_job_run_lease  # noqa: E402
from services.real_migration_engine import ChunkResult, RealMigrationEngine, SnowflakeTargetAdapter  # noqa: E402


class FakeCursor:
    def __init__(self, calls):
        self.calls = calls
        self.sfqid = "QID_TEST"

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if not sql.startswith("ALTER SESSION"):
            self.sfqid = f"QID_{len(self.calls)}"

    def fetchall(self):
        return [(1,)]

    def close(self):
        pass


class FakeSnowflakeConnection:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return FakeCursor(self.calls)


def _fake_adapter():
    adapter = object.__new__(SnowflakeTargetAdapter)
    adapter.conn = FakeSnowflakeConnection()
    adapter.job = SimpleNamespace(id="job-123", sf_warehouse="COMPUTE_WH")
    adapter.cfg = {"warehouse": "COMPUTE_WH"}
    adapter.run_id = "run-123"
    adapter.task_id = "task-123"
    adapter.table_name = "CUSTOMERS"
    adapter.phase = "copy"
    adapter._query_events = []
    adapter._stage_tables_to_drop = []
    return adapter


def test_snowflake_execute_sets_json_query_tag_and_captures_query_id():
    adapter = _fake_adapter()

    rows, qid = adapter.execute("SELECT 1", phase="copy")

    assert rows == [(1,)]
    assert qid == "QID_2"
    assert adapter.conn.calls[0][0].startswith("ALTER SESSION SET QUERY_TAG = ")
    tag_sql = adapter.conn.calls[0][0]
    tag = json.loads(tag_sql.split("QUERY_TAG = ", 1)[1].strip("'"))
    assert tag == {
        "app": "UMA",
        "job_id": "job-123",
        "run_id": "run-123",
        "task_id": "task-123",
        "table_name": "CUSTOMERS",
        "phase": "copy",
    }
    events = adapter.pop_query_events()
    assert events[0]["query_id"] == "QID_2"
    assert events[0]["phase"] == "copy"
    assert events[0]["warehouse_name"] == "COMPUTE_WH"


def test_cost_estimate_uses_safety_factor_and_pending_actual_inputs():
    estimate = RealMigrationEngine.estimate_table_cost(
        estimated_rows=100_000,
        estimated_source_bytes=50_000_000,
        load_strategy="upsert",
        warehouse="MEDIUM",
        validation_strategy="row_count",
        credit_rate=3.0,
    )

    assert estimate["estimated_compressed_bytes"] == 17_500_000
    assert estimate["estimated_credits"] > 0
    assert estimate["estimated_cost"] == pytest.approx(estimate["estimated_credits"] * 3.0)
    assert estimate["confidence_level"] == "medium"
    assert estimate["assumptions"]["safety_factor"] == pytest.approx(1.7)


@pytest.mark.asyncio
async def test_job_run_lease_blocks_concurrent_execution_and_recovers_stale_lock():
    await init_db()
    suffix = uuid.uuid4().hex[:8]
    source_id = target_id = job_id = None
    async with AsyncSessionLocal() as db:
        source = Connection(
            name=f"lease-src-{suffix}",
            type=ConnectionType.postgres,
            connection_role=ConnectionRole.source,
            config={"host": "localhost"},
            credentials={},
        )
        target = Connection(
            name=f"lease-target-{suffix}",
            type=ConnectionType.snowflake,
            connection_role=ConnectionRole.target,
            config={"account": "placeholder"},
            credentials={},
        )
        db.add_all([source, target])
        await db.flush()
        job = Job(
            name=f"lease-job-{suffix}",
            source_connection_id=source.id,
            dest_connection_id=target.id,
            destination_mode=DestinationMode.internal,
            load_strategy=LoadStrategy.full_load,
        )
        db.add(job)
        await db.commit()
        source_id, target_id, job_id = source.id, target.id, job.id

    first = await acquire_job_run_lease(job_id, "holder-a")
    assert first is not None
    second = await acquire_job_run_lease(job_id, "holder-b")
    assert second is None

    async with AsyncSessionLocal() as db:
        lease = (
            await db.execute(select(JobRunLease).where(JobRunLease.job_id == job_id))
        ).scalar_one()
        lease.expires_at = datetime.utcnow() - timedelta(seconds=1)
        await db.commit()

    recovered = await acquire_job_run_lease(job_id, "holder-b")
    assert recovered is not None
    assert recovered.holder_id == "holder-b"

    await release_job_run_lease(job_id, "holder-b")
    async with AsyncSessionLocal() as db:
        await db.execute(delete(JobRunLease).where(JobRunLease.job_id == job_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Connection).where(Connection.id.in_([source_id, target_id])))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_chunk_manifest_records_and_transitions_chunk_state(tmp_path):
    await init_db()
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        source = Connection(
            name=f"manifest-src-{suffix}",
            type=ConnectionType.postgres,
            connection_role=ConnectionRole.source,
            config={"host": "localhost"},
            credentials={},
        )
        target = Connection(
            name=f"manifest-target-{suffix}",
            type=ConnectionType.snowflake,
            connection_role=ConnectionRole.target,
            config={"account": "placeholder"},
            credentials={},
        )
        db.add_all([source, target])
        await db.flush()
        job = Job(
            name=f"manifest-job-{suffix}",
            source_connection_id=source.id,
            dest_connection_id=target.id,
            destination_mode=DestinationMode.internal,
            load_strategy=LoadStrategy.full_load,
        )
        db.add(job)
        await db.flush()
        task = JobTask(
            job_id=job.id,
            source_dataset="public",
            source_table="customers",
            target_schema="PUBLIC",
            target_table="CUSTOMERS",
            config={"primary_key_columns": ["id"], "watermark_column": "updated_at"},
        )
        run = MigrationRun(job_id=job.id, status="RUNNING", mode="full_load", attempt_number=1)
        db.add_all([task, run])
        await db.commit()

        file_path = tmp_path / "chunk.parquet"
        file_path.write_bytes(b"not-used")
        chunk = ChunkResult(
            file_path=file_path,
            rows=3,
            bytes=128,
            batch_index=0,
            last_watermark=datetime(2026, 1, 1, 12, 0, 0),
            last_primary_key=3,
        )
        migration_engine = RealMigrationEngine(job.id, lease_holder="test-holder")
        await migration_engine._record_chunk_manifest(
            db, job, run, task, "public.customers", [chunk], None, "_UMA_STAGE_CUSTOMERS"
        )
        manifest = (
            await db.execute(
                select(MigrationChunkManifest).where(MigrationChunkManifest.run_id == run.id)
            )
        ).scalar_one()
        assert manifest.state == "extracted"
        assert manifest.row_count == 3
        assert manifest.primary_key_end == "3"

        await migration_engine._mark_chunk_manifest(db, run.id, task.id, "validated")
        await db.refresh(manifest)
        assert manifest.state == "validated"

        await db.execute(delete(MigrationChunkManifest).where(MigrationChunkManifest.run_id == run.id))
        await db.execute(delete(MigrationRun).where(MigrationRun.id == run.id))
        await db.execute(delete(JobTask).where(JobTask.id == task.id))
        await db.execute(delete(Job).where(Job.id == job.id))
        await db.execute(delete(Connection).where(Connection.id.in_([source.id, target.id])))
        await db.commit()
    await engine.dispose()
