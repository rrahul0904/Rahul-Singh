from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from core.auth import get_current_user, require_admin
from core.audit import AuditAction, extract_request_context, record as audit_record
from core.config import settings
from core.database import get_db
from models import User
from services.demo_seed import bootstrap_demo_workspace, demo_summary

router = APIRouter()


def _demo_allowed() -> bool:
    return settings.DEMO_MODE_ENABLED or settings.ENVIRONMENT != "production"


@router.get("/status")
async def demo_status(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await demo_summary(db)
    return {
        "enabled": _demo_allowed(),
        **summary,
    }


@router.post("/bootstrap")
async def demo_bootstrap(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not _demo_allowed():
        raise HTTPException(403, "Demo bootstrap is disabled in this environment")

    result = await bootstrap_demo_workspace(db, user)
    ctx = {k: v for k, v in extract_request_context(request).items() if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action="demo.bootstrapped",
        status="success",
        user_id=user.id,
        user_email=user.email,
        resource="demo:workspace",
        details={"created": result.get("created", False), "counts": result.get("counts", {})},
        **ctx,
    )
    return result


@router.post("/seed-postgres")
async def seed_postgres_demo_source(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a small local Postgres source table for end-to-end migration tests."""
    if not _demo_allowed():
        raise HTTPException(403, "Demo seed is disabled in this environment")
    await db.execute(text("CREATE SCHEMA IF NOT EXISTS demo_src"))
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS demo_src.customers (
            customer_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            status TEXT,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """))
    await db.execute(text("""
        INSERT INTO demo_src.customers (customer_id, first_name, last_name, email, status, updated_at)
        VALUES
            (1, 'Rahul', 'Singh', 'rahul@example.com', 'active', now() - interval '3 days'),
            (2, 'Anjali', 'Patel', 'anjali@example.com', 'active', now() - interval '2 days'),
            (3, 'John', 'Miller', 'john@example.com', 'inactive', now() - interval '1 day'),
            (4, 'Priya', 'Shah', 'priya@example.com', 'active', now())
        ON CONFLICT (customer_id) DO UPDATE SET
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            email = EXCLUDED.email,
            status = EXCLUDED.status,
            updated_at = EXCLUDED.updated_at
    """))
    count = (await db.execute(text("SELECT COUNT(*) FROM demo_src.customers"))).scalar_one()
    await db.commit()
    return {
        "success": True,
        "schema": "demo_src",
        "table": "customers",
        "rows": int(count),
        "connection_hint": {
            "type": "postgres",
            "role": "source",
            "host": "postgres",
            "port": 5432,
            "database": "uma",
            "user": "uma",
            "password": "uma",
        },
    }
