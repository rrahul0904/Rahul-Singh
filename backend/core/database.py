"""
UMA Platform — Async Database (PostgreSQL via SQLAlchemy + asyncpg)
Production-tuned: connection pool, statement timeout, pre-ping.
"""

import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

logger = logging.getLogger("uma.db")


# Statement timeout in ms — prevents runaway queries from hanging the DB
STATEMENT_TIMEOUT_MS = 60_000   # 60s


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "application_name":   "uma-platform",
            "statement_timeout":  str(STATEMENT_TIMEOUT_MS),
            "idle_in_transaction_session_timeout": "30000",  # 30s
        },
        "command_timeout": 60,
    },
)


AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db():
    """
    Create all tables on startup.
    In production, migrations should be run with Alembic; this is a safety net
    that ensures tables exist for local dev / fresh installs.
    """
    # Register all models so they're in metadata
    import models          # noqa  — User, Project, Job, etc.
    from core import audit # noqa  — AuditLog

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight compatibility migration for existing local installs.
        # Alembic should own this in production, but create_all will not add
        # newly introduced nullable columns to existing tables.
        if settings.DATABASE_URL.startswith("postgresql"):
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP NULL"))
            await conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'connectionrole') THEN
                        CREATE TYPE connectionrole AS ENUM ('source', 'target', 'both');
                    END IF;
                END $$;
            """))
            await conn.execute(text("ALTER TABLE connections ADD COLUMN IF NOT EXISTS connection_role connectionrole NOT NULL DEFAULT 'both'"))
            await conn.execute(text("ALTER TABLE sync_profiles ADD COLUMN IF NOT EXISTS job_id VARCHAR NULL"))
            await conn.execute(text("ALTER TABLE sync_profiles ADD COLUMN IF NOT EXISTS source_dataset VARCHAR(255) NULL"))
            await conn.execute(text("ALTER TABLE sync_profiles ADD COLUMN IF NOT EXISTS source_table VARCHAR(255) NULL"))
            await conn.execute(text("ALTER TABLE sync_profiles ADD COLUMN IF NOT EXISTS target_schema VARCHAR(255) NULL"))
            await conn.execute(text("ALTER TABLE sync_profiles ADD COLUMN IF NOT EXISTS target_table VARCHAR(255) NULL"))
            await conn.execute(text("ALTER TABLE sync_profiles ADD COLUMN IF NOT EXISTS task_config JSONB NOT NULL DEFAULT '{}'::jsonb"))
            await conn.execute(text("ALTER TABLE code_generation_artifacts ADD COLUMN IF NOT EXISTS basis_for_generation VARCHAR(80) DEFAULT 'user_prompt_only'"))
            await conn.execute(text("ALTER TABLE code_generation_artifacts ADD COLUMN IF NOT EXISTS parent_artifact_id VARCHAR NULL"))
            await conn.execute(text("ALTER TABLE code_generation_artifacts ADD COLUMN IF NOT EXISTS revision_number INTEGER DEFAULT 1"))
            await conn.execute(text("ALTER TABLE human_review_items ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb"))
    logger.info("Database tables ready (create_all + compatibility migrations)")


async def get_db():
    """FastAPI dependency — yields an async session with commit/rollback on exit."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
