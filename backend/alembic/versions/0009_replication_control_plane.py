"""replication control plane tables

Revision ID: 0009_replication_control_plane
Revises: 0008_agentic_orchestrator
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_replication_control_plane"
down_revision = "0008_agentic_orchestrator"
branch_labels = None
depends_on = None


def _has_table(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _json_type(bind):
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    json_t = _json_type(bind)

    if not _has_table(bind, "replication_connections"):
        op.create_table(
            "replication_connections",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("connector_type", sa.String(length=80), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
            sa.Column("config", json_t, nullable=False),
            sa.Column("credentials", json_t, nullable=False),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("latest_error", sa.Text(), nullable=True),
            sa.Column("last_tested_at", sa.DateTime(), nullable=True),
            sa.Column("created_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for col in ("connector_type", "role", "connection_id", "status"):
            op.create_index(f"ix_replication_connections_{col}", "replication_connections", [col])

    if not _has_table(bind, "replication_sources"):
        op.create_table(
            "replication_sources",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("replication_connections.id"), nullable=False),
            sa.Column("connector_type", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("discovery_status", sa.String(length=40), nullable=True),
            sa.Column("discovery_reason", sa.Text(), nullable=True),
            sa.Column("schemas", json_t, nullable=False),
            sa.Column("discovered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for col in ("connection_id", "connector_type", "discovery_status"):
            op.create_index(f"ix_replication_sources_{col}", "replication_sources", [col])

    if not _has_table(bind, "replication_destinations"):
        op.create_table(
            "replication_destinations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("replication_connections.id"), nullable=False),
            sa.Column("connector_type", sa.String(length=80), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("database", sa.String(length=255), nullable=True),
            sa.Column("schema", sa.String(length=255), nullable=True),
            sa.Column("warehouse", sa.String(length=255), nullable=True),
            sa.Column("readiness_status", sa.String(length=40), nullable=True),
            sa.Column("latest_error", sa.Text(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for col in ("connection_id", "connector_type", "readiness_status"):
            op.create_index(f"ix_replication_destinations_{col}", "replication_destinations", [col])

    if not _has_table(bind, "replication_jobs"):
        op.create_table(
            "replication_jobs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("source_connection_id", sa.String(), sa.ForeignKey("replication_connections.id"), nullable=False),
            sa.Column("destination_connection_id", sa.String(), sa.ForeignKey("replication_connections.id"), nullable=False),
            sa.Column("source_id", sa.String(), sa.ForeignKey("replication_sources.id"), nullable=True),
            sa.Column("destination_id", sa.String(), sa.ForeignKey("replication_destinations.id"), nullable=True),
            sa.Column("sync_mode", sa.String(length=50), nullable=True),
            sa.Column("schedule", sa.String(length=100), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("latest_error", sa.Text(), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(), nullable=True),
            sa.Column("created_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for col in ("source_connection_id", "destination_connection_id", "source_id", "destination_id", "sync_mode", "status"):
            op.create_index(f"ix_replication_jobs_{col}", "replication_jobs", [col])

    if not _has_table(bind, "replication_job_tables"):
        op.create_table(
            "replication_job_tables",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("replication_jobs.id"), nullable=False),
            sa.Column("schema_name", sa.String(length=255), nullable=False),
            sa.Column("table_name", sa.String(length=255), nullable=False),
            sa.Column("target_schema", sa.String(length=255), nullable=True),
            sa.Column("target_table", sa.String(length=255), nullable=True),
            sa.Column("selected", sa.Boolean(), nullable=True),
            sa.Column("sync_mode", sa.String(length=50), nullable=True),
            sa.Column("columns", json_t, nullable=False),
            sa.Column("primary_key_columns", json_t, nullable=False),
            sa.Column("watermark_column", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("latest_error", sa.Text(), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("job_id", "schema_name", "table_name", name="uq_replication_job_table"),
        )
        for col in ("job_id", "selected", "status"):
            op.create_index(f"ix_replication_job_tables_{col}", "replication_job_tables", [col])

    if not _has_table(bind, "replication_plans"):
        op.create_table(
            "replication_plans",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("replication_jobs.id"), nullable=False),
            sa.Column("job_table_id", sa.String(), sa.ForeignKey("replication_job_tables.id"), nullable=False),
            sa.Column("source_schema", sa.String(length=255), nullable=False),
            sa.Column("source_object", sa.String(length=255), nullable=False),
            sa.Column("target_database", sa.String(length=255), nullable=True),
            sa.Column("target_schema", sa.String(length=255), nullable=True),
            sa.Column("target_object", sa.String(length=255), nullable=True),
            sa.Column("object_type", sa.String(length=80), nullable=True),
            sa.Column("primary_key_columns", json_t, nullable=False),
            sa.Column("watermark_column", sa.String(length=255), nullable=True),
            sa.Column("load_mode", sa.String(length=80), nullable=True),
            sa.Column("write_mode", sa.String(length=80), nullable=True),
            sa.Column("estimated_rows", sa.Integer(), nullable=True),
            sa.Column("estimated_bytes", sa.Integer(), nullable=True),
            sa.Column("chunk_strategy", sa.String(length=120), nullable=True),
            sa.Column("sync_frequency", sa.String(length=120), nullable=True),
            sa.Column("soft_delete_column", sa.String(length=255), nullable=True),
            sa.Column("schema_drift_policy", sa.String(length=120), nullable=True),
            sa.Column("initial_load_required", sa.Boolean(), nullable=True),
            sa.Column("incremental_supported", sa.Boolean(), nullable=True),
            sa.Column("risk_level", sa.String(length=40), nullable=True),
            sa.Column("reasoning", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("job_id", "job_table_id", name="uq_replication_plan_job_table"),
        )
        for col in ("job_id", "job_table_id", "load_mode", "write_mode", "incremental_supported", "risk_level"):
            op.create_index(f"ix_replication_plans_{col}", "replication_plans", [col])

    if not _has_table(bind, "replication_runs"):
        op.create_table(
            "replication_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("replication_jobs.id"), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("trigger", sa.String(length=40), nullable=True),
            sa.Column("attempt_number", sa.Integer(), nullable=True),
            sa.Column("planned_tables", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("latest_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for col in ("job_id", "status", "created_at"):
            op.create_index(f"ix_replication_runs_{col}", "replication_runs", [col])

    if not _has_table(bind, "replication_table_runs"):
        op.create_table(
            "replication_table_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("replication_runs.id"), nullable=False),
            sa.Column("job_id", sa.String(), sa.ForeignKey("replication_jobs.id"), nullable=False),
            sa.Column("job_table_id", sa.String(), sa.ForeignKey("replication_job_tables.id"), nullable=False),
            sa.Column("schema_name", sa.String(length=255), nullable=False),
            sa.Column("table_name", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("latest_error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for col in ("run_id", "job_id", "job_table_id", "status"):
            op.create_index(f"ix_replication_table_runs_{col}", "replication_table_runs", [col])

    if not _has_table(bind, "replication_watermarks"):
        op.create_table(
            "replication_watermarks",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("replication_jobs.id"), nullable=False),
            sa.Column("job_table_id", sa.String(), sa.ForeignKey("replication_job_tables.id"), nullable=False),
            sa.Column("watermark_column", sa.String(length=255), nullable=True),
            sa.Column("watermark_value", sa.String(length=255), nullable=True),
            sa.Column("state_json", json_t, nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("job_id", "job_table_id", name="uq_replication_watermark_job_table"),
        )
        for col in ("job_id", "job_table_id"):
            op.create_index(f"ix_replication_watermarks_{col}", "replication_watermarks", [col])

    if not _has_table(bind, "replication_events"):
        op.create_table(
            "replication_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("replication_jobs.id"), nullable=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("replication_runs.id"), nullable=True),
            sa.Column("level", sa.String(length=20), nullable=True),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("event_json", json_t, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for col in ("job_id", "run_id", "level", "event_type", "created_at"):
            op.create_index(f"ix_replication_events_{col}", "replication_events", [col])

    if not _has_table(bind, "replication_errors"):
        op.create_table(
            "replication_errors",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("replication_jobs.id"), nullable=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("replication_runs.id"), nullable=True),
            sa.Column("table_run_id", sa.String(), sa.ForeignKey("replication_table_runs.id"), nullable=True),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("replication_connections.id"), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("safe_detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for col in ("job_id", "run_id", "table_run_id", "connection_id", "created_at"):
            op.create_index(f"ix_replication_errors_{col}", "replication_errors", [col])

    if not _has_table(bind, "connector_health_checks"):
        op.create_table(
            "connector_health_checks",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("replication_connections.id"), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("safe_error", sa.Text(), nullable=True),
            sa.Column("details", json_t, nullable=False),
        )
        for col in ("connection_id", "status", "checked_at"):
            op.create_index(f"ix_connector_health_checks_{col}", "connector_health_checks", [col])

    if not _has_table(bind, "snowflake_permission_checks"):
        op.create_table(
            "snowflake_permission_checks",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("connection_id", sa.String(), sa.ForeignKey("replication_connections.id"), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("database", sa.String(length=255), nullable=True),
            sa.Column("schema", sa.String(length=255), nullable=True),
            sa.Column("warehouse", sa.String(length=255), nullable=True),
            sa.Column("missing_permissions", json_t, nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("safe_error", sa.Text(), nullable=True),
            sa.Column("details", json_t, nullable=False),
        )
        for col in ("connection_id", "status", "checked_at"):
            op.create_index(f"ix_snowflake_permission_checks_{col}", "snowflake_permission_checks", [col])


def downgrade() -> None:
    for table in (
        "snowflake_permission_checks",
        "connector_health_checks",
        "replication_errors",
        "replication_events",
        "replication_watermarks",
        "replication_table_runs",
        "replication_runs",
        "replication_plans",
        "replication_job_tables",
        "replication_jobs",
        "replication_destinations",
        "replication_sources",
        "replication_connections",
    ):
        op.drop_table(table)
