"""add migration intelligence backend tables

Revision ID: 0012_migration_intelligence_backend
Revises: 0011_codegen_revisions
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_migration_intelligence_backend"
down_revision = "0011_codegen_revisions"
branch_labels = None
depends_on = None


def _json_type(bind):
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    json_t = _json_type(bind)

    op.create_table(
        "uploaded_artifacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=40), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("extraction_status", sa.String(length=40), nullable=False),
        sa.Column("extracted_text_preview", sa.Text(), nullable=True),
        sa.Column("classification", sa.String(length=80), nullable=True),
        sa.Column("language_guess", sa.String(length=80), nullable=True),
        sa.Column("source_system_guess", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    for col in ("file_type", "sha256_hash", "uploaded_by", "created_at", "extraction_status", "classification"):
        op.create_index(f"ix_uploaded_artifacts_{col}", "uploaded_artifacts", [col], unique=False)

    op.create_table(
        "artifact_extractions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("artifact_id", sa.String(), sa.ForeignKey("uploaded_artifacts.id"), nullable=False),
        sa.Column("extraction_status", sa.String(length=40), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extracted_text_preview", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", json_t, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    for col in ("artifact_id", "extraction_status", "created_at"):
        op.create_index(f"ix_artifact_extractions_{col}", "artifact_extractions", [col])

    op.create_table(
        "artifact_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("artifact_id", sa.String(), sa.ForeignKey("uploaded_artifacts.id"), nullable=False),
        sa.Column("extraction_id", sa.String(), sa.ForeignKey("artifact_extractions.id"), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=255), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("statement_type", sa.String(length=80), nullable=True),
        sa.Column("object_name", sa.String(length=255), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("metadata_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("artifact_id", "extraction_id", "chunk_type", "statement_type", "created_at"):
        op.create_index(f"ix_artifact_chunks_{col}", "artifact_chunks", [col])

    op.create_table(
        "migration_intelligence_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("selected_artifact_ids", json_t, nullable=False),
        sa.Column("source_connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
        sa.Column("target_connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("agent_mode", sa.String(length=80), nullable=False),
        sa.Column("openai_called", sa.Boolean(), nullable=False),
        sa.Column("snowflake_cortex_called", sa.Boolean(), nullable=False),
        sa.Column("snowflake_sql_executed", sa.Boolean(), nullable=False),
        sa.Column("uploaded_sql_executed", sa.Boolean(), nullable=False),
        sa.Column("generated_code_executed", sa.Boolean(), nullable=False),
        sa.Column("ddl_executed", sa.Boolean(), nullable=False),
        sa.Column("data_moved", sa.Boolean(), nullable=False),
        sa.Column("token_credit_note", sa.Text(), nullable=True),
        sa.Column("latest_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("source_connection_id", "target_connection_id", "status", "started_by", "started_at", "created_at"):
        op.create_index(f"ix_migration_intelligence_runs_{col}", "migration_intelligence_runs", [col])

    op.create_table(
        "migration_intelligence_run_steps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("migration_intelligence_runs.id"), nullable=False),
        sa.Column("step_name", sa.String(length=120), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("details_json", json_t, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "step_name", "status", "created_at"):
        op.create_index(f"ix_migration_intelligence_run_steps_{col}", "migration_intelligence_run_steps", [col])

    op.create_table(
        "migration_intelligence_findings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("migration_intelligence_runs.id"), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("finding_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", json_t, nullable=False),
        sa.Column("source_artifact_id", sa.String(), sa.ForeignKey("uploaded_artifacts.id"), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "severity", "finding_type", "source_artifact_id", "status", "created_at"):
        op.create_index(f"ix_migration_intelligence_findings_{col}", "migration_intelligence_findings", [col])

    op.create_table(
        "migration_intelligence_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("migration_intelligence_runs.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("report_json", json_t, nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_migration_intelligence_reports_run_id", "migration_intelligence_reports", ["run_id"], unique=True)
    op.create_index("ix_migration_intelligence_reports_created_at", "migration_intelligence_reports", ["created_at"])


def downgrade() -> None:
    for table in (
        "migration_intelligence_reports",
        "migration_intelligence_findings",
        "migration_intelligence_run_steps",
        "migration_intelligence_runs",
        "artifact_chunks",
        "artifact_extractions",
        "uploaded_artifacts",
    ):
        op.drop_table(table)
