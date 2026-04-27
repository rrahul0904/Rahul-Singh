"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This migration uses SQLAlchemy's metadata.create_all via ORM models.
    # For full production: replace with explicit op.create_table() calls.
    # This is intentionally a no-op stub so the migration framework is in place —
    # existing installs continue working with init_db() create_all().
    # Run `alembic revision --autogenerate -m "add_x"` for subsequent changes.
    pass


def downgrade() -> None:
    pass
