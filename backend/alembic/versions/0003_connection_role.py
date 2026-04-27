"""add connection role

Revision ID: 0003_connection_role
Revises: 0002_recon_fields
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0003_connection_role"
down_revision = "0002_recon_fields"
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
    if bind.dialect.name == "postgresql":
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'connectionrole') THEN
                    CREATE TYPE connectionrole AS ENUM ('source', 'target', 'both');
                END IF;
            END $$;
        """)
        if not _has_column(bind, "connections", "connection_role"):
            op.add_column(
                "connections",
                sa.Column(
                    "connection_role",
                    sa.Enum("source", "target", "both", name="connectionrole", create_type=False),
                    nullable=False,
                    server_default="both",
                ),
            )
    elif not _has_column(bind, "connections", "connection_role"):
        op.add_column("connections", sa.Column("connection_role", sa.String(20), nullable=False, server_default="both"))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "connections", "connection_role"):
        op.drop_column("connections", "connection_role")
