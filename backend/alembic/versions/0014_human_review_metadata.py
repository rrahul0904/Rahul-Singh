"""add human review item metadata

Revision ID: 0014_human_review_metadata
Revises: 0013_control_plane_foundation
Create Date: 2026-05-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_human_review_metadata"
down_revision = "0013_control_plane_foundation"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "human_review_items",
        sa.Column("metadata_json", _json_type(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_human_review_items_updated_at", "human_review_items", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_human_review_items_updated_at", table_name="human_review_items")
    op.drop_column("human_review_items", "metadata_json")
