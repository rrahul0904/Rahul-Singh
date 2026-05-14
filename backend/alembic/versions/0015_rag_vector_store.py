"""add RAG document and chunk tables

Revision ID: 0015_rag_vector_store
Revises: 0014_human_review_metadata
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_rag_vector_store"
down_revision = "0014_human_review_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=True, index=True),
        sa.Column("artifact_id", sa.String(), nullable=True, index=True),
        sa.Column("job_id", sa.String(), nullable=True, index=True),
        sa.Column("artifact_type", sa.String(length=120), nullable=True, index=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("run_id", sa.String(), nullable=True, index=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, default=0),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rag_chunks_run_doc", "rag_chunks", ["run_id", "document_id"])


def downgrade() -> None:
    op.drop_index("ix_rag_chunks_run_doc", table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_table("rag_documents")
