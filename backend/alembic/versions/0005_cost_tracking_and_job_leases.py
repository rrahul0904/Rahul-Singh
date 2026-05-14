"""add cost tracking and job run leases

Revision ID: 0005_cost_tracking_and_job_leases
Revises: 0004_sync_profile_job_binding
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0005_cost_tracking_and_job_leases"
down_revision = "0004_sync_profile_job_binding"
branch_labels = None
depends_on = None


def _has_table(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "job_run_leases"):
        op.create_table(
            "job_run_leases",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("run_id", sa.String(), sa.ForeignKey("migration_runs.id"), nullable=True),
            sa.Column("holder_id", sa.String(length=255), nullable=False),
            sa.Column("acquired_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_job_run_leases_job_id", "job_run_leases", ["job_id"], unique=True)
        op.create_index("ix_job_run_leases_run_id", "job_run_leases", ["run_id"], unique=False)
        op.create_index("ix_job_run_leases_expires_at", "job_run_leases", ["expires_at"], unique=False)

    if not _has_table(bind, "migration_cost_estimates"):
        op.create_table(
            "migration_cost_estimates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("run_id", sa.String(), sa.ForeignKey("migration_runs.id"), nullable=False),
            sa.Column("table_name", sa.String(length=512), nullable=True),
            sa.Column("estimated_rows", sa.Integer(), nullable=True),
            sa.Column("estimated_source_bytes", sa.Integer(), nullable=True),
            sa.Column("estimated_compressed_bytes", sa.Integer(), nullable=True),
            sa.Column("estimated_runtime_seconds", sa.Float(), nullable=True),
            sa.Column("estimated_credits", sa.Float(), nullable=True),
            sa.Column("estimated_cost", sa.Float(), nullable=True),
            sa.Column("currency", sa.String(length=10), nullable=True),
            sa.Column("confidence_level", sa.String(length=20), nullable=True),
            sa.Column("assumptions", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_migration_cost_estimates_job_id", "migration_cost_estimates", ["job_id"])
        op.create_index("ix_migration_cost_estimates_run_id", "migration_cost_estimates", ["run_id"])
        op.create_index("ix_migration_cost_estimates_table_name", "migration_cost_estimates", ["table_name"])

    if not _has_table(bind, "migration_snowflake_queries"):
        op.create_table(
            "migration_snowflake_queries",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("run_id", sa.String(), sa.ForeignKey("migration_runs.id"), nullable=False),
            sa.Column("task_id", sa.String(), sa.ForeignKey("job_tasks.id"), nullable=True),
            sa.Column("table_name", sa.String(length=512), nullable=True),
            sa.Column("phase", sa.String(length=50), nullable=False),
            sa.Column("query_id", sa.String(length=255), nullable=False),
            sa.Column("query_tag", sa.Text(), nullable=False),
            sa.Column("warehouse_name", sa.String(length=255), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("execution_time_ms", sa.Integer(), nullable=True),
            sa.Column("bytes_scanned", sa.Integer(), nullable=True),
            sa.Column("rows_inserted", sa.Integer(), nullable=True),
            sa.Column("rows_updated", sa.Integer(), nullable=True),
            sa.Column("rows_deleted", sa.Integer(), nullable=True),
            sa.Column("credits_attributed", sa.Float(), nullable=True),
            sa.Column("estimated_cost", sa.Float(), nullable=True),
            sa.Column("actual_cost", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_migration_snowflake_queries_job_id", "migration_snowflake_queries", ["job_id"])
        op.create_index("ix_migration_snowflake_queries_run_id", "migration_snowflake_queries", ["run_id"])
        op.create_index("ix_migration_snowflake_queries_task_id", "migration_snowflake_queries", ["task_id"])
        op.create_index("ix_migration_snowflake_queries_table_name", "migration_snowflake_queries", ["table_name"])
        op.create_index("ix_migration_snowflake_queries_phase", "migration_snowflake_queries", ["phase"])
        op.create_index("ix_migration_snowflake_queries_query_id", "migration_snowflake_queries", ["query_id"])

    if not _has_table(bind, "migration_cost_actuals"):
        op.create_table(
            "migration_cost_actuals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("run_id", sa.String(), sa.ForeignKey("migration_runs.id"), nullable=False),
            sa.Column("warehouse_credits", sa.Float(), nullable=True),
            sa.Column("query_attributed_credits", sa.Float(), nullable=True),
            sa.Column("cloud_services_credits", sa.Float(), nullable=True),
            sa.Column("cortex_credits", sa.Float(), nullable=True),
            sa.Column("snowpark_credits", sa.Float(), nullable=True),
            sa.Column("storage_cost", sa.Float(), nullable=True),
            sa.Column("total_estimated_cost", sa.Float(), nullable=True),
            sa.Column("total_actual_cost", sa.Float(), nullable=True),
            sa.Column("cost_variance_percent", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("reconciled_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_migration_cost_actuals_job_id", "migration_cost_actuals", ["job_id"])
        op.create_index("ix_migration_cost_actuals_run_id", "migration_cost_actuals", ["run_id"], unique=True)


def downgrade() -> None:
    for table in [
        "migration_cost_actuals",
        "migration_snowflake_queries",
        "migration_cost_estimates",
        "job_run_leases",
    ]:
        if _has_table(op.get_bind(), table):
            op.drop_table(table)
