from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Connection,
    ConnectionRole,
    ConnectionType,
    Job,
    JobLog,
    JobStatus,
    JobTask,
    LoadStrategy,
    DestinationMode,
    LogLevel,
    SyncProfile,
    SyncRun,
    TaskStatus,
    User,
    ValidationRule,
)

DEMO_PREFIX = "Demo · "


async def demo_summary(db: AsyncSession) -> Dict[str, Any]:
    total_connections = await db.scalar(select(func.count(Connection.id))) or 0
    total_jobs = await db.scalar(select(func.count(Job.id))) or 0
    total_rules = await db.scalar(select(func.count(ValidationRule.id))) or 0
    total_profiles = await db.scalar(select(func.count(SyncProfile.id))) or 0
    total_runs = await db.scalar(select(func.count(SyncRun.id))) or 0
    total_tasks = await db.scalar(select(func.count(JobTask.id))) or 0
    seeded = bool(await db.scalar(select(func.count(Connection.id)).where(Connection.name.like(f"{DEMO_PREFIX}%"))))
    return {
        "seeded": seeded,
        "counts": {
            "connections": total_connections,
            "jobs": total_jobs,
            "tasks": total_tasks,
            "validation_rules": total_rules,
            "sync_profiles": total_profiles,
            "sync_runs": total_runs,
        },
    }


