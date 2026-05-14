"""add run events and schema drift results

Revision ID: 0007_run_events_schema_drift
Revises: 0006_chunk_manifest_validation_results
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0007_run_events_schema_drift"
down_revision = "0006_chunk_manifest_validation_results"
branch_labels = None
depends_on = None


def _has_table(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "migration_run_events"):
        op.create_table(
            "migration_run_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("migration_runs.id"), nullable=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("task_id", sa.String(), sa.ForeignKey("job_tasks.id"), nullable=True),
            sa.Column("table_key", sa.String(length=512), nullable=True),
            sa.Column("phase", sa.String(length=50), nullable=True),
            sa.Column("event", sa.String(length=100), nullable=False),
            sa.Column("level", sa.String(length=20), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("rows_extracted", sa.Integer(), nullable=True),
            sa.Column("rows_loaded", sa.Integer(), nullable=True),
            sa.Column("rows_merged", sa.Integer(), nullable=True),
            sa.Column("rows_deleted", sa.Integer(), nullable=True),
            sa.Column("chunk_count", sa.Integer(), nullable=True),
            sa.Column("error_category", sa.String(length=100), nullable=True),
            sa.Column("event_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for col in ["run_id", "job_id", "task_id", "table_key", "phase", "event"]:
            op.create_index(f"ix_migration_run_events_{col}", "migration_run_events", [col])

    if not _has_table(bind, "migration_schema_drift_results"):
        op.create_table(
            "migration_schema_drift_results",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("migration_runs.id"), nullable=True),
            sa.Column("task_id", sa.String(), sa.ForeignKey("job_tasks.id"), nullable=True),
            sa.Column("table_key", sa.String(length=512), nullable=False),
            sa.Column("drift_type", sa.String(length=50), nullable=False),
            sa.Column("column_name", sa.String(length=255), nullable=True),
            sa.Column("source_type", sa.String(length=255), nullable=True),
            sa.Column("target_type", sa.String(length=255), nullable=True),
            sa.Column("source_nullable", sa.Boolean(), nullable=True),
            sa.Column("target_nullable", sa.Boolean(), nullable=True),
            sa.Column("severity", sa.String(length=20), nullable=True),
            sa.Column("action_taken", sa.String(length=50), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for col in ["job_id", "run_id", "task_id", "table_key", "drift_type", "column_name"]:
            op.create_index(f"ix_migration_schema_drift_results_{col}", "migration_schema_drift_results", [col])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "migration_schema_drift_results"):
        op.drop_table("migration_schema_drift_results")
    if _has_table(bind, "migration_run_events"):
        op.drop_table("migration_run_events")
