"""add reconciliation fields to validation_rules

Revision ID: 0002_recon_fields
Revises: 0001_initial
Create Date: 2026-04-26

Adds:
  - validation_rules.source_connection_id (nullable FK to connections)
  - validation_rules.source_dataset (nullable string)
  - validation_rules.source_table (nullable string)
  - validation_rules.primary_key_columns (nullable JSON)

Idempotent: each ADD COLUMN is wrapped to skip if the column already exists,
so re-running against a fresh DB initialised by create_all() is safe.
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0002_recon_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "validation_rules", "source_connection_id"):
        op.add_column(
            "validation_rules",
            sa.Column("source_connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
        )
    if not _has_column(bind, "validation_rules", "source_dataset"):
        op.add_column("validation_rules", sa.Column("source_dataset", sa.String(255), nullable=True))
    if not _has_column(bind, "validation_rules", "source_table"):
        op.add_column("validation_rules", sa.Column("source_table", sa.String(255), nullable=True))
    if not _has_column(bind, "validation_rules", "primary_key_columns"):
        op.add_column("validation_rules", sa.Column("primary_key_columns", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Best-effort drops; ignored if columns are absent.
    for col in ("primary_key_columns", "source_table", "source_dataset", "source_connection_id"):
        try:
            op.drop_column("validation_rules", col)
        except Exception:
            pass
