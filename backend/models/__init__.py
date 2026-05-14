"""
UMA Platform — SQLAlchemy Models
"""

from sqlalchemy import (
    UniqueConstraint,
    Column, String, Integer, Float, Boolean, DateTime,
    Text, JSON, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from core.database import Base
from datetime import datetime
import uuid
import enum


def gen_uuid():
    return str(uuid.uuid4())


# ─── Enums ───────────────────────────────────────────────────

class ConnectionType(str, enum.Enum):
    bigquery    = "bigquery"
    redshift    = "redshift"
    snowflake   = "snowflake"
    sqlserver   = "sqlserver"
    synapse     = "synapse"
    teradata    = "teradata"
    oracle      = "oracle"
    postgres    = "postgres"
    mysql       = "mysql"
    db2         = "db2"
    saphana     = "saphana"
    # SaaS
    salesforce  = "salesforce"
    zendesk     = "zendesk"
    hubspot     = "hubspot"
    stripe      = "stripe"
    jira        = "jira"
    netsuite    = "netsuite"
    workday     = "workday"
    servicenow  = "servicenow"
    marketo     = "marketo"
    shopify     = "shopify"
    ga4         = "ga4"
    rest        = "rest"
    # Storage
    s3          = "s3"
    azureblob   = "azureblob"
    adls        = "adls"
    gcs         = "gcs"
    flatfile    = "flatfile"
    sftp        = "sftp"
    # Streaming
    kafka       = "kafka"
    kinesis     = "kinesis"
    pubsub      = "pubsub"
    eventhubs   = "eventhubs"


class ConnectionRole(str, enum.Enum):
    source = "source"
    target = "target"
    both   = "both"


class UserRole(str, enum.Enum):
    admin     = "admin"       # full access, manage users
    editor    = "editor"      # create/edit jobs, connections
    operator  = "operator"    # run jobs, view logs
    viewer    = "viewer"      # read-only


class JobStatus(str, enum.Enum):
    pending              = "PENDING"
    running              = "RUNNING"
    succeeded            = "SUCCEEDED"
    failed               = "FAILED"
    partially_succeeded  = "PARTIALLY_SUCCEEDED"
    cancelled            = "CANCELLED"


class TaskStatus(str, enum.Enum):
    pending   = "PENDING"
    running   = "RUNNING"
    succeeded = "SUCCEEDED"
    failed    = "FAILED"
    skipped   = "SKIPPED"


class LoadStrategy(str, enum.Enum):
    full_load    = "full_load"
    incremental  = "incremental"
    cdc          = "cdc"
    upsert       = "upsert"


class DestinationMode(str, enum.Enum):
    internal       = "internal"
    external_stage = "external_stage"
    external_table = "external_table"
    iceberg        = "iceberg"


class LogLevel(str, enum.Enum):
    info  = "INFO"
    warn  = "WARN"
    error = "ERROR"
    debug = "DEBUG"


# ─── Connection ───────────────────────────────────────────────

class Connection(Base):
    __tablename__ = "connections"

    id             = Column(String, primary_key=True, default=gen_uuid)
    project_id     = Column(String, ForeignKey("projects.id"), nullable=True, index=True)
    environment_id = Column(String, ForeignKey("environments.id"), nullable=True)
    name           = Column(String(255), nullable=False)
    type           = Column(SAEnum(ConnectionType), nullable=False)
    connection_role= Column(SAEnum(ConnectionRole), default=ConnectionRole.both, nullable=False)
    description    = Column(Text, default="")
    # Encrypted credentials stored as JSON — never returned raw
    credentials    = Column(JSON, nullable=False, default={})
    # Non-sensitive config (host, port, database, warehouse, etc.)
    config         = Column(JSON, nullable=False, default={})
    health         = Column(String(20), default="unknown")  # healthy / warn / failed / unknown
    last_tested    = Column(DateTime, nullable=True)
    created_by_id  = Column(String, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_jobs = relationship("Job", foreign_keys="Job.source_connection_id", back_populates="source_connection")
    dest_jobs   = relationship("Job", foreign_keys="Job.dest_connection_id",   back_populates="dest_connection")


# ─── Job ─────────────────────────────────────────────────────

class Job(Base):
    __tablename__ = "jobs"

    id                   = Column(String, primary_key=True, default=gen_uuid)
    project_id           = Column(String, ForeignKey("projects.id"), nullable=True, index=True)
    environment_id       = Column(String, ForeignKey("environments.id"), nullable=True)
    name                 = Column(String(255), nullable=False)
    source_connection_id = Column(String, ForeignKey("connections.id"), nullable=False)
    dest_connection_id   = Column(String, ForeignKey("connections.id"), nullable=False)
    created_by_id        = Column(String, ForeignKey("users.id"), nullable=True)

    # Snowflake destination config
    sf_warehouse         = Column(String(255), default="")
    sf_database          = Column(String(255), default="")
    sf_schema            = Column(String(255), default="")
    sf_role              = Column(String(255), default="")
    destination_mode     = Column(SAEnum(DestinationMode), default=DestinationMode.internal)

    # Execution config
    load_strategy        = Column(SAEnum(LoadStrategy), default=LoadStrategy.full_load)
    schedule_cron        = Column(String(100), nullable=True)
    next_scheduled_run   = Column(DateTime, nullable=True)
    file_format          = Column(String(20), default="parquet")
    staging_area         = Column(String(20), default="internal")  # s3 / azure / gcs / internal

    # Runtime state
    status               = Column(SAEnum(JobStatus), default=JobStatus.pending)
    phase                = Column(String(50), default="READY")
    started_at           = Column(DateTime, nullable=True)
    ended_at             = Column(DateTime, nullable=True)

    # Aggregated metrics
    total_rows_exported  = Column(Integer, default=0)
    total_bytes          = Column(Float, default=0.0)
    total_files          = Column(Integer, default=0)
    export_duration_s    = Column(Float, nullable=True)
    stage_duration_s     = Column(Float, nullable=True)
    load_duration_s      = Column(Float, nullable=True)

    created_at           = Column(DateTime, default=datetime.utcnow)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_connection    = relationship("Connection", foreign_keys=[source_connection_id], back_populates="source_jobs")
    dest_connection      = relationship("Connection", foreign_keys=[dest_connection_id],   back_populates="dest_jobs")
    tasks                = relationship("JobTask", back_populates="job", cascade="all, delete-orphan")
    logs                 = relationship("JobLog",  back_populates="job", cascade="all, delete-orphan")


# ─── JobTask (one per table/object) ──────────────────────────

class JobTask(Base):
    __tablename__ = "job_tasks"

    id                 = Column(String, primary_key=True, default=gen_uuid)
    job_id             = Column(String, ForeignKey("jobs.id"), nullable=False)
    source_dataset     = Column(String(255), nullable=False)
    source_table       = Column(String(255), nullable=False)
    target_schema      = Column(String(255), nullable=False)
    target_table       = Column(String(255), nullable=False)
    # Real-engine execution config, for example:
    # {"primary_key_columns":["id"], "watermark_column":"updated_at", "batch_size":50000,
    #  "delete_flag_column":"is_deleted"}
    config             = Column(JSON, nullable=False, default=dict)

    status             = Column(SAEnum(TaskStatus), default=TaskStatus.pending)
    long_text_columns  = Column(Integer, default=0)
    rows_exported      = Column(Integer, default=0)
    bytes_exported     = Column(Float, default=0.0)
    files_exported     = Column(Integer, default=0)
    copy_statement     = Column(Text, nullable=True)
    create_statement   = Column(Text, nullable=True)
    error_message      = Column(Text, nullable=True)
    started_at         = Column(DateTime, nullable=True)
    ended_at           = Column(DateTime, nullable=True)

    job                = relationship("Job", back_populates="tasks")


# ─── JobLog ──────────────────────────────────────────────────

class JobLog(Base):
    __tablename__ = "job_logs"

    id         = Column(String, primary_key=True, default=gen_uuid)
    job_id     = Column(String, ForeignKey("jobs.id"), nullable=False)
    task_ref   = Column(String(255), nullable=True)  # "dataset.table"
    level      = Column(SAEnum(LogLevel), default=LogLevel.info)
    event      = Column(String(100), nullable=False)
    message    = Column(Text, nullable=False)
    detail     = Column(Text, nullable=True)  # SQL statement, JSON payload, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    job        = relationship("Job", back_populates="logs")



# ─── Real Migration Engine State ─────────────────────────────

class MigrationRun(Base):
    """One physical execution attempt for a Job. Unlike Job, this is immutable history."""
    __tablename__ = "migration_runs"

    id              = Column(String, primary_key=True, default=gen_uuid)
    job_id          = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    status          = Column(String(30), default="PENDING", index=True)
    mode            = Column(String(50), default="full_load")
    attempt_number  = Column(Integer, default=1)
    rows_extracted  = Column(Integer, default=0)
    rows_loaded     = Column(Integer, default=0)
    rows_merged     = Column(Integer, default=0)
    rows_deleted    = Column(Integer, default=0)
    bytes_staged    = Column(Integer, default=0)
    started_at      = Column(DateTime, nullable=True)
    ended_at        = Column(DateTime, nullable=True)
    error_message   = Column(Text, default="")
    created_at      = Column(DateTime, default=datetime.utcnow)


class MigrationTaskRun(Base):
    """Execution history per table/task. Stores batch/chunk metrics."""
    __tablename__ = "migration_task_runs"

    id              = Column(String, primary_key=True, default=gen_uuid)
    run_id          = Column(String, ForeignKey("migration_runs.id"), nullable=False, index=True)
    job_id          = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    task_id         = Column(String, ForeignKey("job_tasks.id"), nullable=False, index=True)
    table_key       = Column(String(512), nullable=False, index=True)
    status          = Column(String(30), default="PENDING")
    extraction_sql  = Column(Text, nullable=True)
    staging_path    = Column(Text, nullable=True)
    target_table    = Column(String(512), nullable=True)
    batch_count     = Column(Integer, default=0)
    rows_extracted  = Column(Integer, default=0)
    rows_loaded     = Column(Integer, default=0)
    rows_merged     = Column(Integer, default=0)
    rows_deleted    = Column(Integer, default=0)
    bytes_staged    = Column(Integer, default=0)
    watermark_start = Column(String(255), nullable=True)
    watermark_end   = Column(String(255), nullable=True)
    started_at      = Column(DateTime, nullable=True)
    ended_at        = Column(DateTime, nullable=True)
    error_message   = Column(Text, default="")
    created_at      = Column(DateTime, default=datetime.utcnow)


class MigrationState(Base):
    """High-watermark/checkpoint state for incremental and CDC-style loads."""
    __tablename__ = "migration_states"
    __table_args__ = (UniqueConstraint("job_id", "task_id", name="uq_migration_state_job_task"),)

    id                     = Column(String, primary_key=True, default=gen_uuid)
    job_id                 = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    task_id                = Column(String, ForeignKey("job_tasks.id"), nullable=False, index=True)
    table_key              = Column(String(512), nullable=False, index=True)
    strategy               = Column(String(50), default="full_load")
    primary_key_columns    = Column(JSON, default=list)
    watermark_column       = Column(String(255), nullable=True)
    last_watermark_value   = Column(String(255), nullable=True)
    last_successful_run_id = Column(String, nullable=True)
    last_success_at        = Column(DateTime, nullable=True)
    state_json             = Column(JSON, default=dict)
    created_at             = Column(DateTime, default=datetime.utcnow)
    updated_at             = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobRunLease(Base):
    """Cross-worker lease preventing concurrent execution of the same job."""
    __tablename__ = "job_run_leases"

    id          = Column(String, primary_key=True, default=gen_uuid)
    job_id      = Column(String, ForeignKey("jobs.id"), nullable=False, unique=True, index=True)
    run_id      = Column(String, ForeignKey("migration_runs.id"), nullable=True, index=True)
    holder_id   = Column(String(255), nullable=False)
    acquired_at = Column(DateTime, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=False, index=True)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MigrationCostEstimate(Base):
    __tablename__ = "migration_cost_estimates"

    id                         = Column(String, primary_key=True, default=gen_uuid)
    job_id                     = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    run_id                     = Column(String, ForeignKey("migration_runs.id"), nullable=False, index=True)
    table_name                 = Column(String(512), nullable=True, index=True)
    estimated_rows             = Column(Integer, default=0)
    estimated_source_bytes     = Column(Integer, default=0)
    estimated_compressed_bytes = Column(Integer, default=0)
    estimated_runtime_seconds  = Column(Float, default=0.0)
    estimated_credits          = Column(Float, default=0.0)
    estimated_cost             = Column(Float, default=0.0)
    currency                   = Column(String(10), default="USD")
    confidence_level           = Column(String(20), default="low")
    assumptions                = Column(JSON, default=dict)
    created_at                 = Column(DateTime, default=datetime.utcnow)


class MigrationSnowflakeQuery(Base):
    __tablename__ = "migration_snowflake_queries"

    id                 = Column(String, primary_key=True, default=gen_uuid)
    job_id             = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    run_id             = Column(String, ForeignKey("migration_runs.id"), nullable=False, index=True)
    task_id            = Column(String, ForeignKey("job_tasks.id"), nullable=True, index=True)
    table_name         = Column(String(512), nullable=True, index=True)
    phase              = Column(String(50), nullable=False, index=True)
    query_id           = Column(String(255), nullable=False, index=True)
    query_tag          = Column(Text, nullable=False)
    warehouse_name     = Column(String(255), nullable=True)
    started_at         = Column(DateTime, nullable=True)
    ended_at           = Column(DateTime, nullable=True)
    execution_time_ms  = Column(Integer, nullable=True)
    bytes_scanned      = Column(Integer, nullable=True)
    rows_inserted      = Column(Integer, nullable=True)
    rows_updated       = Column(Integer, nullable=True)
    rows_deleted       = Column(Integer, nullable=True)
    credits_attributed = Column(Float, nullable=True)
    estimated_cost     = Column(Float, nullable=True)
    actual_cost        = Column(Float, nullable=True)
    status             = Column(String(30), default="SUCCEEDED")
    created_at         = Column(DateTime, default=datetime.utcnow)


class MigrationCostActual(Base):
    __tablename__ = "migration_cost_actuals"

    id                       = Column(String, primary_key=True, default=gen_uuid)
    job_id                   = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    run_id                   = Column(String, ForeignKey("migration_runs.id"), nullable=False, unique=True, index=True)
    warehouse_credits        = Column(Float, nullable=True)
    query_attributed_credits = Column(Float, nullable=True)
    cloud_services_credits   = Column(Float, nullable=True)
    cortex_credits           = Column(Float, nullable=True)
    snowpark_credits         = Column(Float, nullable=True)
    storage_cost             = Column(Float, nullable=True)
    total_estimated_cost     = Column(Float, nullable=True)
    total_actual_cost        = Column(Float, nullable=True)
    cost_variance_percent    = Column(Float, nullable=True)
    status                   = Column(String(30), default="pending")
    reconciled_at            = Column(DateTime, nullable=True)
    created_at               = Column(DateTime, default=datetime.utcnow)


class MigrationChunkManifest(Base):
    __tablename__ = "migration_chunk_manifest"
    __table_args__ = (
        UniqueConstraint("run_id", "task_id", "chunk_index", name="uq_chunk_manifest_run_task_index"),
    )

    id              = Column(String, primary_key=True, default=gen_uuid)
    run_id          = Column(String, ForeignKey("migration_runs.id"), nullable=False, index=True)
    job_id          = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    task_id         = Column(String, ForeignKey("job_tasks.id"), nullable=False, index=True)
    table_key       = Column(String(512), nullable=False, index=True)
    chunk_index     = Column(Integer, nullable=False)
    state           = Column(String(30), default="planned", index=True)
    file_path       = Column(Text, nullable=True)
    stage_table     = Column(String(512), nullable=True)
    row_count       = Column(Integer, default=0)
    bytes_staged    = Column(Integer, default=0)
    watermark_start = Column(String(255), nullable=True)
    watermark_end   = Column(String(255), nullable=True)
    primary_key_end = Column(String(255), nullable=True)
    error_message   = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MigrationValidationResult(Base):
    __tablename__ = "migration_validation_results"

    id             = Column(String, primary_key=True, default=gen_uuid)
    run_id         = Column(String, ForeignKey("migration_runs.id"), nullable=False, index=True)
    job_id         = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    task_id        = Column(String, ForeignKey("job_tasks.id"), nullable=True, index=True)
    table_key      = Column(String(512), nullable=True, index=True)
    rule_type      = Column(String(50), nullable=False, index=True)
    severity       = Column(String(20), default="error")
    status         = Column(String(20), default="PENDING", index=True)
    source_value   = Column(String(255), nullable=True)
    target_value   = Column(String(255), nullable=True)
    delta          = Column(String(100), nullable=True)
    message        = Column(Text, nullable=True)
    result_json    = Column(JSON, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow)


class MigrationRunEvent(Base):
    __tablename__ = "migration_run_events"

    id             = Column(String, primary_key=True, default=gen_uuid)
    run_id         = Column(String, ForeignKey("migration_runs.id"), nullable=True, index=True)
    job_id         = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    task_id        = Column(String, ForeignKey("job_tasks.id"), nullable=True, index=True)
    table_key      = Column(String(512), nullable=True, index=True)
    phase          = Column(String(50), nullable=True, index=True)
    event          = Column(String(100), nullable=False, index=True)
    level          = Column(String(20), default="INFO")
    message        = Column(Text, nullable=False)
    rows_extracted = Column(Integer, nullable=True)
    rows_loaded    = Column(Integer, nullable=True)
    rows_merged    = Column(Integer, nullable=True)
    rows_deleted   = Column(Integer, nullable=True)
    chunk_count    = Column(Integer, nullable=True)
    error_category = Column(String(100), nullable=True)
    event_json     = Column(JSON, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow)


class MigrationSchemaDriftResult(Base):
    __tablename__ = "migration_schema_drift_results"

    id              = Column(String, primary_key=True, default=gen_uuid)
    job_id          = Column(String, ForeignKey("jobs.id"), nullable=True, index=True)
    run_id          = Column(String, ForeignKey("migration_runs.id"), nullable=True, index=True)
    task_id         = Column(String, ForeignKey("job_tasks.id"), nullable=True, index=True)
    table_key       = Column(String(512), nullable=False, index=True)
    drift_type      = Column(String(50), nullable=False, index=True)
    column_name     = Column(String(255), nullable=True, index=True)
    source_type     = Column(String(255), nullable=True)
    target_type     = Column(String(255), nullable=True)
    source_nullable = Column(Boolean, nullable=True)
    target_nullable = Column(Boolean, nullable=True)
    severity        = Column(String(20), default="warning")
    action_taken    = Column(String(50), default="reported")
    result_json     = Column(JSON, default=dict)
    created_at      = Column(DateTime, default=datetime.utcnow)


# ─── Agentic Migration Orchestrator ───────────────────────────

class AgentRun(Base):
    """Stateful agentic migration workflow run. Stores orchestration state, not chat."""
    __tablename__ = "agent_runs"

    id                    = Column(String, primary_key=True, default=gen_uuid)
    project_id            = Column(String, ForeignKey("projects.id"), nullable=True, index=True)
    user_id               = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    run_type              = Column(String(80), default="migration_orchestration", index=True)
    status                = Column(String(40), default="PENDING", index=True)
    request_text          = Column(Text, default="")
    source_connection_id  = Column(String, ForeignKey("connections.id"), nullable=True, index=True)
    target_connection_id  = Column(String, ForeignKey("connections.id"), nullable=True, index=True)
    source_type           = Column(String(80), default="")
    target_type           = Column(String(80), default="snowflake")
    migration_type        = Column(String(80), default="full_load")
    schemas               = Column(JSON, default=list)
    state_json            = Column(JSON, default=dict)
    current_step          = Column(String(120), nullable=True)
    requires_approval     = Column(Boolean, default=False)
    approved              = Column(Boolean, default=False)
    error_message         = Column(Text, default="")
    started_at            = Column(DateTime, nullable=True)
    completed_at          = Column(DateTime, nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id             = Column(String, primary_key=True, default=gen_uuid)
    run_id         = Column(String, ForeignKey("agent_runs.id"), nullable=False, index=True)
    step_name      = Column(String(120), nullable=False, index=True)
    status         = Column(String(40), default="PENDING", index=True)
    sequence       = Column(Integer, default=0)
    input_json     = Column(JSON, default=dict)
    output_json    = Column(JSON, default=dict)
    error_message  = Column(Text, default="")
    started_at     = Column(DateTime, nullable=True)
    completed_at   = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id             = Column(String, primary_key=True, default=gen_uuid)
    run_id         = Column(String, ForeignKey("agent_runs.id"), nullable=False, index=True)
    step_id        = Column(String, ForeignKey("agent_steps.id"), nullable=True, index=True)
    tool_name      = Column(String(160), nullable=False, index=True)
    permission     = Column(String(40), default="READ_ONLY", index=True)
    input_json     = Column(JSON, default=dict)
    output_json    = Column(JSON, default=dict)
    status         = Column(String(40), default="SUCCEEDED", index=True)
    error_message  = Column(Text, default="")
    created_at     = Column(DateTime, default=datetime.utcnow)


class AgentApproval(Base):
    __tablename__ = "agent_approvals"

    id               = Column(String, primary_key=True, default=gen_uuid)
    run_id           = Column(String, ForeignKey("agent_runs.id"), nullable=False, index=True)
    step_id          = Column(String, ForeignKey("agent_steps.id"), nullable=True, index=True)
    approval_type    = Column(String(80), default="ddl_execution", index=True)
    requested_by     = Column(String, ForeignKey("users.id"), nullable=True)
    approved_by      = Column(String, ForeignKey("users.id"), nullable=True)
    status           = Column(String(40), default="PENDING", index=True)
    approval_payload = Column(JSON, default=dict)
    requested_at     = Column(DateTime, default=datetime.utcnow)
    approved_at      = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)


class DDLConversionResult(Base):
    __tablename__ = "ddl_conversion_results"

    id                      = Column(String, primary_key=True, default=gen_uuid)
    run_id                  = Column(String, ForeignKey("agent_runs.id"), nullable=False, index=True)
    source_object_name      = Column(String(512), nullable=False, index=True)
    source_object_type      = Column(String(80), default="table")
    source_dialect          = Column(String(80), default="")
    target_dialect          = Column(String(80), default="snowflake")
    original_ddl            = Column(Text, default="")
    converted_ddl           = Column(Text, default="")
    conversion_confidence   = Column(Float, default=0.0)
    unsupported_features    = Column(JSON, default=list)
    manual_review_required  = Column(Boolean, default=True)
    review_status           = Column(String(40), default="generated", index=True)
    execution_status        = Column(String(40), default="not_executed", index=True)
    created_at              = Column(DateTime, default=datetime.utcnow)

# ─── ValidationRule ──────────────────────────────────────────

class ValidationRule(Base):
    __tablename__ = "validation_rules"

    id              = Column(String, primary_key=True, default=gen_uuid)
    job_id          = Column(String, ForeignKey("jobs.id"), nullable=True)
    name            = Column(String(255), nullable=False)
    rule_type       = Column(String(50), nullable=False)  # row_count / schema / null / freshness / duplicate / checksum
    # Optional source-side context for reconciliation. When set, source_query
    # is auto-derived if the user didn't provide one.
    source_connection_id = Column(String, ForeignKey("connections.id"), nullable=True)
    source_dataset  = Column(String(255), nullable=True)
    source_table    = Column(String(255), nullable=True)
    primary_key_columns = Column(JSON, default=list, nullable=True)  # used by checksum
    source_query    = Column(Text, nullable=True)
    target_query    = Column(Text, nullable=True)
    target_table    = Column(String(255), nullable=False)
    threshold_pct   = Column(Float, default=0.0)

    # Last run results
    status          = Column(String(20), default="PENDING")
    source_value    = Column(String(255), nullable=True)
    target_value    = Column(String(255), nullable=True)
    delta           = Column(String(100), nullable=True)
    last_run        = Column(DateTime, nullable=True)
    error_message   = Column(Text, nullable=True)

    created_at      = Column(DateTime, default=datetime.utcnow)


# ─── User / Role (Control Plane) ─────────────────────────────

class User(Base):
    __tablename__ = "users"

    id            = Column(String, primary_key=True, default=gen_uuid)
    email         = Column(String(255), unique=True, nullable=False, index=True)
    name          = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)  # bcrypt
    role          = Column(SAEnum(UserRole), default=UserRole.viewer, nullable=False)
    is_active     = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    email_verified_at = Column(DateTime, nullable=True)
    last_login    = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Optional project scoping — if null, user has global access based on role
    default_project_id = Column(String, ForeignKey("projects.id"), nullable=True)
    memberships        = relationship("ProjectMember", back_populates="user", cascade="all, delete-orphan")


class EmailVerificationToken(Base):
    """One-time tokens for account email verification."""
    __tablename__ = "email_verification_tokens"

    id         = Column(String, primary_key=True, default=gen_uuid)
    user_id    = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiToken(Base):
    """Personal access tokens for programmatic access."""
    __tablename__ = "api_tokens"

    id          = Column(String, primary_key=True, default=gen_uuid)
    user_id     = Column(String, ForeignKey("users.id"), nullable=False)
    name        = Column(String(255), nullable=False)
    token_hash  = Column(String(255), nullable=False, index=True)  # sha256 of actual token
    prefix      = Column(String(12), nullable=False)               # first 8 chars for display
    expires_at  = Column(DateTime, nullable=True)
    last_used   = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


# ─── Project / Environment (Control Plane) ───────────────────

class Project(Base):
    __tablename__ = "projects"

    id          = Column(String, primary_key=True, default=gen_uuid)
    name        = Column(String(255), nullable=False)
    slug        = Column(String(100), unique=True, nullable=False)
    description = Column(Text, default="")
    owner_id    = Column(String, ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    environments = relationship("Environment", back_populates="project", cascade="all, delete-orphan")
    members      = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")


class Environment(Base):
    """dev / staging / prod per project, each with its own Snowflake target."""
    __tablename__ = "environments"

    id              = Column(String, primary_key=True, default=gen_uuid)
    project_id      = Column(String, ForeignKey("projects.id"), nullable=False)
    name            = Column(String(100), nullable=False)  # dev / staging / prod
    description     = Column(Text, default="")

    # Default Snowflake target for jobs in this env
    sf_warehouse    = Column(String(255), default="COMPUTE_WH")
    sf_database     = Column(String(255), default="ANALYTICS_DB_DEV")
    sf_schema       = Column(String(255), default="RAW")
    sf_role         = Column(String(255), default="SYSADMIN")

    # Default staging
    staging_area    = Column(String(20), default="s3")
    staging_bucket  = Column(String(255), default="")

    is_production   = Column(Boolean, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)

    project         = relationship("Project", back_populates="environments")


class ProjectMember(Base):
    """Maps users to projects with per-project roles."""
    __tablename__ = "project_members"

    id         = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    user_id    = Column(String, ForeignKey("users.id"),    nullable=False)
    role       = Column(SAEnum(UserRole), default=UserRole.viewer, nullable=False)
    added_at   = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="members")
    user    = relationship("User",    back_populates="memberships")


# ─── Scheduler Lease (Leader Election) ───────────────────────

class SchedulerLease(Base):
    """
    Leader-election primitive for multi-replica scheduler.
    Only the holder of the active lease actually triggers jobs.
    Lease expires after ~90s; replicas race to acquire it via SQL UPSERT.
    """
    __tablename__ = "scheduler_leases"

    lock_name   = Column(String(50), primary_key=True, default="scheduler")  # single-row table
    holder_id   = Column(String(100), nullable=False)  # hostname + pid
    acquired_at = Column(DateTime, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=False)


# ─── Platform Settings / Audit ───────────────────────────────

class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key         = Column(String(100), primary_key=True)
    value       = Column(JSON, nullable=False, default=dict)
    updated_by  = Column(String, ForeignKey("users.id"), nullable=True)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PlatformSettingAudit(Base):
    __tablename__ = "platform_settings_audit"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    key         = Column(String(100), nullable=False, index=True)
    old_value   = Column(JSON, nullable=True)
    new_value   = Column(JSON, nullable=True)
    changed_by  = Column(String, ForeignKey("users.id"), nullable=True)
    changed_at  = Column(DateTime, default=datetime.utcnow, index=True)


# ─── Migration Intelligence Artifact Pipeline ───────────────

class UploadedArtifact(Base):
    __tablename__ = "uploaded_artifacts"

    id                     = Column(String, primary_key=True, default=gen_uuid)
    file_name              = Column(String(255), nullable=False)
    file_type              = Column(String(40), nullable=False, index=True)
    mime_type              = Column(String(120), nullable=False, default="application/octet-stream")
    size_bytes             = Column(Integer, nullable=False, default=0)
    sha256_hash            = Column(String(64), nullable=False, index=True)
    storage_path           = Column(Text, nullable=False)
    uploaded_by            = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    created_at             = Column(DateTime, default=datetime.utcnow, index=True)
    extraction_status      = Column(String(40), nullable=False, default="UPLOADED", index=True)
    extracted_text_preview = Column(Text, nullable=True)
    classification         = Column(String(80), nullable=True, index=True)
    language_guess         = Column(String(80), nullable=True)
    source_system_guess    = Column(String(80), nullable=True)
    error_message          = Column(Text, nullable=True)


class ArtifactExtraction(Base):
    __tablename__ = "artifact_extractions"

    id                     = Column(String, primary_key=True, default=gen_uuid)
    artifact_id            = Column(String, ForeignKey("uploaded_artifacts.id"), nullable=False, index=True)
    extraction_status      = Column(String(40), nullable=False, default="UPLOADED", index=True)
    extracted_text         = Column(Text, nullable=True)
    extracted_text_preview = Column(Text, nullable=True)
    page_count             = Column(Integer, nullable=True)
    metadata_json          = Column(JSON, nullable=False, default=dict)
    error_message          = Column(Text, nullable=True)
    created_at             = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at             = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ArtifactChunk(Base):
    __tablename__ = "artifact_chunks"

    id            = Column(String, primary_key=True, default=gen_uuid)
    artifact_id    = Column(String, ForeignKey("uploaded_artifacts.id"), nullable=False, index=True)
    extraction_id  = Column(String, ForeignKey("artifact_extractions.id"), nullable=True, index=True)
    chunk_index    = Column(Integer, nullable=False, default=0)
    chunk_type     = Column(String(80), nullable=False, default="TEXT", index=True)
    heading        = Column(String(255), nullable=True)
    text           = Column(Text, nullable=False)
    statement_type = Column(String(80), nullable=True, index=True)
    object_name    = Column(String(255), nullable=True)
    line_start     = Column(Integer, nullable=True)
    line_end       = Column(Integer, nullable=True)
    metadata_json  = Column(JSON, nullable=False, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)


class MigrationIntelligenceRun(Base):
    __tablename__ = "migration_intelligence_runs"

    id                         = Column(String, primary_key=True, default=gen_uuid)
    selected_artifact_ids      = Column(JSON, nullable=False, default=list)
    source_connection_id       = Column(String, ForeignKey("connections.id"), nullable=True, index=True)
    target_connection_id       = Column(String, ForeignKey("connections.id"), nullable=True, index=True)
    status                     = Column(String(40), nullable=False, default="QUEUED", index=True)
    started_by                 = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    started_at                 = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at               = Column(DateTime, nullable=True)
    agent_mode                 = Column(String(80), nullable=False, default="deterministic_local")
    openai_called              = Column(Boolean, nullable=False, default=False)
    snowflake_cortex_called    = Column(Boolean, nullable=False, default=False)
    snowflake_sql_executed     = Column(Boolean, nullable=False, default=False)
    uploaded_sql_executed      = Column(Boolean, nullable=False, default=False)
    generated_code_executed    = Column(Boolean, nullable=False, default=False)
    ddl_executed               = Column(Boolean, nullable=False, default=False)
    data_moved                 = Column(Boolean, nullable=False, default=False)
    token_credit_note          = Column(Text, nullable=True)
    latest_error               = Column(Text, nullable=True)
    created_at                 = Column(DateTime, default=datetime.utcnow, index=True)


class MigrationIntelligenceRunStep(Base):
    __tablename__ = "migration_intelligence_run_steps"

    id            = Column(String, primary_key=True, default=gen_uuid)
    run_id         = Column(String, ForeignKey("migration_intelligence_runs.id"), nullable=False, index=True)
    step_name      = Column(String(120), nullable=False, index=True)
    sequence       = Column(Integer, nullable=False, default=0)
    status         = Column(String(40), nullable=False, default="PENDING", index=True)
    started_at     = Column(DateTime, nullable=True)
    completed_at   = Column(DateTime, nullable=True)
    details_json   = Column(JSON, nullable=False, default=dict)
    error_message  = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)


