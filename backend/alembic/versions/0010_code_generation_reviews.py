"""persist code generation artifacts and judge pass reviews

Revision ID: 0010_code_generation_reviews
Revises: 0009_replication_control_plane
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_code_generation_reviews"
down_revision = "0009_replication_control_plane"
branch_labels = None
depends_on = None


def _has_table(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _json_type(bind):
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    json_t = _json_type(bind)

    if not _has_table(bind, "code_generation_artifacts"):
        op.create_table(
            "code_generation_artifacts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("generation_type", sa.String(length=80), nullable=False),
            sa.Column("source_language", sa.String(length=120), nullable=True),
            sa.Column("target_language", sa.String(length=120), nullable=True),
            sa.Column("prompt", sa.Text(), nullable=True),
            sa.Column("source_code", sa.Text(), nullable=True),
            sa.Column("metadata_json", json_t, nullable=False),
            sa.Column("generated_code", sa.Text(), nullable=True),
            sa.Column("technical_design_document", json_t, nullable=False),
            sa.Column("initial_judge_review", json_t, nullable=False),
            sa.Column("safety_notes", json_t, nullable=False),
            sa.Column("execution_ready", sa.Boolean(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for col in ("user_id", "generation_type", "execution_ready", "status", "created_at"):
            op.create_index(f"ix_code_generation_artifacts_{col}", "code_generation_artifacts", [col])

    if not _has_table(bind, "code_generation_judge_reviews"):
        op.create_table(
            "code_generation_judge_reviews",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("artifact_id", sa.String(), sa.ForeignKey("code_generation_artifacts.id"), nullable=False),
            sa.Column("reviewer_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=True),
            sa.Column("improvement_points", json_t, nullable=False),
            sa.Column("blocking_issues", json_t, nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        for col in ("artifact_id", "reviewer_id", "status", "created_at"):
            op.create_index(f"ix_code_generation_judge_reviews_{col}", "code_generation_judge_reviews", [col])


def downgrade() -> None:
    for table in ("code_generation_judge_reviews", "code_generation_artifacts"):
        op.drop_table(table)
