"""add chunk manifest and run validation results

Revision ID: 0006_chunk_manifest_validation_results
Revises: 0005_cost_tracking_and_job_leases
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0006_chunk_manifest_validation_results"
down_revision = "0005_cost_tracking_and_job_leases"
branch_labels = None
depends_on = None


def _has_table(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "migration_chunk_manifest"):
        op.create_table(
            "migration_chunk_manifest",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("migration_runs.id"), nullable=False),
            sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("task_id", sa.String(), sa.ForeignKey("job_tasks.id"), nullable=False),
            sa.Column("table_key", sa.String(length=512), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(length=30), nullable=True),
            sa.Column("file_path", sa.Text(), nullable=True),
            sa.Column("stage_table", sa.String(length=512), nullable=True),
            sa.Column("row_count", sa.Integer(), nullable=True),
            sa.Column("bytes_staged", sa.Integer(), nullable=True),
            sa.Column("watermark_start", sa.String(length=255), nullable=True),
            sa.Column("watermark_end", sa.String(length=255), nullable=True),
            sa.Column("primary_key_end", sa.String(length=255), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("run_id", "task_id", "chunk_index", name="uq_chunk_manifest_run_task_index"),
        )
        op.create_index("ix_migration_chunk_manifest_run_id", "migration_chunk_manifest", ["run_id"])
        op.create_index("ix_migration_chunk_manifest_job_id", "migration_chunk_manifest", ["job_id"])
        op.create_index("ix_migration_chunk_manifest_task_id", "migration_chunk_manifest", ["task_id"])
        op.create_index("ix_migration_chunk_manifest_table_key", "migration_chunk_manifest", ["table_key"])
        op.create_index("ix_migration_chunk_manifest_state", "migration_chunk_manifest", ["state"])

    if not _has_table(bind, "migration_validation_results"):
        op.create_table(
            "migration_validation_results",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("migration_runs.id"), nullable=False),
            sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("task_id", sa.String(), sa.ForeignKey("job_tasks.id"), nullable=True),
            sa.Column("table_key", sa.String(length=512), nullable=True),
            sa.Column("rule_type", sa.String(length=50), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("source_value", sa.String(length=255), nullable=True),
            sa.Column("target_value", sa.String(length=255), nullable=True),
            sa.Column("delta", sa.String(length=100), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_migration_validation_results_run_id", "migration_validation_results", ["run_id"])
        op.create_index("ix_migration_validation_results_job_id", "migration_validation_results", ["job_id"])
        op.create_index("ix_migration_validation_results_task_id", "migration_validation_results", ["task_id"])
        op.create_index("ix_migration_validation_results_table_key", "migration_validation_results", ["table_key"])
        op.create_index("ix_migration_validation_results_rule_type", "migration_validation_results", ["rule_type"])
        op.create_index("ix_migration_validation_results_status", "migration_validation_results", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "migration_validation_results"):
        op.drop_table("migration_validation_results")
    if _has_table(bind, "migration_chunk_manifest"):
        op.drop_table("migration_chunk_manifest")
