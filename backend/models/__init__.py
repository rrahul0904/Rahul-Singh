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

# ─── Managed Syncs (Fivetran/Stitch-style foundation) ────────

class SyncProfile(Base):
    __tablename__ = "sync_profiles"

    id                  = Column(String, primary_key=True, default=gen_uuid)
    name                = Column(String(255), nullable=False)
    source_connection_id= Column(String, ForeignKey("connections.id"), nullable=False)
    dest_connection_id  = Column(String, ForeignKey("connections.id"), nullable=False)
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
