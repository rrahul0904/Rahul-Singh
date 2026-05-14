"""code generation revisions

Revision ID: 0011_codegen_revisions
Revises: 0010_code_generation_reviews
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_codegen_revisions"
down_revision = "0010_code_generation_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("code_generation_artifacts", sa.Column("basis_for_generation", sa.String(length=80), nullable=True))
    op.add_column("code_generation_artifacts", sa.Column("parent_artifact_id", sa.String(), nullable=True))
    op.add_column("code_generation_artifacts", sa.Column("revision_number", sa.Integer(), nullable=True))
    op.create_index("ix_code_generation_artifacts_basis_for_generation", "code_generation_artifacts", ["basis_for_generation"])
    op.create_index("ix_code_generation_artifacts_parent_artifact_id", "code_generation_artifacts", ["parent_artifact_id"])


def downgrade() -> None:
    op.drop_index("ix_code_generation_artifacts_parent_artifact_id", table_name="code_generation_artifacts")
    op.drop_index("ix_code_generation_artifacts_basis_for_generation", table_name="code_generation_artifacts")
    op.drop_column("code_generation_artifacts", "revision_number")
    op.drop_column("code_generation_artifacts", "parent_artifact_id")
    op.drop_column("code_generation_artifacts", "basis_for_generation")
