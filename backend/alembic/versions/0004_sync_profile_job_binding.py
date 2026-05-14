"""bind sync profiles to real managed jobs

Revision ID: 0004_sync_profile_job_binding
Revises: 0003_connection_role
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0004_sync_profile_job_binding"
down_revision = "0003_connection_role"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    try:
        return column in [c["name"] for c in insp.get_columns(table)]
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "sync_profiles", "job_id"):
        op.add_column("sync_profiles", sa.Column("job_id", sa.String(), nullable=True))
        op.create_index("ix_sync_profiles_job_id", "sync_profiles", ["job_id"], unique=False)
    if not _has_column(bind, "sync_profiles", "source_dataset"):
        op.add_column("sync_profiles", sa.Column("source_dataset", sa.String(length=255), nullable=True))
    if not _has_column(bind, "sync_profiles", "source_table"):
        op.add_column("sync_profiles", sa.Column("source_table", sa.String(length=255), nullable=True))
    if not _has_column(bind, "sync_profiles", "target_schema"):
        op.add_column("sync_profiles", sa.Column("target_schema", sa.String(length=255), nullable=True))
    if not _has_column(bind, "sync_profiles", "target_table"):
        op.add_column("sync_profiles", sa.Column("target_table", sa.String(length=255), nullable=True))
    if not _has_column(bind, "sync_profiles", "task_config"):
        if bind.dialect.name == "postgresql":
            op.add_column(
                "sync_profiles",
                sa.Column("task_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            )
        else:
            op.add_column(
                "sync_profiles",
                sa.Column("task_config", sa.JSON(), nullable=False, server_default="{}"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "sync_profiles", "task_config"):
        op.drop_column("sync_profiles", "task_config")
    if _has_column(bind, "sync_profiles", "target_table"):
        op.drop_column("sync_profiles", "target_table")
    if _has_column(bind, "sync_profiles", "target_schema"):
        op.drop_column("sync_profiles", "target_schema")
    if _has_column(bind, "sync_profiles", "source_table"):
        op.drop_column("sync_profiles", "source_table")
    if _has_column(bind, "sync_profiles", "source_dataset"):
        op.drop_column("sync_profiles", "source_dataset")
    if _has_column(bind, "sync_profiles", "job_id"):
        try:
            op.drop_index("ix_sync_profiles_job_id", table_name="sync_profiles")
        except Exception:
            pass
        op.drop_column("sync_profiles", "job_id")