class MigrationIntelligenceFinding(Base):
    __tablename__ = "migration_intelligence_findings"

    id                  = Column(String, primary_key=True, default=gen_uuid)
    run_id               = Column(String, ForeignKey("migration_intelligence_runs.id"), nullable=False, index=True)
    severity             = Column(String(40), nullable=False, index=True)
    finding_type         = Column(String(80), nullable=False, index=True)
    title                = Column(String(255), nullable=False)
    description          = Column(Text, nullable=False)
    evidence             = Column(JSON, nullable=False, default=list)
    source_artifact_id   = Column(String, ForeignKey("uploaded_artifacts.id"), nullable=True, index=True)
    recommended_action   = Column(Text, nullable=True)
    status               = Column(String(40), nullable=False, default="OPEN", index=True)
    created_at           = Column(DateTime, default=datetime.utcnow, index=True)


class MigrationIntelligenceReport(Base):
    __tablename__ = "migration_intelligence_reports"

    id              = Column(String, primary_key=True, default=gen_uuid)
    run_id           = Column(String, ForeignKey("migration_intelligence_runs.id"), nullable=False, unique=True, index=True)
    title            = Column(String(255), nullable=False)
    report_json      = Column(JSON, nullable=False, default=dict)
    report_markdown  = Column(Text, nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── Migration Control Plane Foundation ──────────────────────

class ControlPlaneArtifact(Base):
    __tablename__ = "control_plane_artifacts"

    id                = Column(String, primary_key=True, default=gen_uuid)
    run_id            = Column(String, ForeignKey("control_plane_runs.id"), nullable=True, index=True)
    filename          = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_type         = Column(String(40), nullable=False, index=True)
    artifact_category = Column(String(80), nullable=False, index=True)
    storage_path      = Column(Text, nullable=False)
    mime_type         = Column(String(120), nullable=False, default="application/octet-stream")
    size_bytes        = Column(Integer, nullable=False, default=0)
    checksum_sha256   = Column(String(64), nullable=False, index=True)
    created_by        = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    created_at        = Column(DateTime, default=datetime.utcnow, index=True)
    metadata_json     = Column(JSON, nullable=False, default=dict)


class ControlPlaneRun(Base):
    __tablename__ = "control_plane_runs"

    id                    = Column(String, primary_key=True, default=gen_uuid)
    name                  = Column(String(255), nullable=False)
    workflow_type         = Column(String(80), nullable=False, index=True)
    source_type           = Column(String(80), default="")
    target_type           = Column(String(80), default="snowflake")
    source_dialect        = Column(String(80), default="")
    target_dialect        = Column(String(80), default="snowflake")
    source_connection_id  = Column(String, ForeignKey("connections.id"), nullable=True, index=True)
    target_connection_id  = Column(String, ForeignKey("connections.id"), nullable=True, index=True)
    safety_mode           = Column(String(40), nullable=False, default="READ_ONLY", index=True)
    status                = Column(String(40), nullable=False, default="DRAFT", index=True)
    current_phase         = Column(String(120), default="")
    created_by            = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    created_at            = Column(DateTime, default=datetime.utcnow, index=True)
    started_at            = Column(DateTime, nullable=True)
    completed_at          = Column(DateTime, nullable=True)
    error_message         = Column(Text, default="")
    summary_json          = Column(JSON, nullable=False, default=dict)
    metrics_json          = Column(JSON, nullable=False, default=dict)
    config_json           = Column(JSON, nullable=False, default=dict)
    approval_granted      = Column(Boolean, default=False, index=True)
    approved_by           = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at           = Column(DateTime, nullable=True)


class ControlPlaneJob(Base):
    __tablename__ = "control_plane_jobs"

    id              = Column(String, primary_key=True, default=gen_uuid)
    run_id          = Column(String, ForeignKey("control_plane_runs.id"), nullable=False, index=True)
    module          = Column(String(80), nullable=False, index=True)
    phase           = Column(String(120), nullable=False, index=True)
    status          = Column(String(40), nullable=False, default="PENDING", index=True)
    started_at      = Column(DateTime, nullable=True)
    completed_at    = Column(DateTime, nullable=True)
    logs_redacted   = Column(Text, default="")
    error_message   = Column(Text, default="")
    output_json     = Column(JSON, nullable=False, default=dict)
    created_at      = Column(DateTime, default=datetime.utcnow, index=True)


class SqlConversionMessage(Base):
    __tablename__ = "sql_conversion_messages"

    id              = Column(String, primary_key=True, default=gen_uuid)
    run_id          = Column(String, ForeignKey("control_plane_runs.id"), nullable=False, index=True)
    artifact_id     = Column(String, ForeignKey("control_plane_artifacts.id"), nullable=True, index=True)
    file_name       = Column(String(255), nullable=False)
    statement_index = Column(Integer, default=0, index=True)
    statement_type  = Column(String(80), default="UNKNOWN", index=True)
    severity        = Column(String(20), nullable=False, default="INFO", index=True)
    message         = Column(Text, nullable=False)
    source_dialect  = Column(String(80), default="")
    target_dialect  = Column(String(80), default="snowflake")
    line_start      = Column(Integer, nullable=True)
    line_end        = Column(Integer, nullable=True)
    recommendation  = Column(Text, default="")
    metadata_json   = Column(JSON, nullable=False, default=dict)
    created_at      = Column(DateTime, default=datetime.utcnow, index=True)


class HumanReviewItem(Base):
    __tablename__ = "human_review_items"

    id               = Column(String, primary_key=True, default=gen_uuid)
    run_id           = Column(String, ForeignKey("control_plane_runs.id"), nullable=False, index=True)
    item_type        = Column(String(80), nullable=False, index=True)
    severity         = Column(String(20), nullable=False, default="WARN", index=True)
    title            = Column(String(255), nullable=False)
    description      = Column(Text, nullable=False)
    recommendation   = Column(Text, default="")
    status           = Column(String(40), default="OPEN", index=True)
    reviewer_comment = Column(Text, nullable=True)
    metadata_json    = Column(JSON, nullable=False, default=dict)
    created_at       = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalyzerComponent(Base):
    __tablename__ = "analyzer_components"

    id             = Column(String, primary_key=True, default=gen_uuid)
    run_id         = Column(String, ForeignKey("control_plane_runs.id"), nullable=False, index=True)
    component_type = Column(String(80), nullable=False, index=True)
    name           = Column(String(255), nullable=False, index=True)
    source_file    = Column(String(255), nullable=False)
    metadata_json  = Column(JSON, nullable=False, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)


class AnalyzerDependency(Base):
    __tablename__ = "analyzer_dependencies"

    id               = Column(String, primary_key=True, default=gen_uuid)
    run_id           = Column(String, ForeignKey("control_plane_runs.id"), nullable=False, index=True)
    source_component = Column(String(255), nullable=False, index=True)
    target_component = Column(String(255), nullable=False, index=True)
    dependency_type  = Column(String(80), nullable=False, default="REFERENCES", index=True)
    metadata_json    = Column(JSON, nullable=False, default=dict)
    created_at       = Column(DateTime, default=datetime.utcnow, index=True)


class AdvisorScan(Base):
    __tablename__ = "advisor_scans"

    id                        = Column(String, primary_key=True, default=gen_uuid)
    run_id                    = Column(String, ForeignKey("control_plane_runs.id"), nullable=True, index=True)
    connection_id             = Column(String, ForeignKey("connections.id"), nullable=True, index=True)
    status                    = Column(String(40), default="PENDING", index=True)
    health_score              = Column(Integer, default=0)
    security_score            = Column(Integer, default=0)
    compute_score             = Column(Integer, default=0)
    storage_score             = Column(Integer, default=0)
    cost_score                = Column(Integer, default=0)
    operational_score         = Column(Integer, default=0)
    migration_readiness_score = Column(Integer, default=0)
    started_at                = Column(DateTime, nullable=True)
    completed_at              = Column(DateTime, nullable=True)
    error_message             = Column(Text, default="")
    config_json               = Column(JSON, nullable=False, default=dict)
    created_at                = Column(DateTime, default=datetime.utcnow, index=True)


class AdvisorCheckResult(Base):
    __tablename__ = "advisor_check_results"

    id                 = Column(String, primary_key=True, default=gen_uuid)
    scan_id            = Column(String, ForeignKey("advisor_scans.id"), nullable=False, index=True)
    check_name         = Column(String(160), nullable=False, index=True)
    category           = Column(String(80), nullable=False, index=True)
    severity           = Column(String(20), default="INFO", index=True)
    status             = Column(String(40), default="PLANNED", index=True)
    description        = Column(Text, nullable=False)
    result_count       = Column(Integer, default=0)
    result_sample_json = Column(JSON, nullable=False, default=list)
    recommendation     = Column(Text, default="")
    raw_sql_redacted   = Column(Text, default="")
    created_at         = Column(DateTime, default=datetime.utcnow, index=True)

# ─── Managed Syncs (Fivetran/Stitch-style foundation) ────────

class SyncProfile(Base):
    __tablename__ = "sync_profiles"

    id                  = Column(String, primary_key=True, default=gen_uuid)
    name                = Column(String(255), nullable=False)
    source_connection_id= Column(String, ForeignKey("connections.id"), nullable=False)
    dest_connection_id  = Column(String, ForeignKey("connections.id"), nullable=False)
    job_id              = Column(String, nullable=True, index=True)
    source_dataset      = Column(String(255), nullable=True)
    source_table        = Column(String(255), nullable=True)
    target_schema       = Column(String(255), nullable=True)
    target_table        = Column(String(255), nullable=True)
    task_config         = Column(JSON, nullable=False, default=dict)
    mode                = Column(String(50), default="incremental")  # full_refresh / incremental / cdc
    cadence             = Column(String(100), default="0 2 * * *")
    schema_drift_policy = Column(String(50), default="warn")         # warn / auto_add / block
    destination_mode    = Column(String(50), default="internal")
    is_active           = Column(Boolean, default=True)
    created_by          = Column(String, ForeignKey("users.id"), nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SyncRun(Base):
    __tablename__ = "sync_runs"

    id            = Column(String, primary_key=True, default=gen_uuid)
    profile_id    = Column(String, ForeignKey("sync_profiles.id"), nullable=False, index=True)
    status        = Column(String(30), default="PENDING")  # PENDING/RUNNING/SUCCEEDED/FAILED
    rows_synced   = Column(Integer, default=0)
    bytes_synced  = Column(Integer, default=0)
    started_at    = Column(DateTime, nullable=True)
    ended_at      = Column(DateTime, nullable=True)
    error_message = Column(Text, default="")
    created_at    = Column(DateTime, default=datetime.utcnow)


# ─── Data Replication Control Plane ───────────────────────────

class ReplicationConnection(Base):
    __tablename__ = "replication_connections"

    id              = Column(String, primary_key=True, default=gen_uuid)
    name            = Column(String(255), nullable=False)
    connector_type  = Column(String(80), nullable=False, index=True)
    role            = Column(String(30), default="both", index=True)  # source / destination / both
    description     = Column(Text, default="")
    connection_id   = Column(String, ForeignKey("connections.id"), nullable=True, index=True)
    config          = Column(JSON, nullable=False, default=dict)
    credentials     = Column(JSON, nullable=False, default=dict)
    status          = Column(String(40), default="NOT_CONFIGURED", index=True)
    latest_error    = Column(Text, default="")
    last_tested_at  = Column(DateTime, nullable=True)
    created_by_id   = Column(String, ForeignKey("users.id"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReplicationSource(Base):
    __tablename__ = "replication_sources"

    id             = Column(String, primary_key=True, default=gen_uuid)
    connection_id  = Column(String, ForeignKey("replication_connections.id"), nullable=False, index=True)
    connector_type = Column(String(80), nullable=False, index=True)
    name           = Column(String(255), nullable=False)
    discovery_status = Column(String(40), default="NOT_CHECKED", index=True)
    discovery_reason = Column(Text, default="")
    schemas        = Column(JSON, nullable=False, default=list)
    discovered_at  = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReplicationDestination(Base):
    __tablename__ = "replication_destinations"

    id             = Column(String, primary_key=True, default=gen_uuid)
    connection_id  = Column(String, ForeignKey("replication_connections.id"), nullable=False, index=True)
    connector_type = Column(String(80), default="snowflake", index=True)
    name           = Column(String(255), nullable=False)
    database       = Column(String(255), default="")
    schema         = Column(String(255), default="")
    warehouse      = Column(String(255), default="")
    readiness_status = Column(String(40), default="NOT_CHECKED", index=True)
    latest_error   = Column(Text, default="")
    checked_at     = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReplicationJob(Base):
    __tablename__ = "replication_jobs"

    id                    = Column(String, primary_key=True, default=gen_uuid)
    name                  = Column(String(255), nullable=False)
    source_connection_id  = Column(String, ForeignKey("replication_connections.id"), nullable=False, index=True)
    destination_connection_id = Column(String, ForeignKey("replication_connections.id"), nullable=False, index=True)
    source_id             = Column(String, ForeignKey("replication_sources.id"), nullable=True, index=True)
    destination_id        = Column(String, ForeignKey("replication_destinations.id"), nullable=True, index=True)
    sync_mode             = Column(String(50), default="incremental", index=True)
    schedule              = Column(String(100), nullable=True)
    status                = Column(String(40), default="DRAFT", index=True)
    latest_error          = Column(Text, default="")
    last_sync_at          = Column(DateTime, nullable=True)
    created_by_id         = Column(String, ForeignKey("users.id"), nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReplicationJobTable(Base):
    __tablename__ = "replication_job_tables"
    __table_args__ = (
        UniqueConstraint("job_id", "schema_name", "table_name", name="uq_replication_job_table"),
    )

    id                  = Column(String, primary_key=True, default=gen_uuid)
    job_id              = Column(String, ForeignKey("replication_jobs.id"), nullable=False, index=True)
    schema_name         = Column(String(255), nullable=False)
    table_name          = Column(String(255), nullable=False)
    target_schema       = Column(String(255), default="")
    target_table        = Column(String(255), default="")
    selected            = Column(Boolean, default=True, index=True)
    sync_mode           = Column(String(50), default="incremental")
    columns             = Column(JSON, nullable=False, default=list)
    primary_key_columns = Column(JSON, nullable=False, default=list)
    watermark_column    = Column(String(255), nullable=True)
    status              = Column(String(40), default="NOT_STARTED", index=True)
    latest_error        = Column(Text, default="")
    last_sync_at        = Column(DateTime, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReplicationPlan(Base):
    __tablename__ = "replication_plans"
    __table_args__ = (
        UniqueConstraint("job_id", "job_table_id", name="uq_replication_plan_job_table"),
    )

    id                    = Column(String, primary_key=True, default=gen_uuid)
    job_id                = Column(String, ForeignKey("replication_jobs.id"), nullable=False, index=True)
    job_table_id          = Column(String, ForeignKey("replication_job_tables.id"), nullable=False, index=True)
    source_schema         = Column(String(255), nullable=False)
    source_object         = Column(String(255), nullable=False)
    target_database       = Column(String(255), default="")
    target_schema         = Column(String(255), default="")
    target_object         = Column(String(255), default="")
    object_type           = Column(String(80), default="TABLE")
    primary_key_columns   = Column(JSON, nullable=False, default=list)
    watermark_column      = Column(String(255), nullable=True)
    load_mode             = Column(String(80), default="FULL_LOAD", index=True)
    write_mode            = Column(String(80), default="CREATE_OR_REPLACE", index=True)
    estimated_rows        = Column(Integer, default=0)
    estimated_bytes       = Column(Integer, default=0)
    chunk_strategy        = Column(String(120), default="SINGLE_TABLE_SCAN")
    sync_frequency        = Column(String(120), default="manual")
    soft_delete_column    = Column(String(255), nullable=True)
    schema_drift_policy   = Column(String(120), default="ADDITIVE_ONLY_REVIEW")
    initial_load_required = Column(Boolean, default=True)
    incremental_supported = Column(Boolean, default=False, index=True)
    risk_level            = Column(String(40), default="MEDIUM", index=True)
    reasoning             = Column(Text, default="")
    created_at            = Column(DateTime, default=datetime.utcnow)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReplicationRun(Base):
    __tablename__ = "replication_runs"

    id             = Column(String, primary_key=True, default=gen_uuid)
    job_id         = Column(String, ForeignKey("replication_jobs.id"), nullable=False, index=True)
    status         = Column(String(40), default="QUEUED", index=True)
    trigger        = Column(String(40), default="manual")
    attempt_number = Column(Integer, default=1)
    planned_tables = Column(Integer, default=0)
    started_at     = Column(DateTime, nullable=True)
    ended_at       = Column(DateTime, nullable=True)
    latest_error   = Column(Text, default="")
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReplicationTableRun(Base):
    __tablename__ = "replication_table_runs"

    id           = Column(String, primary_key=True, default=gen_uuid)
    run_id       = Column(String, ForeignKey("replication_runs.id"), nullable=False, index=True)
    job_id       = Column(String, ForeignKey("replication_jobs.id"), nullable=False, index=True)
    job_table_id = Column(String, ForeignKey("replication_job_tables.id"), nullable=False, index=True)
    schema_name  = Column(String(255), nullable=False)
    table_name   = Column(String(255), nullable=False)
    status       = Column(String(40), default="PLANNED", index=True)
    latest_error = Column(Text, default="")
    started_at   = Column(DateTime, nullable=True)
    ended_at     = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)


class ReplicationWatermark(Base):
    __tablename__ = "replication_watermarks"
    __table_args__ = (
        UniqueConstraint("job_id", "job_table_id", name="uq_replication_watermark_job_table"),
    )

    id              = Column(String, primary_key=True, default=gen_uuid)
    job_id          = Column(String, ForeignKey("replication_jobs.id"), nullable=False, index=True)
    job_table_id    = Column(String, ForeignKey("replication_job_tables.id"), nullable=False, index=True)
    watermark_column = Column(String(255), nullable=True)
    watermark_value = Column(String(255), nullable=True)
    state_json      = Column(JSON, nullable=False, default=dict)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReplicationEvent(Base):
    __tablename__ = "replication_events"

    id           = Column(String, primary_key=True, default=gen_uuid)
    job_id       = Column(String, ForeignKey("replication_jobs.id"), nullable=True, index=True)
    run_id       = Column(String, ForeignKey("replication_runs.id"), nullable=True, index=True)
    level        = Column(String(20), default="INFO", index=True)
    event_type   = Column(String(100), nullable=False, index=True)
    message      = Column(Text, nullable=False)
    event_json   = Column(JSON, nullable=False, default=dict)
    created_at   = Column(DateTime, default=datetime.utcnow, index=True)


class ReplicationError(Base):
    __tablename__ = "replication_errors"

    id          = Column(String, primary_key=True, default=gen_uuid)
    job_id      = Column(String, ForeignKey("replication_jobs.id"), nullable=True, index=True)
    run_id      = Column(String, ForeignKey("replication_runs.id"), nullable=True, index=True)
    table_run_id = Column(String, ForeignKey("replication_table_runs.id"), nullable=True, index=True)
    connection_id = Column(String, ForeignKey("replication_connections.id"), nullable=True, index=True)
    category    = Column(String(100), default="control_plane")
    message     = Column(Text, nullable=False)
    safe_detail = Column(Text, default="")
    created_at  = Column(DateTime, default=datetime.utcnow, index=True)


class ConnectorHealthCheck(Base):
    __tablename__ = "connector_health_checks"

    id             = Column(String, primary_key=True, default=gen_uuid)
    connection_id  = Column(String, ForeignKey("replication_connections.id"), nullable=False, index=True)
    status         = Column(String(40), default="NOT_CONFIGURED", index=True)
    checked_at     = Column(DateTime, default=datetime.utcnow, index=True)
    latency_ms     = Column(Integer, nullable=True)
    message        = Column(Text, default="")
    safe_error     = Column(Text, default="")
    details        = Column(JSON, nullable=False, default=dict)


class SnowflakePermissionCheck(Base):
    __tablename__ = "snowflake_permission_checks"

    id             = Column(String, primary_key=True, default=gen_uuid)
    connection_id  = Column(String, ForeignKey("replication_connections.id"), nullable=True, index=True)
    status         = Column(String(40), default="NOT_CHECKED", index=True)
    checked_at     = Column(DateTime, default=datetime.utcnow, index=True)
    database       = Column(String(255), default="")
    schema         = Column(String(255), default="")
    warehouse      = Column(String(255), default="")
    missing_permissions = Column(JSON, nullable=False, default=list)
    message        = Column(Text, default="")
    safe_error     = Column(Text, default="")
    details        = Column(JSON, nullable=False, default=dict)


class CodeGenerationArtifact(Base):
    __tablename__ = "code_generation_artifacts"

    id              = Column(String, primary_key=True, default=gen_uuid)
    user_id         = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    generation_type = Column(String(80), nullable=False, index=True)
    source_language = Column(String(120), default="")
    target_language = Column(String(120), default="")
    prompt          = Column(Text, default="")
    source_code     = Column(Text, default="")
    metadata_json   = Column(JSON, nullable=False, default=dict)
    basis_for_generation = Column(String(80), default="user_prompt_only", index=True)
    parent_artifact_id = Column(String, ForeignKey("code_generation_artifacts.id"), nullable=True, index=True)
    revision_number = Column(Integer, default=1)
    generated_code  = Column(Text, default="")
    technical_design_document = Column(JSON, nullable=False, default=dict)
    initial_judge_review = Column(JSON, nullable=False, default=dict)
    safety_notes    = Column(JSON, nullable=False, default=list)
    execution_ready = Column(Boolean, default=False, index=True)
    status          = Column(String(40), default="GENERATED", index=True)
    created_at      = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CodeGenerationJudgeReview(Base):
    __tablename__ = "code_generation_judge_reviews"

    id                 = Column(String, primary_key=True, default=gen_uuid)
    artifact_id        = Column(String, ForeignKey("code_generation_artifacts.id"), nullable=False, index=True)
    reviewer_id        = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    score              = Column(Integer, nullable=False)
    status             = Column(String(40), default="NEEDS_IMPROVEMENT", index=True)
    improvement_points = Column(JSON, nullable=False, default=list)
    blocking_issues    = Column(JSON, nullable=False, default=list)
    notes              = Column(Text, default="")
    created_at         = Column(DateTime, default=datetime.utcnow, index=True)


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id             = Column(String, primary_key=True, default=gen_uuid)
    run_id         = Column(String, nullable=True, index=True)
    artifact_id    = Column(String, nullable=True, index=True)
    job_id         = Column(String, nullable=True, index=True)
    artifact_type  = Column(String(120), nullable=True, index=True)
    file_path      = Column(Text, nullable=True)
    content_hash   = Column(String(128), nullable=True, index=True)
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)
    metadata_json  = Column(JSON, nullable=False, default=dict)


class RagChunkModel(Base):
    __tablename__ = "rag_chunks"

    id             = Column(String, primary_key=True, default=gen_uuid)
    document_id    = Column(String, ForeignKey("rag_documents.id"), nullable=True, index=True)
    run_id         = Column(String, nullable=True, index=True)
    chunk_index    = Column(Integer, default=0)
    chunk_text     = Column(Text, nullable=False)
    embedding      = Column(JSON, nullable=True)
    metadata_json  = Column(JSON, nullable=False, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)
