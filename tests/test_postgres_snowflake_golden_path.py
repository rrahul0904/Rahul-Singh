import os
import sys
import uuid
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")

from api.routes.validation import _check_row_count  # noqa: E402
from connectors.snowflake_connector import SnowflakeConnector  # noqa: E402
from core.config import settings  # noqa: E402
from core.database import AsyncSessionLocal  # noqa: E402
from core.security import get_cipher  # noqa: E402
from models import (  # noqa: E402
    Connection,
    ConnectionRole,
    ConnectionType,
    DestinationMode,
    Job,
    JobLog,
    JobTask,
    LoadStrategy,
    MigrationRun,
    MigrationState,
    MigrationTaskRun,
    ValidationRule,
)
from services.real_migration_engine import RealMigrationEngine  # noqa: E402


def _snowflake_config_or_skip():
    required = {
        "account": os.getenv("SNOWFLAKE_ACCOUNT", ""),
        "user": os.getenv("SNOWFLAKE_USER", ""),
        "password": os.getenv("SNOWFLAKE_PASSWORD", ""),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", ""),
        "database": os.getenv("SNOWFLAKE_DATABASE", ""),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        pytest.skip(f"Snowflake golden path skipped; missing env: {', '.join(missing)}")
    placeholders = {
        "your-org-accountname",
        "your_snowflake_username",
        "your_snowflake_password",
        "your_warehouse",
        "your_database",
        "change-me",
        "replace-me",
    }
    unsafe = [
        k
        for k, v in required.items()
        if v.strip().lower() in placeholders
        or "accountname" in v.strip().lower()
        or v.strip().lower().startswith("your_")
    ]
    if unsafe:
        pytest.skip(f"Snowflake golden path skipped; placeholder env: {', '.join(unsafe)}")
    return {
        **required,
        "schema": os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
        "role": os.getenv("SNOWFLAKE_ROLE", ""),
    }


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _row_value(row: dict, key: str):
    return row.get(key, row.get(key.upper()))


def _source_config_from_database_url() -> dict:
    url = make_url(settings.DATABASE_URL)
    return {
        "host": url.host or "localhost",
        "port": url.port or 5432,
        "database": url.database,
        "user": url.username,
        "password": url.password or "",
    }


def test_postgres_to_snowflake_full_incremental_soft_delete_and_validation():
    sf_config = _snowflake_config_or_skip()
    asyncio.run(_run_postgres_to_snowflake_full_incremental_soft_delete_and_validation(sf_config))


async def _run_postgres_to_snowflake_full_incremental_soft_delete_and_validation(sf_config):
    suffix = uuid.uuid4().hex[:8]
    source_schema = f"golden_src_{suffix}"
    source_table = "customers"
    target_schema = f"UMA_E2E_{suffix}".upper()
    target_table = f"CUSTOMERS_{suffix}".upper()
    base_ts = datetime(2026, 1, 1, 12, 0, 0)
    created_ids = {}

    async with AsyncSessionLocal() as db:
        await db.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{source_schema}"'))
        await db.execute(text(f'DROP TABLE IF EXISTS "{source_schema}"."{source_table}"'))
        await db.execute(text(f"""
            CREATE TABLE "{source_schema}"."{source_table}" (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))
        await db.execute(
            text(f"""
                INSERT INTO "{source_schema}"."{source_table}" (id, name, updated_at, is_deleted)
                VALUES
                  (1, 'Ada', :base_ts, FALSE),
                  (2, 'Grace', :base_ts, FALSE),
                  (3, 'Linus', :base_ts, FALSE)
            """),
            {"base_ts": base_ts},
        )

        cipher = get_cipher()
        source_conn = Connection(
            name=f"golden-postgres-{suffix}",
            type=ConnectionType.postgres,
            connection_role=ConnectionRole.source,
            config=_source_config_from_database_url(),
            credentials={},
        )
        target_conn = Connection(
            name=f"golden-snowflake-{suffix}",
            type=ConnectionType.snowflake,
            connection_role=ConnectionRole.target,
            config={
                "account": sf_config["account"],
                "warehouse": sf_config["warehouse"],
                "database": sf_config["database"],
                "schema": target_schema,
                "role": sf_config["role"],
                "user": sf_config["user"],
            },
            credentials=cipher.encrypt_dict({"password": sf_config["password"]}),
        )
        db.add_all([source_conn, target_conn])
        await db.flush()

        job = Job(
            name=f"golden-pg-sf-{suffix}",
            source_connection_id=source_conn.id,
            dest_connection_id=target_conn.id,
            sf_warehouse=sf_config["warehouse"],
            sf_database=sf_config["database"],
            sf_schema=target_schema,
            sf_role=sf_config["role"],
            destination_mode=DestinationMode.internal,
            load_strategy=LoadStrategy.full_load,
        )
        db.add(job)
        await db.flush()
        task = JobTask(
            job_id=job.id,
            source_dataset=source_schema,
            source_table=source_table,
            target_schema=target_schema,
            target_table=target_table,
            config={
                "primary_key_columns": ["id"],
                "watermark_column": "updated_at",
                "delete_flag_column": "is_deleted",
                "batch_size": 2,
            },
        )
        db.add(task)
        await db.commit()
        created_ids = {"job": job.id, "source": source_conn.id, "target": target_conn.id}

        try:
            full = await RealMigrationEngine(job.id).execute()
            assert full["success"] is True
            assert full["rows_loaded"] == 3

            with SnowflakeConnector({**sf_config, "schema": target_schema}) as sf:
                target_fqn = f'{_q(sf_config["database"])}.{_q(target_schema)}.{_q(target_table)}'
                rows = sf.run_query(
                    f'SELECT "id", "name", "_UMA_IS_DELETED" FROM {target_fqn} ORDER BY "id"'
                )
                assert [(int(_row_value(r, "id")), _row_value(r, "name"), bool(_row_value(r, "_UMA_IS_DELETED"))) for r in rows] == [
                    (1, "Ada", False),
                    (2, "Grace", False),
                    (3, "Linus", False),
                ]

            await db.execute(
                text(f"""
                    INSERT INTO "{source_schema}"."{source_table}" (id, name, updated_at, is_deleted)
                    VALUES (4, 'Katherine', :base_ts, FALSE)
                """),
                {"base_ts": base_ts},
            )
            await db.execute(
                text(f"""
                    UPDATE "{source_schema}"."{source_table}"
                    SET name = 'Grace Hopper', updated_at = :update_ts
                    WHERE id = 2
                """),
                {"update_ts": base_ts + timedelta(minutes=1)},
            )
            await db.execute(
                text(f"""
                    UPDATE "{source_schema}"."{source_table}"
                    SET is_deleted = TRUE, updated_at = :delete_ts
                    WHERE id = 1
                """),
                {"delete_ts": base_ts + timedelta(minutes=2)},
            )
            job.load_strategy = LoadStrategy.upsert
            await db.commit()

            inc = await RealMigrationEngine(job.id).execute()
            assert inc["success"] is True

            with SnowflakeConnector({**sf_config, "schema": target_schema}) as sf:
                target_fqn = f'{_q(sf_config["database"])}.{_q(target_schema)}.{_q(target_table)}'
                rows = sf.run_query(
                    f'SELECT "id", "name", "_UMA_IS_DELETED" FROM {target_fqn} ORDER BY "id"'
                )
                assert [(int(_row_value(r, "id")), _row_value(r, "name"), bool(_row_value(r, "_UMA_IS_DELETED"))) for r in rows] == [
                    (1, "Ada", True),
                    (2, "Grace Hopper", False),
                    (3, "Linus", False),
                    (4, "Katherine", False),
                ]
                counts = sf.run_query(
                    f'''
                    SELECT COUNT(*) AS total_rows,
                           COUNT(DISTINCT "id") AS distinct_ids,
                           SUM(IFF(COALESCE("_UMA_IS_DELETED", FALSE), 1, 0)) AS deleted_rows
                    FROM {target_fqn}
                    '''
                )[0]
                assert int(_row_value(counts, "total_rows")) == 4
                assert int(_row_value(counts, "distinct_ids")) == 4
                assert int(_row_value(counts, "deleted_rows")) == 1

                rerun = await RealMigrationEngine(job.id).execute()
                assert rerun["success"] is True
                counts_after = sf.run_query(
                    f'SELECT COUNT(*) AS total_rows, COUNT(DISTINCT "id") AS distinct_ids FROM {target_fqn}'
                )[0]
                assert int(_row_value(counts_after, "total_rows")) == 4
                assert int(_row_value(counts_after, "distinct_ids")) == 4

                mismatch = _check_row_count(
                    sf,
                    ValidationRule(
                        name="expected_wrong_count",
                        rule_type="row_count",
                        target_table=target_fqn,
                        source_query="SELECT 999 AS cnt",
                        target_query=f"SELECT COUNT(*) AS cnt FROM {target_fqn}",
                        threshold_pct=0.0,
                    ),
                    None,
                )
                assert mismatch["status"] == "FAILED"
        finally:
            await db.execute(text(f'DROP SCHEMA IF EXISTS "{source_schema}" CASCADE'))
            if created_ids:
                await db.execute(delete(ValidationRule).where(ValidationRule.job_id == created_ids["job"]))
                await db.execute(delete(MigrationTaskRun).where(MigrationTaskRun.job_id == created_ids["job"]))
                await db.execute(delete(MigrationRun).where(MigrationRun.job_id == created_ids["job"]))
                await db.execute(delete(MigrationState).where(MigrationState.job_id == created_ids["job"]))
                await db.execute(delete(JobLog).where(JobLog.job_id == created_ids["job"]))
                await db.execute(delete(JobTask).where(JobTask.job_id == created_ids["job"]))
                await db.execute(delete(Job).where(Job.id == created_ids["job"]))
                await db.execute(delete(Connection).where(Connection.id.in_([created_ids["source"], created_ids["target"]])))
            await db.commit()
            try:
                with SnowflakeConnector({**sf_config, "schema": target_schema}) as sf:
                    sf.run_query(f'DROP SCHEMA IF EXISTS {_q(sf_config["database"])}.{_q(target_schema)}')
            except Exception:
                pass
