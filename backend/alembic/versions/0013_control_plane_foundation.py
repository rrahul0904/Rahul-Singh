"""add migration control plane foundation

Revision ID: 0013_control_plane_foundation
Revises: 0012_migration_intelligence_backend
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_control_plane_foundation"
down_revision = "0012_migration_intelligence_backend"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ix(table: str, column: str, unique: bool = False) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column], unique=unique)


def upgrade() -> None:
    json_t = _json_type()

    op.create_table(
        "control_plane_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("workflow_type", sa.String(length=80), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=True),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("source_dialect", sa.String(length=80), nullable=True),
        sa.Column("target_dialect", sa.String(length=80), nullable=True),
        sa.Column("source_connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
        sa.Column("target_connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
        sa.Column("safety_mode", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_phase", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary_json", json_t, nullable=False),
        sa.Column("metrics_json", json_t, nullable=False),
        sa.Column("config_json", json_t, nullable=False),
        sa.Column("approval_granted", sa.Boolean(), nullable=True),
        sa.Column("approved_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
    )
    for col in (
        "workflow_type",
        "source_connection_id",
        "target_connection_id",
        "safety_mode",
        "status",
        "created_by",
        "created_at",
        "approval_granted",
    ):
        _ix("control_plane_runs", col)

    op.create_table(
        "control_plane_artifacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("control_plane_runs.id"), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=40), nullable=False),
        sa.Column("artifact_category", sa.String(length=80), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("metadata_json", json_t, nullable=False),
    )
    for col in ("run_id", "file_type", "artifact_category", "checksum_sha256", "created_by", "created_at"):
        _ix("control_plane_artifacts", col)

    op.create_table(
        "control_plane_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("control_plane_runs.id"), nullable=False),
        sa.Column("module", sa.String(length=80), nullable=False),
        sa.Column("phase", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("logs_redacted", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("output_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "module", "phase", "status", "created_at"):
        _ix("control_plane_jobs", col)

    op.create_table(
        "sql_conversion_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("control_plane_runs.id"), nullable=False),
        sa.Column("artifact_id", sa.String(), sa.ForeignKey("control_plane_artifacts.id"), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("statement_index", sa.Integer(), nullable=True),
        sa.Column("statement_type", sa.String(length=80), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_dialect", sa.String(length=80), nullable=True),
        sa.Column("target_dialect", sa.String(length=80), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("metadata_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "artifact_id", "statement_index", "statement_type", "severity", "created_at"):
        _ix("sql_conversion_messages", col)

    op.create_table(
        "human_review_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("control_plane_runs.id"), nullable=False),
        sa.Column("item_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("reviewer_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "item_type", "severity", "status", "created_at"):
        _ix("human_review_items", col)

    op.create_table(
        "analyzer_components",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("control_plane_runs.id"), nullable=False),
        sa.Column("component_type", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "component_type", "name", "created_at"):
        _ix("analyzer_components", col)

    op.create_table(
        "analyzer_dependencies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("control_plane_runs.id"), nullable=False),
        sa.Column("source_component", sa.String(length=255), nullable=False),
        sa.Column("target_component", sa.String(length=255), nullable=False),
        sa.Column("dependency_type", sa.String(length=80), nullable=False),
        sa.Column("metadata_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "source_component", "target_component", "dependency_type", "created_at"):
        _ix("analyzer_dependencies", col)

    op.create_table(
        "advisor_scans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("control_plane_runs.id"), nullable=True),
        sa.Column("connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("health_score", sa.Integer(), nullable=True),
        sa.Column("security_score", sa.Integer(), nullable=True),
        sa.Column("compute_score", sa.Integer(), nullable=True),
        sa.Column("storage_score", sa.Integer(), nullable=True),
        sa.Column("cost_score", sa.Integer(), nullable=True),
        sa.Column("operational_score", sa.Integer(), nullable=True),
        sa.Column("migration_readiness_score", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("config_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "connection_id", "status", "created_at"):
        _ix("advisor_scans", col)

    op.create_table(
        "advisor_check_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scan_id", sa.String(), sa.ForeignKey("advisor_scans.id"), nullable=False),
        sa.Column("check_name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("result_sample_json", json_t, nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("raw_sql_redacted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("scan_id", "check_name", "category", "severity", "status", "created_at"):
        _ix("advisor_check_results", col)


def downgrade() -> None:
    for table in (
        "advisor_check_results",
        "advisor_scans",
        "analyzer_dependencies",
        "analyzer_components",
        "human_review_items",
        "sql_conversion_messages",
        "control_plane_jobs",
        "control_plane_artifacts",
        "control_plane_runs",
    ):
        op.drop_table(table)