async def bootstrap_demo_workspace(db: AsyncSession, user: User | None = None) -> Dict[str, Any]:
    existing = await demo_summary(db)
    if existing["seeded"]:
        return {**existing, "created": False, "message": "Demo workspace already exists."}

    now = datetime.utcnow()
    created_by = getattr(user, "id", None)

    connections = [
        Connection(
            name=f"{DEMO_PREFIX}BigQuery Finance",
            type=ConnectionType.bigquery,
            connection_role=ConnectionRole.source,
            description="Sample source system for dashboard/demo flows",
            credentials={},
            config={"project_id": "demo-finance-prod"},
            health="healthy",
            last_tested=now - timedelta(minutes=12),
            created_by_id=created_by,
        ),
        Connection(
            name=f"{DEMO_PREFIX}Salesforce CRM",
            type=ConnectionType.salesforce,
            connection_role=ConnectionRole.source,
            description="Sample SaaS source for object-based migrations",
            credentials={},
            config={"instance_url": "https://demo.my.salesforce.com"},
            health="warn",
            last_tested=now - timedelta(hours=2),
            created_by_id=created_by,
        ),
        Connection(
            name=f"{DEMO_PREFIX}Snowflake Analytics",
            type=ConnectionType.snowflake,
            connection_role=ConnectionRole.target,
            description="Sample Snowflake destination",
            credentials={},
            config={
                "account": "demo-org.analytics",
                "warehouse": "COMPUTE_WH",
                "database": "ANALYTICS_DB",
                "schema": "RAW",
                "role": "SYSADMIN",
            },
            health="healthy",
            last_tested=now - timedelta(minutes=4),
            created_by_id=created_by,
        ),
        Connection(
            name=f"{DEMO_PREFIX}S3 Landing Zone",
            type=ConnectionType.s3,
            connection_role=ConnectionRole.both,
            description="Sample external stage / landing bucket",
            credentials={},
            config={"bucket": "uma-demo-landing", "region": "us-east-1", "prefix": "exports/"},
            health="healthy",
            last_tested=now - timedelta(minutes=18),
            created_by_id=created_by,
        ),
    ]
    db.add_all(connections)
    await db.flush()

    bq_conn, sf_conn = connections[0], connections[2]
    sfcrm_conn = connections[1]

    jobs = [
        Job(
            name=f"{DEMO_PREFIX}Finance Mart → Snowflake",
            source_connection_id=bq_conn.id,
            dest_connection_id=sf_conn.id,
            created_by_id=created_by,
            sf_warehouse="COMPUTE_WH",
            sf_database="ANALYTICS_DB",
            sf_schema="FINANCE",
            sf_role="SYSADMIN",
            destination_mode=DestinationMode.internal,
            load_strategy=LoadStrategy.incremental,
            file_format="parquet",
            staging_area="s3",
            schedule_cron="0 2 * * *",
            status=JobStatus.succeeded,
            phase="LOAD_COMPLETE",
            started_at=now - timedelta(hours=3, minutes=20),
            ended_at=now - timedelta(hours=3, minutes=6),
            total_rows_exported=18_450_120,
            total_bytes=82_400_000_000,
            total_files=244,
            export_duration_s=215,
            stage_duration_s=126,
            load_duration_s=487,
        ),
        Job(
            name=f"{DEMO_PREFIX}Salesforce Accounts Incremental",
            source_connection_id=sfcrm_conn.id,
            dest_connection_id=sf_conn.id,
            created_by_id=created_by,
            sf_warehouse="COMPUTE_WH",
            sf_database="ANALYTICS_DB",
            sf_schema="CRM",
            sf_role="SYSADMIN",
            destination_mode=DestinationMode.internal,
            load_strategy=LoadStrategy.upsert,
            file_format="parquet",
            staging_area="s3",
            schedule_cron="0 * * * *",
            status=JobStatus.partially_succeeded,
            phase="VALIDATION_WARNING",
            started_at=now - timedelta(minutes=58),
            ended_at=now - timedelta(minutes=46),
            total_rows_exported=1_205_441,
            total_bytes=6_750_000_000,
            total_files=38,
            export_duration_s=96,
            stage_duration_s=44,
            load_duration_s=181,
        ),
        Job(
            name=f"{DEMO_PREFIX}Customer 360 Backfill",
            source_connection_id=bq_conn.id,
            dest_connection_id=sf_conn.id,
            created_by_id=created_by,
            sf_warehouse="XL_WH",
            sf_database="ANALYTICS_DB",
            sf_schema="CUSTOMER_360",
            sf_role="SYSADMIN",
            destination_mode=DestinationMode.internal,
            load_strategy=LoadStrategy.full_load,
            file_format="parquet",
            staging_area="s3",
            schedule_cron="30 1 * * 0",
            status=JobStatus.running,
            phase="COPY_INTO",
            started_at=now - timedelta(minutes=14),
            ended_at=None,
            total_rows_exported=92_114_222,
            total_bytes=145_000_000_000,
            total_files=712,
            export_duration_s=601,
            stage_duration_s=322,
            load_duration_s=None,
        ),
    ]
    db.add_all(jobs)
    await db.flush()

    tasks = [
        JobTask(job_id=jobs[0].id, source_dataset="finance_core", source_table="gl_entries", target_schema="FINANCE", target_table="gl_entries", status=TaskStatus.succeeded, long_text_columns=0, rows_exported=12_100_000, bytes_exported=41_200_000_000, files_exported=122, started_at=jobs[0].started_at, ended_at=jobs[0].ended_at),
        JobTask(job_id=jobs[0].id, source_dataset="finance_core", source_table="ap_invoices", target_schema="FINANCE", target_table="ap_invoices", status=TaskStatus.succeeded, long_text_columns=1, rows_exported=3_210_551, bytes_exported=21_000_000_000, files_exported=67, started_at=jobs[0].started_at, ended_at=jobs[0].ended_at),
        JobTask(job_id=jobs[0].id, source_dataset="finance_core", source_table="ar_receipts", target_schema="FINANCE", target_table="ar_receipts", status=TaskStatus.succeeded, long_text_columns=0, rows_exported=3_139_569, bytes_exported=20_200_000_000, files_exported=55, started_at=jobs[0].started_at, ended_at=jobs[0].ended_at),
        JobTask(job_id=jobs[1].id, source_dataset="salesforce", source_table="Account", target_schema="CRM", target_table="account", status=TaskStatus.succeeded, long_text_columns=0, rows_exported=402_112, bytes_exported=1_550_000_000, files_exported=11, started_at=jobs[1].started_at, ended_at=jobs[1].ended_at),
        JobTask(job_id=jobs[1].id, source_dataset="salesforce", source_table="Opportunity", target_schema="CRM", target_table="opportunity", status=TaskStatus.failed, long_text_columns=2, rows_exported=231_901, bytes_exported=950_000_000, files_exported=7, error_message="2 columns exceeded target VARCHAR length policy; manual review required.", started_at=jobs[1].started_at, ended_at=jobs[1].ended_at),
        JobTask(job_id=jobs[1].id, source_dataset="salesforce", source_table="CampaignMember", target_schema="CRM", target_table="campaign_member", status=TaskStatus.succeeded, long_text_columns=0, rows_exported=571_428, bytes_exported=4_250_000_000, files_exported=20, started_at=jobs[1].started_at, ended_at=jobs[1].ended_at),
        JobTask(job_id=jobs[2].id, source_dataset="customer_360", source_table="guest_profile", target_schema="CUSTOMER_360", target_table="guest_profile", status=TaskStatus.running, long_text_columns=3, rows_exported=35_112_004, bytes_exported=58_000_000_000, files_exported=289, started_at=jobs[2].started_at, ended_at=None),
        JobTask(job_id=jobs[2].id, source_dataset="customer_360", source_table="stay_history", target_schema="CUSTOMER_360", target_table="stay_history", status=TaskStatus.pending, long_text_columns=0, rows_exported=0, bytes_exported=0, files_exported=0),
        JobTask(job_id=jobs[2].id, source_dataset="customer_360", source_table="guest_feedback", target_schema="CUSTOMER_360", target_table="guest_feedback", status=TaskStatus.pending, long_text_columns=4, rows_exported=0, bytes_exported=0, files_exported=0),
    ]
    db.add_all(tasks)

    logs = [
        JobLog(job_id=jobs[0].id, level=LogLevel.info, event="extract.started", message="Started finance extract from BigQuery.", created_at=jobs[0].started_at),
        JobLog(job_id=jobs[0].id, level=LogLevel.info, event="copy.complete", message="COPY INTO completed for 3 tables.", created_at=jobs[0].ended_at),
        JobLog(job_id=jobs[1].id, task_ref="salesforce.Opportunity", level=LogLevel.warn, event="schema.drift", message="Detected 2 long text columns requiring promotion.", detail="Description__c, Internal_Notes__c", created_at=jobs[1].ended_at - timedelta(minutes=4)),
        JobLog(job_id=jobs[1].id, task_ref="salesforce.Opportunity", level=LogLevel.error, event="validation.failed", message="Row parity exceeded 1% threshold for Opportunity.", detail="source=231,901 target=229,410", created_at=jobs[1].ended_at - timedelta(minutes=2)),
        JobLog(job_id=jobs[2].id, task_ref="customer_360.guest_profile", level=LogLevel.info, event="copy.running", message="Snowflake COPY INTO still in progress for guest_profile.", created_at=now - timedelta(minutes=6)),
    ]
    db.add_all(logs)

    rules = [
        ValidationRule(name=f"{DEMO_PREFIX}Finance row parity", rule_type="row_count", target_table="FINANCE.gl_entries", threshold_pct=0.1, status="SUCCEEDED", source_value="12100000", target_value="12100000", delta="+0 (0.00%)", last_run=now - timedelta(hours=3)),
        ValidationRule(name=f"{DEMO_PREFIX}Opportunity parity", rule_type="row_count", target_table="CRM.opportunity", threshold_pct=1.0, status="FAILED", source_value="231901", target_value="229410", delta="-2,491 (1.07%)", error_message="Delta 1.07% exceeds threshold 1.0%", last_run=now - timedelta(minutes=45)),
        ValidationRule(name=f"{DEMO_PREFIX}Customer freshness", rule_type="freshness", target_table="CUSTOMER_360.guest_profile", threshold_pct=0, status="RUNNING", source_value="—", target_value="—", delta="—", last_run=now - timedelta(minutes=10)),
        ValidationRule(name=f"{DEMO_PREFIX}Duplicate check", rule_type="duplicate", target_table="CRM.account", threshold_pct=0, status="SUCCEEDED", source_value="0", target_value="0", delta="0", last_run=now - timedelta(minutes=55)),
    ]
    db.add_all(rules)

    profiles = [
        SyncProfile(name=f"{DEMO_PREFIX}Hourly CRM Sync", source_connection_id=sfcrm_conn.id, dest_connection_id=sf_conn.id, mode="incremental", cadence="0 * * * *", schema_drift_policy="warn", destination_mode="internal", is_active=True, created_by=created_by),
        SyncProfile(name=f"{DEMO_PREFIX}Finance CDC", source_connection_id=bq_conn.id, dest_connection_id=sf_conn.id, mode="cdc", cadence="*/15 * * * *", schema_drift_policy="auto_add", destination_mode="internal", is_active=True, created_by=created_by),
    ]
    db.add_all(profiles)
    await db.flush()

    sync_runs = [
        SyncRun(profile_id=profiles[0].id, status="SUCCEEDED", rows_synced=12500, bytes_synced=52_428_800, started_at=now - timedelta(minutes=61), ended_at=now - timedelta(minutes=59)),
        SyncRun(profile_id=profiles[0].id, status="SUCCEEDED", rows_synced=13140, bytes_synced=61_440_000, started_at=now - timedelta(minutes=4), ended_at=now - timedelta(minutes=2)),
        SyncRun(profile_id=profiles[1].id, status="RUNNING", rows_synced=482200, bytes_synced=1_204_000_000, started_at=now - timedelta(minutes=9), ended_at=None),
    ]
    db.add_all(sync_runs)

    await db.commit()
    summary = await demo_summary(db)
    return {
        **summary,
        "created": True,
        "message": "Demo workspace created with sample connections, jobs, validation, drift signals, and managed sync runs.",
    }
